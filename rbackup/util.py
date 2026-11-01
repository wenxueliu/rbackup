from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AlreadyRunningError


VERSION_ID_RE = r"^\d{8}T\d{6}Z(?:-[0-9a-f]{6})?$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def new_version_id(now: datetime | None = None) -> str:
    """生成按时间排序、同一秒内也不冲突的云端版本目录名。"""
    moment = now or utc_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def version_sort_key(version_id: str) -> str:
    """版本 ID 的时间前缀；校验由 layout 完成。"""
    return version_id[:16]


def human_size(size: int | float | None) -> str:
    if size is None:
        return "-"
    value = float(size)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(size)} B"


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def print_json(value: Any, *, stream: Any = None) -> None:
    target = stream or sys.stdout
    target.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    target.flush()


def safe_text(value: str) -> str:
    """让可能含换行的远端路径在人类可读输出中保持单行。"""
    return (
        value.replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def confirm(question: str, *, default: bool = False) -> bool:
    """只在真实终端询问；管道/计划任务中返回安全默认值。"""
    if not sys.stdin or not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in {"y", "yes", "是", "好"}


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def mtime_close(left: str | None, right: str | None, tolerance: float = 2.0) -> bool:
    """比较远端/本地 mtime；后端精度不同，允许两秒误差。"""
    a = parse_iso_datetime(left)
    b = parse_iso_datetime(right)
    if a is None or b is None:
        return left == right
    return abs((a - b).total_seconds()) <= tolerance


class ProcessLock:
    """跨平台进程锁，防止同一设备同时执行两个 backup/push。

    锁文件只放在系统临时目录，不保存任何数据，不属于本地索引。
    """

    def __init__(self, key: str, *, path: Path | None = None) -> None:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        self.path = path or Path(tempfile.gettempdir()) / f"rbackup-{digest}.lock"
        self._file: Any = None

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError(
                f"另一个 rbackup 进程正在使用同一设备（锁文件：{self.path}）"
            ) from exc
        self._file = handle
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        handle = self._file
        self._file = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
