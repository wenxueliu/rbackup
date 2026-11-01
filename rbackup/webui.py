from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .app import App, local_target_path
from .backup import run_backup
from .config import default_config_path
from .doctor import checks_ok, collect_checks
from .errors import ConfigError, RbackupError
from .rclone import Rclone
from .webconfig import (
    config_to_payload,
    normalize_payload,
    read_payload,
    save_payload,
    validate_payload,
)
from . import webfiles
from .webpage import render_page

log = logging.getLogger(__name__)

MAX_BODY = 1_000_000


def rclone_for_web(payload: dict[str, Any], config_path: Path) -> Rclone:
    normalized = normalize_payload(payload)
    rclone_bin = os.path.expandvars(os.path.expanduser(normalized["rclone_bin"]))
    if not rclone_bin:
        raise ConfigError("rclone_bin 不能为空")
    if (os.sep in rclone_bin or (os.altsep and os.altsep in rclone_bin)) and not Path(
        rclone_bin
    ).is_absolute():
        rclone_bin = str((config_path.parent / rclone_bin).resolve(strict=False))
    raw_config = normalized["rclone_config"].strip()
    rclone_config: Path | None = None
    if raw_config:
        rclone_config = Path(
            os.path.expandvars(os.path.expanduser(raw_config))
        )
        if not rclone_config.is_absolute():
            rclone_config = config_path.parent / rclone_config
        rclone_config = rclone_config.resolve(strict=False)
        if not rclone_config.exists():
            raise ConfigError(f"rclone_config 文件不存在：{rclone_config}")
    settings = SimpleNamespace(
        rclone_bin=rclone_bin,
        rclone_config=rclone_config,
        retries=normalized["retries"],
        checkers=normalized["checkers"],
        transfers=normalized["transfers"],
        bwlimit=normalized["bwlimit"] or None,
        follow_symlinks=normalized["follow_symlinks"],
    )
    return Rclone(settings)  # type: ignore[arg-type]


