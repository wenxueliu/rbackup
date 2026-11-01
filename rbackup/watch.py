from __future__ import annotations

import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .app import App, select_categories
from .backup import run_backup
from .errors import RbackupError
from .listing import (
    Change,
    Snapshot,
    change_counts,
    describe_change,
    load_snapshot,
)
from .state import StateError
from .util import human_size, iso_now, print_json


def _filter_snapshot(snapshot: Snapshot, names: dict[str, Any]) -> Snapshot:
    return Snapshot({name: snapshot.categories.get(name, {}) for name in names})


def _drift_categories(app: App, current: Snapshot, names: dict[str, Any]) -> dict[str, Any]:
    try:
        state = app.state.load()
    except StateError as exc:
        print(f"警告：无法读取状态文件，跳过漂移基线比较：{exc}", file=sys.stderr)
        return {}
    if state is None:
        return {}
    result: dict[str, Any] = {}
    for name in names:
        old = state.category_digest(name)
        if old is None:
            continue
        new = current.category_digest(name)
        if old != new:
            files = current.categories.get(name, {})
            result[name] = {
                "files": len(files),
                "bytes": sum(item.size for item in files.values()),
                "old_digest": old,
                "new_digest": new,
            }
    return result


def _emit_baseline(
    app: App,
    snapshot: Snapshot,
    names: dict[str, Any],
    *,
    interval: float,
    json_output: bool,
) -> None:
    counts = {
        name: {
            "files": len(snapshot.categories.get(name, {})),
            "bytes": sum(item.size for item in snapshot.categories.get(name, {}).values()),
        }
        for name in names
    }
    total = {
        "files": sum(item["files"] for item in counts.values()),
        "bytes": sum(item["bytes"] for item in counts.values()),
    }
    if json_output:
        print_json(
            {
                "event": "baseline",
                "detected_at": iso_now(),
                "device": app.layout.device,
                "remote": app.layout.remote,
                "b_path": str(app.b_path) if app.b_path else None,
                "interval": interval,
                "categories": counts,
                **total,
            }
        )
    else:
        print(
            f"监听 {app.layout.remote}:{app.layout.device} 的 "
            f"{len(names)} 个类别；基线 {total['files']} 个文件 / "
            f"{human_size(total['bytes'])}；轮询间隔 {interval:g}s。",
            file=sys.stderr,
        )
        if app.b_path:
            print(f"B 本地同步目录：{app.b_path}", file=sys.stderr)
        print("按 Ctrl+C 停止。检测到变化只报告，不会自动改动本地或远端。", file=sys.stderr)


def _emit_drift(app: App, drifts: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print_json(
            {
                "event": "drift",
                "detected_at": iso_now(),
                "device": app.layout.device,
                "categories": drifts,
                "message": "远端与 _state 中记录的基线不同；请用 status/diff 查看详情，再决定是否 restore 或 backup --force。",
            }
        )
    else:
        print("远端与上次备份记录的基线不同：", file=sys.stderr)
        for name, info in sorted(drifts.items()):
            print(
                f"  [{name}] {info['files']} 个文件 / {human_size(info['bytes'])}",
                file=sys.stderr,
            )
        print(
            "  可用 `rbackup status` 或 `rbackup diff` 查看；"
            "本进程只报告，不自动处理。",
            file=sys.stderr,
        )


def _emit_batch(
    changes: list[Change],
    *,
    json_output: bool,
    max_events: int,
) -> None:
    counts = change_counts(changes)
    if json_output:
        print_json(
            {
                "event": "batch",
                "detected_at": iso_now(),
                "added": counts["added"],
                "modified": counts["modified"],
                "deleted": counts["deleted"],
                "changes": [change.to_dict() for change in changes],
            }
        )
        return
    print(
        f"\n检测到远端变化：新增 {counts['added']}，修改 {counts['modified']}，"
        f"删除 {counts['deleted']}",
        file=sys.stderr,
    )
    for change in changes[:max_events]:
        print(describe_change(change), file=sys.stderr)
    remaining = len(changes) - max_events
    if remaining > 0:
        print(f"  … 还有 {remaining} 项（用 --json 获取全部）", file=sys.stderr)


def _restore_changes(
    app: App,
    changes: list[Change],
    *,
    restore_dir: Path,
) -> int:
    restore_dir = restore_dir.expanduser().resolve(strict=False)
    restored = 0
    for change in changes:
        if change.kind == "deleted":
            continue
        source = app.layout.category_file(change.category, change.path)
        destination = restore_dir / change.category / Path(*PurePosixPath(change.path).parts)
        try:
            destination.resolve(strict=False).relative_to(restore_dir)
        except ValueError:
            print(f"跳过越界路径：{change.path}", file=sys.stderr)
            continue
        if destination.exists():
            print(f"已存在，跳过（不覆盖）：{destination}", file=sys.stderr)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"恢复 {change.category}/{change.path} -> {destination}", file=sys.stderr)
        app.rclone.copyto(source, str(destination))
        restored += 1
    if any(change.kind == "deleted" for change in changes):
        print(
            "删除项无法从当前版本恢复；请用 `rbackup versions` 找到历史版本后 restore --version。",
            file=sys.stderr,
        )
    return restored


