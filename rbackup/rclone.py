from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from .config import Config
from .errors import RbackupError

log = logging.getLogger(__name__)

MISSING_REMOTE_CODES = {3, 4}

# rclone 的 --stats-one-line 形如：
#   12.345 MiB / 41.454 MiB, 30%, 6.005 MiB/s, ETA 5s
# 注意：写进管道时各段之间没有任何分隔符，是首尾相接的，所以用正则逐段抽取。
_PROGRESS_RE = re.compile(
    r"([\d.]+)\s+([KMGTP]?i?B)\s*/\s*([\d.]+)\s+([KMGTP]?i?B)\s*,\s*(\d+)%"
    r"(?:\s*,\s*([\d.]+)\s+([KMGTP]?i?B)/s)?"
    # ETA 只会是 5s / 1m30s 这类时长；用 \S+ 会把下一段的开头数字一起吞掉
    r"(?:\s*,\s*ETA\s+(-|(?:\d+\.?\d*[dhms])+))?"
)
_UNIT_BYTES = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "TiB": 1024**4,
    "PiB": 1024**5,
}


def _to_bytes(value: str, unit: str) -> float:
    return float(value) * _UNIT_BYTES.get(unit, 1)


def parse_progress(text: str) -> dict[str, Any] | None:
    """从 rclone 的 stats 文本里取最后一段进度；取不到返回 None。"""
    last = None
    for match in _PROGRESS_RE.finditer(text):
        last = match
    if last is None:
        return None
    speed = None
    if last.group(6) is not None:
        speed = _to_bytes(last.group(6), last.group(7))
    return {
        "percent": int(last.group(5)),
        "bytes": _to_bytes(last.group(1), last.group(2)),
        "total_bytes": _to_bytes(last.group(3), last.group(4)),
        "speed": speed,
        "eta": last.group(8) if last.group(8) not in (None, "-") else None,
    }