@dataclass
class WebState:
    config_path: Path
    token: str
    payload: dict[str, Any]
    exists: bool
    load_error: str | None
    lock: threading.Lock = field(default_factory=threading.Lock)
    mutation_lock: threading.Lock = field(default_factory=threading.Lock)
    port: int = 0
    progress_lock: threading.Lock = field(default_factory=threading.Lock)
    progress: dict[str, Any] = field(
        default_factory=lambda: {
            "active": False,
            "op": "",
            "label": "",
            "index": 0,
            "total": 0,
            "path": "",
            "percent": 0,
            "bytes": 0,
            "total_bytes": 0,
            "speed": None,
            "eta": None,
            "overall": 0,
            "error": None,
        }
    )

    @classmethod
    def create(cls, config_path: Path, token: str) -> "WebState":
        path = config_path.expanduser().resolve(strict=False)
        payload, exists, error = read_payload(path)
        return cls(
            config_path=path,
            token=token,
            payload=payload,
            exists=exists,
            load_error=error,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            "path": str(self.config_path),
            "exists": self.exists,
            "payload": self.payload,
            "load_error": self.load_error,
        }

    def reload(self) -> dict[str, Any]:
        with self.lock:
            self.payload, self.exists, self.load_error = read_payload(self.config_path)
            return self.snapshot()

    def remotes(self, payload: dict[str, Any]) -> list[str]:
        return rclone_for_web(payload, self.config_path).listremotes()

    def remote_info(self, payload: dict[str, Any], remote: str) -> dict[str, Any]:
        if not remote:
            raise ConfigError("remote 不能为空")
        rclone = rclone_for_web(payload, self.config_path)
        remote_config = rclone.remote_config(remote)
        target = remote_config.get("remote")
        b_path = local_target_path(target)
        return {
            "ok": True,
            "remote": remote,
            "type": remote_config.get("type", ""),
            "target": target,
            "b_path": str(b_path) if b_path else None,
            "b_exists": bool(b_path and b_path.exists()),
            "b_is_dir": bool(b_path and b_path.is_dir()),
        }

    def check(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = validate_payload(payload, self.config_path)
        app = App.from_config(config)
        checks = collect_checks(app)
        for check in checks:
            if check["name"] == "config":
                # 校验用的是临时文件；页面显示用户实际保存的路径。
                check["detail"] = str(self.config_path)
        return {
            "ok": True,
            "passed": checks_ok(checks),
            "b_path": str(app.b_path) if app.b_path else None,
            "checks": checks,
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            config, backup = save_payload(payload, self.config_path)
            self.payload = config_to_payload(config)
            self.exists = True
            self.load_error = None
            result = self.snapshot()
            result.update(
                {
                    "backup": str(backup) if backup else None,
                }
            )
            return result

    # --- 进度 ---------------------------------------------------------

    def progress_snapshot(self) -> dict[str, Any]:
        with self.progress_lock:
            data = dict(self.progress)
        started = data.pop("started_at", None)
        data["elapsed"] = (
            round(time.monotonic() - started, 1) if started is not None else 0.0
        )
        data["ok"] = True
        return data

    def _progress_begin(self, op: str, label: str) -> None:
        with self.progress_lock:
            self.progress = {
                "active": True,
                "op": op,
                "label": label,
                "index": 0,
                "total": 0,
                "path": "",
                "percent": 0,
                "bytes": 0,
                "total_bytes": 0,
                "speed": None,
                "eta": None,
                "overall": 0,
                "error": None,
                "started_at": time.monotonic(),
            }

    def _progress_event(self, info: dict[str, Any]) -> None:
        with self.progress_lock:
            data = self.progress
            if info.get("index"):
                data["index"] = int(info["index"])
            if info.get("total"):
                data["total"] = int(info["total"])
            if info.get("path"):
                data["path"] = str(info["path"])
            if info.get("percent") is not None:
                data["percent"] = int(info["percent"])
            for key in ("bytes", "total_bytes", "speed", "eta"):
                if info.get(key) is not None:
                    data[key] = info[key]
            total = int(data["total"] or 0)
            index = int(data["index"] or 0)
            percent = int(data["percent"] or 0)
            if total > 0 and index > 0:
                finished = index - 1
                data["overall"] = max(
                    0, min(100, int(((finished + percent / 100.0) / total) * 100))
                )
            else:
                data["overall"] = max(0, min(100, percent))

    def _progress_end(self, error: str | None = None) -> None:
        with self.progress_lock:
            self.progress["active"] = False
            self.progress["error"] = error
            if error is None:
                self.progress["percent"] = 100
                self.progress["overall"] = 100

    # --- A/B 对比与写操作 ---------------------------------------------

    def _app(self, payload: dict[str, Any]) -> App:
        return webfiles.app_from_payload(payload, self.config_path)

    def diff(self, payload: dict[str, Any], names: Any = None) -> dict[str, Any]:
        return webfiles.compute_diff(self._app(payload), _name_list(names))

    def upload(
        self, payload: dict[str, Any], category: Any, paths: Any, dry_run: Any = False
    ) -> dict[str, Any]:
        app = self._app(payload)
        name = _category_name(category)
        with self.mutation_lock:
            self._progress_begin("upload", f"上传到 B · {name}")
            failure: str | None = None
            try:
                result = webfiles.upload_paths(
                    app,
                    name,
                    paths,
                    dry_run=_flag(dry_run),
                    on_progress=self._progress_event,
                )
            except RbackupError as exc:
                failure = str(exc)
                raise
            else:
                if result.get("failed"):
                    failure = f"{result['failed']} 项失败，详见结果"
                return result
            finally:
                self._progress_end(failure)

    def remove(
        self, payload: dict[str, Any], category: Any, paths: Any, dry_run: Any = False
    ) -> dict[str, Any]:
        app = self._app(payload)
        with self.mutation_lock:
            return webfiles.delete_paths(
                app, _category_name(category), paths, dry_run=_flag(dry_run)
            )

    def remove_local(
        self, payload: dict[str, Any], category: Any, paths: Any, dry_run: Any = False
    ) -> dict[str, Any]:
        app = self._app(payload)
        with self.mutation_lock:
            return webfiles.delete_local_paths(
                app, _category_name(category), paths, dry_run=_flag(dry_run)
            )

    def restore(
        self,
        payload: dict[str, Any],
        category: Any,
        paths: Any,
        dry_run: Any = False,
        overwrite: Any = False,
    ) -> dict[str, Any]:
        app = self._app(payload)
        name = _category_name(category)
        with self.mutation_lock:
            self._progress_begin("restore", f"恢复到 A · {name}")
            failure: str | None = None
            try:
                result = webfiles.restore_paths(
                    app,
                    name,
                    paths,
                    dry_run=_flag(dry_run),
                    overwrite=_flag(overwrite),
                    on_progress=self._progress_event,
                )
            except RbackupError as exc:
                failure = str(exc)
                raise
            else:
                if result.get("failed"):
                    failure = f"{result['failed']} 项失败，详见结果"
                return result
            finally:
                self._progress_end(failure)

    def rebaseline(self, payload: dict[str, Any], names: Any = None) -> dict[str, Any]:
        app = self._app(payload)
        with self.mutation_lock:
            return webfiles.rebaseline(app, _name_list(names))

    def backup_now(
        self, payload: dict[str, Any], names: Any = None, force: Any = False
    ) -> dict[str, Any]:
        app = self._app(payload)
        with self.mutation_lock:
            summary = run_backup(
                app,
                list(_name_list(names) or []),
                force=_flag(force),
                json_output=False,
            )
        exit_code = int(summary["exit_code"])
        result: dict[str, Any] = {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "status": summary["status"],
            "version_id": summary["version_id"],
            "device": summary["device"],
            "remote": summary["remote"],
            "categories": summary["categories"],
            "remote_drift": summary["remote_drift"],
            "failures": summary["failures"],
            "local_missing": summary["local_missing"],
            "verify_failures": summary["verify_failures"],
        }
        if exit_code != 0:
            result["error"] = _backup_error_text(summary)
        return result


def _name_list(value: Any) -> list[str] | None:
    """把页面传来的类别数组规范化为 list 或 None（None = 全部）。"""
    if value is None or value == []:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError("categories 必须是字符串数组")
    names = [item.strip() for item in value if item.strip()]
    return names or None


def _category_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("category 必须是非空字符串")
    return value.strip()


def _flag(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ConfigError("dry_run 必须是 true 或 false")
    return value


def _backup_error_text(summary: dict[str, Any]) -> str:
    parts: list[str] = []
    for name, entry in (summary.get("categories") or {}).items():
        error = (entry or {}).get("error")
        if error:
            parts.append(f"{name}: {error}")
    missing = summary.get("local_missing")
    if missing:
        parts.append(f"{missing} 个类别的 A 目录缺失")
    if not parts:
        parts.append(f"退出码 {summary.get('exit_code')}")
    return "备份未完全成功：" + "；".join(parts)[:2000]


def _origin_ok(handler: BaseHTTPRequestHandler, port: int) -> bool:
    origin = handler.headers.get("Origin")
    if origin is None:
        return True
    allowed = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }
    return origin in allowed


def make_handler(state: WebState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "rbackup-web"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # 不记录请求行/query，避免把访问令牌写进日志。
            return

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'",
            )

        def _send_bytes(
            self, status: int, body: bytes, content_type: str
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._security_headers()
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send_json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._send_bytes(
                status, body, "application/json; charset=utf-8"
            )

        def _send_html(self, html: str) -> None:
            self._send_bytes(
                200, html.encode("utf-8"), "text/html; charset=utf-8"
            )

        def _plain(self, status: int, message: str) -> None:
            self._send_bytes(
                status, message.encode("utf-8"), "text/plain; charset=utf-8"
            )

        def _auth(self, *, query: dict[str, list[str]] | None = None) -> bool:
            supplied = self.headers.get("X-RBackup-Token", "")
            if not supplied and query is not None:
                supplied = (query.get("token") or [""])[0]
            if hmac.compare_digest(supplied, state.token):
                return True
            self._send_json(
                403, {"ok": False, "error": "无效或缺失的访问令牌，请使用启动时打印的 URL。"}
            )
            return False

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                query = parse_qs(parsed.query)
                if not self._auth(query=query):
                    return
                self._send_html(render_page(state.token))
                return
            if parsed.path == "/favicon.ico":
                self._send_bytes(204, b"", "image/x-icon")
                return
            if parsed.path == "/api/config":
                if not self._auth():
                    return
                self._send_json(200, state.snapshot())
                return
            if parsed.path == "/api/progress":
                if not self._auth():
                    return
                self._send_json(200, state.progress_snapshot())
                return
            self._send_json(404, {"ok": False, "error": "not found"})

        def _read_json(self) -> dict[str, Any] | None:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                self._send_json(400, {"ok": False, "error": "Content-Length 无效"})
                return None
            if length <= 0 or length > MAX_BODY:
                self._send_json(
                    413,
                    {"ok": False, "error": f"请求体必须在 1..{MAX_BODY} 字节之间"},
                )
                return None
            raw = self.rfile.read(length)
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "请求体不是合法 JSON"})
                return None
            if not isinstance(value, dict):
                self._send_json(400, {"ok": False, "error": "请求体必须是 JSON 对象"})
                return None
            return value

        def _payload_from(self, body: dict[str, Any]) -> dict[str, Any]:
            payload = body.get("payload", body)
            if not isinstance(payload, dict):
                raise ConfigError("payload 必须是对象")
            return payload

        def do_POST(self) -> None:  # noqa: N802
            if not _origin_ok(self, state.port):
                self._send_json(403, {"ok": False, "error": "Origin 不被允许"})
                return
            if not self._auth():
                return
            parsed = urlparse(self.path)
            body = self._read_json()
            if body is None:
                return
            try:
                if parsed.path == "/api/remotes":
                    payload = state.payload.copy()
                    for key in ("rclone_bin", "rclone_config"):
                        if key in body:
                            payload[key] = body[key]
                    self._send_json(
                        200, {"ok": True, "remotes": state.remotes(payload)}
                    )
                    return
                if parsed.path == "/api/remote-info":
                    payload = state.payload.copy()
                    for key in ("rclone_bin", "rclone_config"):
                        if key in body:
                            payload[key] = body[key]
                    remote = body.get("remote")
                    if not isinstance(remote, str):
                        raise ConfigError("remote 必须是字符串")
                    self._send_json(
                        200, state.remote_info(payload, remote)
                    )
                    return
                if parsed.path == "/api/check":
                    self._send_json(200, state.check(self._payload_from(body)))
                    return
                if parsed.path == "/api/save":
                    self._send_json(200, state.save(self._payload_from(body)))
                    return
                if parsed.path == "/api/reload":
                    self._send_json(200, state.reload())
                    return
                if parsed.path == "/api/diff":
                    self._send_json(
                        200,
                        state.diff(self._payload_from(body), body.get("categories")),
                    )
                    return
                if parsed.path == "/api/upload":
                    self._send_json(
                        200,
                        state.upload(
                            self._payload_from(body),
                            body.get("category"),
                            body.get("paths"),
                            body.get("dry_run", False),
                        ),
                    )
                    return
                if parsed.path == "/api/delete":
                    self._send_json(
                        200,
                        state.remove(
                            self._payload_from(body),
                            body.get("category"),
                            body.get("paths"),
                            body.get("dry_run", False),
                        ),
                    )
                    return
                if parsed.path == "/api/delete-local":
                    self._send_json(
                        200,
                        state.remove_local(
                            self._payload_from(body),
                            body.get("category"),
                            body.get("paths"),
                            body.get("dry_run", False),
                        ),
                    )
                    return
                if parsed.path == "/api/restore":
                    self._send_json(
                        200,
                        state.restore(
                            self._payload_from(body),
                            body.get("category"),
                            body.get("paths"),
                            body.get("dry_run", False),
                            body.get("overwrite", False),
                        ),
                    )
                    return
                if parsed.path == "/api/rebaseline":
                    self._send_json(
                        200,
                        state.rebaseline(
                            self._payload_from(body), body.get("categories")
                        ),
                    )
                    return
                if parsed.path == "/api/backup":
                    self._send_json(
                        200,
                        state.backup_now(
                            self._payload_from(body),
                            body.get("categories"),
                            body.get("force", False),
                        ),
                    )
                    return
                self._send_json(404, {"ok": False, "error": "not found"})
            except RbackupError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # 防止页面因单个异常断开
                log.exception("web API 失败")
                self._send_json(500, {"ok": False, "error": f"内部错误：{exc}"})

    return Handler


def resolve_web_config(explicit: str | None) -> Path:
    if explicit:
        return Path(os.path.expandvars(os.path.expanduser(explicit))).resolve(
            strict=False
        )
    env = os.environ.get("RBACKUP_CONFIG")
    if env:
        return Path(os.path.expandvars(os.path.expanduser(env))).resolve(
            strict=False
        )
    local = Path.cwd() / "rbackup.toml"
    if local.exists():
        return local.resolve()
    return default_config_path()


def run_web(
    config_path: str | None,
    *,
    port: int = 8765,
    open_browser: bool = True,
) -> int:
    if not 0 <= port <= 65535:
        raise ConfigError("--port 必须在 0..65535 之间")
    path = resolve_web_config(config_path)
    token = secrets.token_urlsafe(24)
    state = WebState.create(path, token)
    handler = make_handler(state)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        if port == 0:
            raise
        print(f"端口 {port} 不可用，改用随机端口。")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    state.port = server.server_port
    url = f"http://127.0.0.1:{server.server_port}/?token={quote(state.token)}"
    print(f"rbackup 配置页：{url}")
    print(f"配置文件：{state.config_path}")
    print("按 Ctrl+C 停止。")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0