def _interactive(
    app: App,
    changes: list[Change],
    *,
    restore_dir: Path,
) -> str:
    if not sys.stdin or not sys.stdin.isatty():
        print(
            "非交互终端：只报告变化。需要处理请运行 restore / backup --force。",
            file=sys.stderr,
        )
        return "ignore"
    categories = sorted({change.category for change in changes})
    print(
        "\n处理本次变化？\n"
        f"  [r] 恢复到 {restore_dir}（不覆盖已存在文件）\n"
        "  [u] 用本地文件覆盖远端（旧内容进入 _versions）\n"
        "  [i] 忽略本次（继续监听）\n"
        "  [q] 退出",
        file=sys.stderr,
    )
    try:
        answer = input("选择 [r/u/i/q]（默认 i）：").strip().lower()
    except EOFError:
        return "ignore"
    if answer == "q":
        return "quit"
    if answer == "r":
        _restore_changes(app, changes, restore_dir=restore_dir)
        return "restore"
    if answer == "u":
        result = run_backup(app, categories, force=True, json_output=False)
        print(f"覆盖结果：{result['status']}", file=sys.stderr)
        return "push"
    return "ignore"


def run_watch(
    app: App,
    names: list[str] | tuple[str, ...] | None,
    *,
    interval: float | None = None,
    once: bool = False,
    exit_on_change: bool = False,
    interactive: bool = False,
    restore_dir: Path | None = None,
    json_output: bool = False,
    max_events: int = 50,
) -> int:
    selected = select_categories(app, names)
    poll_interval = float(interval if interval is not None else app.config.poll_interval)
    if poll_interval < 1:
        raise RbackupError("轮询间隔至少为 1 秒")
    if interactive and json_output:
        raise RbackupError("--interactive 与 --json 不能同时使用")

    snapshot = load_snapshot(app.rclone, app.layout)
    snapshot = _filter_snapshot(snapshot, selected)
    _emit_baseline(
        app,
        snapshot,
        selected,
        interval=poll_interval,
        json_output=json_output,
    )
    drifts = _drift_categories(app, snapshot, selected)
    if drifts:
        _emit_drift(app, drifts, json_output=json_output)
    if once:
        return 0

    restore_root = restore_dir or (Path.cwd() / "rbackup-restore")
    previous = snapshot
    failures = 0
    while True:
        try:
            time.sleep(poll_interval)
            current = _filter_snapshot(load_snapshot(app.rclone, app.layout), selected)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failures += 1
            message = f"远端轮询失败：{exc}"
            print(message, file=sys.stderr)
            if json_output:
                print_json(
                    {
                        "event": "error",
                        "detected_at": iso_now(),
                        "message": str(exc),
                        "consecutive_failures": failures,
                    }
                )
            delay = min(poll_interval * (2 ** min(failures, 4)), 300.0)
            try:
                time.sleep(delay)
            except KeyboardInterrupt:
                raise
            continue

        failures = 0
        changes = previous.diff(current)
        previous = current
        if not changes:
            continue
        _emit_batch(changes, json_output=json_output, max_events=max_events)
        action = "ignore"
        if interactive:
            try:
                action = _interactive(app, changes, restore_dir=restore_root)
            except Exception as exc:
                print(f"处理失败，继续监听：{exc}", file=sys.stderr)
                action = "ignore"
        if action == "quit":
            return 0
        if action in {"restore", "push"}:
            previous = _filter_snapshot(load_snapshot(app.rclone, app.layout), selected)
        if exit_on_change:
            return 0