class RcloneError(RbackupError):
    exit_code = 1

    def __init__(
        self,
        message: str,
        *,
        argv: Sequence[str] = (),
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class RcloneResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _tail(value: str, limit: int = 6000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return "…（截断）\n" + text[-limit:]


class Rclone:
    """对 rclone 命令行的薄封装：所有调用都使用参数数组，不经过 shell。"""

    def __init__(self, config: Config) -> None:
        self.binary = config.rclone_bin
        self.config = config
        self._version: str | None = None

    def _global_args(self) -> list[str]:
        args: list[str] = []
        if self.config.rclone_config:
            args.extend(["--config", str(self.config.rclone_config)])
        args.extend(
            [
                "--retries",
                str(self.config.retries),
                "--low-level-retries",
                "10",
                "--contimeout",
                "30s",
                "--timeout",
                "5m",
                "--checkers",
                str(self.config.checkers),
                "--transfers",
                str(self.config.transfers),
            ]
        )
        if self.config.bwlimit:
            args.extend(["--bwlimit", self.config.bwlimit])
        if self.config.follow_symlinks:
            args.append("--copy-links")
        else:
            # 不跟随符号链接，把它保存成可还原的小文件。
            args.append("--links")
        return args

    def _argv(
        self,
        args: Sequence[str],
        *,
        stats: bool = False,
        stats_interval: str = "5s",
        progress: bool = False,
    ) -> list[str]:
        argv = [self.binary, *self._global_args()]
        if stats:
            argv.extend(["--stats-one-line", "--stats", stats_interval])
        else:
            argv.extend(["--stats", "0"])
        if progress:
            # 输出被重定向时 rclone 默认不刷进度，--progress 强制持续输出
            argv.append("--progress")
        argv.extend(args)
        return argv

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        timeout: float | None = 300,
        input_bytes: bytes | None = None,
        stream: bool = False,
        stats: bool = False,
    ) -> RcloneResult:
        argv = self._argv(args, stats=stats)
        log.debug("rclone: %s", shlex.join(argv))
        env = os.environ.copy()
        env.setdefault("RCLONE_ASK_PASSWORD", "false")
        if stream:
            # 进度/错误直接给用户看；stdout 留给本工具的 JSON 输出。
            try:
                completed = subprocess.run(
                    argv,
                    stdout=subprocess.DEVNULL,
                    stderr=None,
                    input=input_bytes,
                    timeout=timeout,
                    env=env,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise RcloneError(
                    f"找不到 rclone 可执行文件：{self.binary!r}。"
                    "请安装 rclone，或在配置中设置 rclone_bin。",
                    argv=argv,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RcloneError(
                    f"rclone 超时（{timeout} 秒）：{shlex.join(argv)}", argv=argv
                ) from exc
            result = RcloneResult(argv, completed.returncode, "", "")
        else:
            try:
                completed = subprocess.run(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    input=input_bytes,
                    timeout=timeout,
                    env=env,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise RcloneError(
                    f"找不到 rclone 可执行文件：{self.binary!r}。"
                    "请安装 rclone，或在配置中设置 rclone_bin。",
                    argv=argv,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RcloneError(
                    f"rclone 超时（{timeout} 秒）：{shlex.join(argv)}", argv=argv
                ) from exc
            stdout = completed.stdout.decode("utf-8", errors="replace")
            stderr = completed.stderr.decode("utf-8", errors="replace")
            result = RcloneResult(argv, completed.returncode, stdout, stderr)

        if check and not result.ok:
            details = _tail(result.stderr or result.stdout)
            raise RcloneError(
                f"rclone 失败（退出码 {result.returncode}）：{shlex.join(argv)}"
                + (f"\n{details}" if details else "\n（rclone 输出见上方）"),
                argv=argv,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def run_with_progress(
        self,
        args: Sequence[str],
        *,
        on_progress: Callable[[dict[str, Any]], None],
        timeout: float | None = None,
        interval: str = "500ms",
        check: bool = True,
    ) -> RcloneResult:
        """运行 rclone，并把 stats 进度实时回调出去。

        与 ``stream=True`` 的区别：stdout 由本程序接管用来解析进度，不再丢给终端，
        因此网页端能拿到百分比；stderr 仍然被收集，用于失败时展示原因。
        """
        argv = self._argv(args, stats=True, stats_interval=interval, progress=True)
        log.debug("rclone: %s", shlex.join(argv))
        env = os.environ.copy()
        env.setdefault("RCLONE_ASK_PASSWORD", "false")

        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RcloneError(
                f"找不到 rclone 可执行文件：{self.binary!r}。"
                "请安装 rclone，或在配置中设置 rclone_bin。",
                argv=argv,
            ) from exc

        state = {"timed_out": False}

        def _watchdog() -> None:
            if proc.poll() is None:
                state["timed_out"] = True
                proc.kill()

        timer = None
        if timeout is not None:
            timer = threading.Timer(timeout, _watchdog)
            timer.daemon = True
            timer.start()

        stderr_chunks: list[bytes] = []

        def _drain_stderr() -> None:
            try:
                stderr_chunks.append(proc.stderr.read() or b"")
            except Exception:  # 进程被强杀时管道可能已关闭
                log.debug("读取 rclone stderr 失败", exc_info=True)

        drainer = threading.Thread(target=_drain_stderr, daemon=True)
        drainer.start()

        buffer = ""
        try:
            assert proc.stdout is not None
            while True:
                # read1 有数据就返回，不会等满缓冲区，进度才够及时
                chunk = proc.stdout.read1(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                if len(buffer) > 16384:
                    buffer = buffer[-8192:]
                info = parse_progress(buffer)
                if info is not None:
                    try:
                        on_progress(info)
                    except Exception:  # 回调出错不能影响传输
                        log.debug("进度回调异常", exc_info=True)
        finally:
            if timer is not None:
                timer.cancel()
            proc.wait()
            drainer.join(timeout=5)

        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        if state["timed_out"]:
            raise RcloneError(
                f"rclone 超时（{timeout} 秒）：{shlex.join(argv)}", argv=argv
            )
        result = RcloneResult(argv, proc.returncode, "", stderr_text)
        if check and not result.ok:
            details = _tail(stderr_text)
            raise RcloneError(
                f"rclone 失败（退出码 {result.returncode}）：{shlex.join(argv)}"
                + (f"\n{details}" if details else "\n（rclone 输出见上方）"),
                argv=argv,
                returncode=result.returncode,
                stderr=stderr_text,
            )
        return result

    def version(self) -> str:
        if self._version is None:
            result = self.run(["version"], timeout=30)
            first = result.stdout.splitlines()[0].strip() if result.stdout else ""
            self._version = first or "rclone（版本未知）"
        return self._version

    def listremotes(self) -> list[str]:
        result = self.run(["listremotes"], timeout=30)
        return [line.strip().rstrip(":") for line in result.stdout.splitlines() if line.strip()]

    def remote_config(self, name: str) -> dict[str, str]:
        """读取 crypt remote 的非敏感配置（type 和底层 remote）。

        不返回 password/password2，也不把配置内容写进日志或异常。
        """
        result = self.run(["config", "show", name], timeout=30, check=False)
        if not result.ok:
            detail = _tail(result.stderr)
            raise RcloneError(
                f"无法读取 rclone remote {name!r} 的配置（退出码 {result.returncode}）"
                + (f"\n{detail}" if detail else ""),
                argv=result.argv,
                returncode=result.returncode,
            )
        config: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if not separator:
                continue
            normalized = key.strip().lower()
            if normalized in {"type", "remote"}:
                config[normalized] = value.strip().strip('"').strip("'")
        if "type" not in config:
            raise RcloneError(
                f"rclone remote {name!r} 没有 type 配置项",
                argv=result.argv,
                returncode=result.returncode,
            )
        return config

    def remote_type(self, name: str) -> str:
        return self.remote_config(name)["type"]

    def lsjson(
        self,
        path: str,
        *,
        recursive: bool = True,
        files_only: bool = False,
        dirs_only: bool = False,
        stat: bool = False,
        filters: Iterable[str] = (),
        timeout: float | None = 120,
    ) -> list[dict[str, Any]]:
        args = ["lsjson"]
        if recursive:
            args.append("-R")
        if files_only:
            args.append("--files-only")
        if dirs_only:
            args.append("--dirs-only")
        if stat:
            args.append("--stat")
        args.append("--no-mimetype")
        for pattern in filters:
            args.append(f"--exclude={pattern}")
        args.append(path)
        result = self.run(args, timeout=timeout)
        text = result.stdout.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RcloneError(
                f"rclone lsjson 返回了无法解析的 JSON：{path}",
                argv=result.argv,
                stdout=result.stdout,
                stderr=result.stderr,
            ) from exc
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        if not isinstance(data, list):
            raise RcloneError(f"rclone lsjson 返回了意外的 JSON 类型：{type(data).__name__}")
        return data

    def list_files(
        self, path: str, *, filters: Iterable[str] = (), timeout: float | None = 300
    ) -> list[dict[str, Any]]:
        return self.lsjson(
            path,
            recursive=True,
            files_only=True,
            filters=filters,
            timeout=timeout,
        )

    def list_dirs(
        self,
        path: str,
        *,
        recursive: bool = False,
        filters: Iterable[str] = (),
        timeout: float | None = 120,
    ) -> list[dict[str, Any]]:
        return self.lsjson(
            path,
            recursive=recursive,
            dirs_only=True,
            filters=filters,
            timeout=timeout,
        )

    def stat(self, path: str) -> dict[str, Any] | None:
        try:
            rows = self.lsjson(path, recursive=False, stat=True, timeout=60)
        except RcloneError as exc:
            if exc.returncode in MISSING_REMOTE_CODES:
                return None
            raise
        return rows[0] if rows else None

    def cat(self, path: str, *, timeout: float = 60) -> str:
        result = self.run(["cat", path], timeout=timeout)
        return result.stdout

    def rcat(self, path: str, data: bytes, *, timeout: float = 120) -> None:
        self.run(
            ["rcat", "--size", str(len(data)), path],
            input_bytes=data,
            timeout=timeout,
        )

    def copy(
        self,
        source: str,
        destination: str,
        *,
        backup_dir: str | None = None,
        dry_run: bool = False,
        filters: Iterable[str] = (),
        create_empty_dirs: bool = True,
        timeout: float | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        args = ["copy"]
        if backup_dir:
            args.extend(["--backup-dir", backup_dir])
        if dry_run:
            args.append("--dry-run")
        if create_empty_dirs:
            args.append("--create-empty-src-dirs")
        for pattern in filters:
            args.append(f"--exclude={pattern}")
        args.extend([source, destination])
        if on_progress is not None:
            self.run_with_progress(args, on_progress=on_progress, timeout=timeout)
        else:
            self.run(args, timeout=timeout, stream=True, stats=True)

    def copyto(
        self,
        source: str,
        destination: str,
        *,
        backup_dir: str | None = None,
        dry_run: bool = False,
        timeout: float | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        args = ["copyto"]
        if backup_dir:
            args.extend(["--backup-dir", backup_dir])
        if dry_run:
            args.append("--dry-run")
        args.extend([source, destination])
        if on_progress is not None:
            self.run_with_progress(args, on_progress=on_progress, timeout=timeout)
        else:
            self.run(args, timeout=timeout, stream=True, stats=True)

    def cryptcheck(
        self,
        local_path: str,
        remote_path: str,
        *,
        one_way: bool = False,
        filters: Iterable[str] = (),
        timeout: float | None = None,
    ) -> RcloneResult:
        args = ["cryptcheck"]
        if one_way:
            args.append("--one-way")
        for pattern in filters:
            args.append(f"--exclude={pattern}")
        args.extend([local_path, remote_path])
        return self.run(args, timeout=timeout, check=False)

    def purge(self, path: str, *, dry_run: bool = False) -> None:
        args = ["purge"]
        if dry_run:
            args.append("--dry-run")
        args.append(path)
        self.run(args, timeout=600, stream=True)

    def deletefile(self, path: str, *, dry_run: bool = False) -> None:
        args = ["deletefile"]
        if dry_run:
            args.append("--dry-run")
        args.append(path)
        self.run(args, timeout=300, stream=True)

    def delete(
        self, path: str, *, dry_run: bool = False, filters: Iterable[str] = ()
    ) -> None:
        args = ["delete"]
        if dry_run:
            args.append("--dry-run")
        for pattern in filters:
            args.append(f"--exclude={pattern}")
        args.append(path)
        self.run(args, timeout=600, stream=True)

    def mkdir(self, path: str) -> None:
        self.run(["mkdir", path], timeout=60)
