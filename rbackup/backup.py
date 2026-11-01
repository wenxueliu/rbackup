from __future__ import annotations

import copy
import socket
import sys
from typing import Any

from .app import App, select_categories
from .errors import RemoteDriftError
from .listing import load_local_files, load_snapshot
from .rclone import RcloneError
from .state import State, StateError
from .util import ProcessLock, confirm, human_size, iso_now, new_version_id, print_json
from .verify import verify_category


def _category_remote_info(snapshot: Any, category: str) -> dict[str, Any]:
    files = snapshot.categories.get(category, {})
    return {
        "files": len(files),
        "bytes": sum(item.size for item in files.values()),
    }


def _drift_message(drifts: dict[str, dict[str, Any]]) -> str:
    lines = ["远端数据自上次记录后发生了变化："]
    for name, info in sorted(drifts.items()):
        lines.append(
            f"  {name}: {info['files']} 个文件 / {human_size(info['bytes'])}"
        )
    lines.append(
        "继续会用本地同名文件覆盖远端（旧内容仍会进入 _versions），"
        "但 copy 不会删除远端多出的文件。"
    )
    lines.append(
        "请先运行 `rbackup status` / `rbackup diff` / `rbackup watch` 检查；"
        "确认要用本地覆盖后加 --force。"
    )
    return "\n".join(lines)


def _handle_drift(
    drifts: dict[str, dict[str, Any]],
    *,
    force: bool,
    dry_run: bool,
    json_output: bool,
) -> None:
    message = _drift_message(drifts)
    if force:
        print(
            "检测到远端变化；已指定 --force，用本地覆盖同名远端文件"
            "（旧内容进入 _versions，copy 不会删除远端多出的文件）。",
            file=sys.stderr,
        )
        return
    if dry_run:
        print("[dry-run] " + message.replace("\n", "\n[dry-run] "), file=sys.stderr)
        return
    print(message, file=sys.stderr)
    if (
        not json_output
        and sys.stdin is not None
        and sys.stdin.isatty()
        and confirm("是否用本地版本覆盖这些远端变化？", default=False)
    ):
        return
    raise RemoteDriftError(
        "远端数据相对状态基线已变化；本次未写入任何内容。"
        "请先检查（status/diff/watch），确认覆盖后加 --force。"
    )


def run_backup(
    app: App,
    names: list[str] | tuple[str, ...] | None,
    *,
    dry_run: bool = False,
    force: bool = False,
    verify: bool = False,
    json_output: bool = False,
) -> dict[str, Any]:
    selected = select_categories(app, names)
    lock_key = f"{app.config.remote}|{app.layout.device}"
    with ProcessLock(lock_key):
        return _run_backup_locked(
            app,
            selected,
            dry_run=dry_run,
            force=force,
            verify=verify,
            json_output=json_output,
        )


