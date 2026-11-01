from __future__ import annotations

from typing import Any

from .app import App, select_categories
from .listing import load_snapshot
from .util import human_size, print_json


def _short_digest(value: str | None) -> str:
    return value[:12] + "…" if value else "-"


def run_status(
    app: App,
    names: list[str] | tuple[str, ...] | None,
    *,
    json_output: bool = False,
    check: bool = False,
    offline: bool = False,
) -> int:
    selected = select_categories(app, names)
    state = app.state.load()
    live = None if offline else load_snapshot(app.rclone, app.layout)

    categories: dict[str, Any] = {}
    drift_categories: list[str] = []
    for name, category in selected.items():
        entry = (state.categories.get(name) or {}) if state else {}
        old_digest = state.category_digest(name) if state else None
        if live is not None:
            files = live.categories.get(name, {})
            remote_info = {
                "files": len(files),
                "bytes": sum(item.size for item in files.values()),
                "digest": live.category_digest(name),
            }
            drift = old_digest is not None and old_digest != remote_info["digest"]
        else:
            remote_info = None
            drift = None
        if drift:
            drift_categories.append(name)
        categories[name] = {
            "local_exists": category.path.exists() and category.path.is_dir(),
            "local_path": str(category.path),
            "state": entry,
            "remote": remote_info,
            "drift": drift,
            "baseline_digest": old_digest,
        }

    result = {
        "device": app.layout.device,
        "remote": app.layout.remote,
        "b_path": str(app.b_path) if app.b_path else None,
        "state_file": app.layout.state_file,
        "state": state.summary() if state else None,
        "offline": offline,
        "categories": categories,
        "drift_categories": drift_categories,
        "exit_code": 3 if check and drift_categories else 0,
    }

    if json_output:
        print_json(result)
    else:
        print(f"设备: {app.layout.device}    远端: {app.layout.remote}")
        if app.b_path:
            print(f"B 本地同步目录: {app.b_path}")
        print(f"状态文件: {app.layout.state_file}")
        if state:
            summary = state.summary()
            print(
                f"最近运行: {summary['status']}  版本: {summary['version_id']}  "
                f"开始: {summary['started_at']}  结束: {summary['finished_at'] or '-'}"
            )
            if state.error:
                print(f"错误: {state.error}")
        else:
            print("尚未找到状态文件（还没有成功写入过备份状态）。")

        for name, info in categories.items():
            entry = info["state"]
            print(f"\n[{name}] {info['local_path']}")
            print(f"  本地: {'存在' if info['local_exists'] else '不存在（不影响远端备份）'}")
            if info["remote"] is not None:
                remote = info["remote"]
                print(
                    f"  云端: {remote['files']} 个文件 / {human_size(remote['bytes'])}  "
                    f"digest {_short_digest(remote['digest'])}"
                )
            else:
                print("  云端: 未查询（--offline）")
            if info["drift"] is None:
                if info["remote"] is None:
                    print("  基线: 未比较")
                else:
                    print("  基线: 尚未建立（首次备份后写入）")
            elif info["drift"]:
                print(
                    f"  基线: 漂移！状态记录 {_short_digest(info['baseline_digest'])}，"
                    f"云端现在 {_short_digest(info['remote']['digest'])}"
                )
            else:
                print("  基线: 一致")
            if entry:
                print(
                    f"  记录: {entry.get('status', '?')}  "
                    f"{entry.get('files', '-')} 文件 / "
                    f"{human_size(entry.get('bytes'))}  "
                    f"更新于 {entry.get('updated_at') or entry.get('last_attempt_at') or '-'}"
                )

        if drift_categories:
            print(
                f"\n检测到远端漂移：{', '.join(drift_categories)}\n"
                "用 `rbackup diff` 查看本地/远端差异，或用 `rbackup watch` 持续监听。"
            )
        elif not offline:
            has_baseline = any(
                info["baseline_digest"] for info in categories.values()
            )
            print(
                "\n远端与状态基线一致。"
                if has_baseline
                else "\n没有可比较的基线（首次备份后写入）。"
            )

    return result["exit_code"]
