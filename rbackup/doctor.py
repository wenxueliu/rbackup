from __future__ import annotations

import platform
import socket
import sys
from typing import Any

from .app import App, local_target_path, validate_b_not_nested
from .errors import ConfigError, RbackupError
from .util import print_json


def collect_checks(app: App) -> list[dict[str, Any]]:
    """返回结构化检查结果，供 CLI doctor 和 Web 配置页共用。"""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, *, critical: bool = False) -> None:
        checks.append(
            {"name": name, "ok": ok, "detail": detail, "critical": critical}
        )

    add(
        "python",
        sys.version_info >= (3, 11),
        f"{sys.version.split()[0]} ({platform.platform()})",
        critical=True,
    )
    add("config", True, str(app.config.path), critical=True)

    try:
        version = app.rclone.version()
        add("rclone", True, version, critical=True)
    except RbackupError as exc:
        add("rclone", False, str(exc), critical=True)
        version = None

    if version:
        remote_configured = False
        try:
            remotes = app.rclone.listremotes()
            remote_configured = app.config.remote in remotes
            add(
                "remote",
                remote_configured,
                f"{app.config.remote} "
                + (
                    "已配置"
                    if remote_configured
                    else f"未找到；已有：{', '.join(remotes) or '（无）'}"
                ),
                critical=True,
            )
        except RbackupError as exc:
            add("remote", False, str(exc), critical=True)

        if remote_configured:
            try:
                remote_config = app.rclone.remote_config(app.config.remote)
                remote_type = remote_config.get("type", "")
                add(
                    "remote_type",
                    remote_type == "crypt",
                    f"type={remote_type}"
                    + ("（正确）" if remote_type == "crypt" else "，必须使用 crypt remote"),
                    critical=True,
                )
                b_path = local_target_path(remote_config.get("remote"))
                if b_path is not None:
                    b_ok = b_path.exists() and b_path.is_dir()
                    add(
                        "b_local",
                        b_ok,
                        f"{b_path} "
                        + (
                            "存在，作为 B 本地同步目录"
                            if b_ok
                            else "不存在或不是目录；请先创建 B 并让网盘客户端同步它"
                        ),
                        critical=True,
                    )
                    if b_ok:
                        try:
                            validate_b_not_nested(app.config, b_path)
                            add("b_isolation", True, "A/B 目录不嵌套")
                        except ConfigError as exc:
                            add("b_isolation", False, str(exc), critical=True)
                else:
                    add(
                        "b_local",
                        True,
                        "底层不是本地目录（直接使用云端 crypt remote）",
                    )
            except RbackupError as exc:
                add("remote_type", False, str(exc), critical=True)

        try:
            app.rclone.list_dirs(f"{app.config.remote}:")
            add("crypt_root", True, f"{app.config.remote}: 可列出", critical=True)
        except RbackupError as exc:
            add("crypt_root", False, str(exc), critical=True)

    for name, category in app.config.categories.items():
        exists = category.path.exists() and category.path.is_dir()
        add(
            f"category:{name}",
            exists,
            f"{category.path} " + ("存在" if exists else "不存在（备份时会跳过）"),
            critical=False,
        )

    try:
        state = app.state.load()
        if state:
            summary = state.summary()
            add(
                "state",
                True,
                f"{app.layout.state_file}；status={summary['status']}，"
                f"version={summary['version_id']}",
            )
            if state.hostname and state.hostname != socket.gethostname():
                add(
                    "device_identity",
                    False,
                    f"状态由 {state.hostname!r} 写入，当前主机是 "
                    f"{socket.gethostname()!r}；确认 device 唯一",
                )
        else:
            add("state", True, "尚未建立（首次备份会创建）")
    except RbackupError as exc:
        add("state", False, str(exc), critical=True)

    return checks


def checks_ok(checks: list[dict[str, Any]]) -> bool:
    return all(not item["critical"] or item["ok"] for item in checks)


def run_doctor(app: App, *, json_output: bool = False) -> int:
    checks = collect_checks(app)
    ok = checks_ok(checks)
    if json_output:
        print_json(
            {
                "ok": ok,
                "device": app.config.device,
                "remote": app.config.remote,
                "b_path": str(app.b_path) if app.b_path else None,
                "checks": checks,
            }
        )
    else:
        print(f"rbackup doctor  device={app.config.device}  remote={app.config.remote}")
        for check in checks:
            marker = "OK" if check["ok"] else ("FAIL" if check["critical"] else "WARN")
            print(f"  [{marker:4}] {check['name']}: {check['detail']}")
        print("\n结论：", "关键检查通过" if ok else "有关键检查失败")
    return 0 if ok else 1