def _run_backup_locked(
    app: App,
    selected: dict[str, Any],
    *,
    dry_run: bool,
    force: bool,
    verify: bool,
    json_output: bool,
) -> dict[str, Any]:
    version_id = new_version_id()
    started_at = iso_now()
    if app.b_path is not None and not app.b_path.exists():
        print(
            f"警告：B 本地同步目录在运行中不可见：{app.b_path}；"
            "请检查挂载点或网盘同步客户端。",
            file=sys.stderr,
        )
    rclone_version = app.rclone.version()
    previous = app.state.load()
    if (
        previous is not None
        and previous.hostname
        and previous.hostname != socket.gethostname()
    ):
        print(
            f"警告：状态文件由主机 {previous.hostname!r} 写入，当前主机是 "
            f"{socket.gethostname()!r}；请确认 device 前缀没有被两台设备共用。",
            file=sys.stderr,
        )

    before = load_snapshot(app.rclone, app.layout)
    if previous is None:
        occupied: dict[str, dict[str, Any]] = {}
        for name in selected:
            info = _category_remote_info(before, name)
            if info["files"] > 0:
                occupied[name] = info
        if occupied:
            message = (
                "远端已有数据，但没有 `_state` 基线：\n"
                + "\n".join(
                    f"  {name}: {info['files']} 个文件 / {human_size(info['bytes'])}"
                    for name, info in sorted(occupied.items())
                )
                + "\n首次运行也可能只是状态文件丢失。"
                "继续会用本地覆盖同名远端文件（旧内容进入 _versions），"
                "copy 不会删除远端多出的文件。请先用 `rbackup diff` 检查。"
            )
            if dry_run:
                print("[dry-run] " + message.replace("\n", "\n[dry-run] "), file=sys.stderr)
            elif force:
                print(
                    "远端已有数据但没有状态基线；已指定 --force，继续用本地覆盖同名文件。",
                    file=sys.stderr,
                )
            else:
                print(message, file=sys.stderr)
                if (
                    not json_output
                    and sys.stdin is not None
                    and sys.stdin.isatty()
                    and confirm("是否继续用本地覆盖同名远端文件？", default=False)
                ):
                    pass
                else:
                    raise RemoteDriftError(
                        "远端已有数据但没有状态基线；本次未写入任何内容。"
                        "请先 diff 检查，确认覆盖后加 --force。"
                    )
    drifts: dict[str, dict[str, Any]] = {}
    for name in selected:
        if previous is None:
            break
        if not selected[name].path.exists() or not selected[name].path.is_dir():
            # 本地整个目录已消失：本次只会跳过，不会覆盖远端，无需强制。
            continue
        old_digest = previous.category_digest(name)
        if old_digest is None:
            continue
        new_digest = before.category_digest(name)
        if new_digest != old_digest:
            info = _category_remote_info(before, name)
            info["old_digest"] = old_digest
            info["new_digest"] = new_digest
            drifts[name] = info

    if drifts:
        _handle_drift(
            drifts,
            force=force,
            dry_run=dry_run,
            json_output=json_output,
        )

    state = State(
        device=app.layout.device,
        remote=app.layout.remote,
        run_id=version_id,
        version_id=version_id,
        started_at=started_at,
        status="running",
        categories=copy.deepcopy(previous.categories) if previous else {},
        hostname=socket.gethostname(),
        rclone_version=rclone_version,
    )

    failures = 0
    local_missing = 0
    verify_failures = 0
    errors: list[str] = []
    touched: list[str] = []

    for name, category in selected.items():
        if not category.path.exists() or not category.path.is_dir():
            local_missing += 1
            message = f"本地目录不存在或不是目录：{category.path}"
            errors.append(f"{name}: {message}")
            entry = dict(state.categories.get(name) or {})
            entry.update(
                {
                    "status": "local_missing",
                    "error": message,
                    "last_attempt_at": iso_now(),
                    "available": False,
                }
            )
            state.categories[name] = entry
            print(f"[{name}] 跳过：{message}", file=sys.stderr)
            continue

        backup_dir = app.layout.version_category(version_id, name)
        print(
            f"[{name}] copy {category.path} -> {app.layout.category_root(name)}"
            + ("（dry-run）" if dry_run else ""),
            file=sys.stderr,
        )
        try:
            app.rclone.copy(
                str(category.path),
                app.layout.category_root(name),
                backup_dir=backup_dir,
                dry_run=dry_run,
                filters=category.excludes,
                create_empty_dirs=app.config.create_empty_dirs,
            )
        except RcloneError as exc:
            failures += 1
            errors.append(f"{name}: {exc}")
            entry = dict(state.categories.get(name) or {})
            entry.update(
                {
                    "status": "failed",
                    "error": str(exc)[:3000],
                    "last_attempt_at": iso_now(),
                }
            )
            state.categories[name] = entry
            print(f"[{name}] 失败：{exc}", file=sys.stderr)
            continue

        touched.append(name)
        entry = {
            "status": "ok",
            "files": 0,
            "bytes": 0,
            "digest": None,
            "version_id": version_id,
            "updated_at": iso_now(),
            "verified": None,
        }
        state.categories[name] = entry
        print(
            f"[{name}] " + ("dry-run 完成" if dry_run else "上传完成"),
            file=sys.stderr,
        )

        if verify and not dry_run:
            try:
                check = verify_category(app, name, one_way=True)
            except Exception as exc:  # 校验失败不应抹掉已成功的上传
                check = {
                    "ok": False,
                    "returncode": None,
                    "unsupported": False,
                    "output": str(exc),
                }
            entry["verified"] = bool(check["ok"])
            if not check["ok"]:
                verify_failures += 1
                entry["status"] = "verify_failed"
                entry["verify_error"] = str(check.get("output", ""))[-3000:]
                errors.append(f"{name}: cryptcheck 未通过")
                print(
                    f"[{name}] cryptcheck 未通过\n{check.get('output', '')}",
                    file=sys.stderr,
                )

    after = None
    if touched and not dry_run:
        after = load_snapshot(app.rclone, app.layout)

    if after is not None:
        for name in touched:
            entry = state.categories.get(name)
            if not entry or entry.get("status") not in {"ok", "verify_failed"}:
                continue
            files = after.categories.get(name, {})
            entry["files"] = len(files)
            entry["bytes"] = sum(item.size for item in files.values())
            entry["digest"] = after.category_digest(name)

    if dry_run:
        # dry-run 没有远端结果，用本地文件数展示“将要备份”的规模。
        for name in touched:
            entry = state.categories.get(name)
            if not entry:
                continue
            local = load_local_files(app.rclone, selected[name])
            if local is not None:
                entry["files"] = len(local)
                entry["bytes"] = sum(item.size for item in local.values())

    if dry_run:
        status = "dry_run"
    elif failures or local_missing or verify_failures:
        status = "partial" if touched else "failed"
    else:
        status = "ok"
    state.status = status
    state.finished_at = iso_now()
    state.error = "; ".join(errors)[:6000] if errors else None

    if not dry_run:
        try:
            app.state.save(state)
        except RcloneError as exc:
            raise StateError(f"备份已执行，但写入远端状态失败：{exc}") from exc

    exit_code = 0
    if failures or local_missing:
        exit_code = 1
    if verify_failures and exit_code == 0:
        exit_code = 4

    summary = {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "dry_run": dry_run,
        "status": status,
        "version_id": version_id,
        "started_at": started_at,
        "finished_at": state.finished_at,
        "device": app.layout.device,
        "remote": app.layout.remote,
        "b_path": str(app.b_path) if app.b_path else None,
        "categories": {
            name: state.categories.get(name, {}) for name in selected
        },
        "remote_drift": sorted(drifts),
        "local_missing": local_missing,
        "failures": failures,
        "verify_failures": verify_failures,
    }

    if json_output:
        print_json(summary)
    else:
        total_files = sum(
            int((state.categories.get(name) or {}).get("files", 0) or 0)
            for name in selected
        )
        total_bytes = sum(
            int((state.categories.get(name) or {}).get("bytes", 0) or 0)
            for name in selected
        )
        print(
            f"\n备份{ '检查' if dry_run else '完成'}：{status}；"
            f"版本 {version_id}；{total_files} 个文件 / {human_size(total_bytes)}"
        )
        if errors:
            print("问题：", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        if exit_code == 4:
            print("提示：上传已完成，但 cryptcheck 未通过。", file=sys.stderr)
    return summary
