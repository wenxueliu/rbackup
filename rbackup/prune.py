from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from .app import App
from .errors import UsageError
from .rclone import RcloneError
from .util import ProcessLock, human_size, print_json
from .versions import collect_versions, list_version_dirs, version_timestamp


def _lock_key(app: App) -> str:
    return f"{app.config.remote}|{app.layout.device}"


def run_prune(
    app: App,
    *,
    keep: int | None = None,
    older_than_days: int | None = None,
    yes: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
) -> int:
    if keep is not None and older_than_days is not None:
        raise UsageError("--keep 与 --older-than 不能同时使用")
    if older_than_days is not None and older_than_days < 1:
        raise UsageError("--older-than 至少为 1 天")
    if keep is None and older_than_days is None:
        keep = app.config.keep_versions
    if keep is not None and keep < 1:
        raise UsageError("--keep 至少为 1")

    with ProcessLock(_lock_key(app)):
        version_ids = list_version_dirs(app)
        stats = {item.version_id: item for item in collect_versions(app)}
        if older_than_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
            selected = [
                version_id
                for version_id in version_ids
                if (stamp := version_timestamp(version_id)) is not None and stamp < cutoff
            ]
        else:
            assert keep is not None
            selected = version_ids[keep:]

        planned = [
            {
                "version_id": version_id,
                "files": stats[version_id].files if version_id in stats else 0,
                "bytes": stats[version_id].bytes if version_id in stats else 0,
            }
            for version_id in selected
        ]
        planned_bytes = sum(item["bytes"] for item in planned)

        if not selected:
            if json_output:
                print_json(
                    {
                        "ok": True,
                        "dry_run": dry_run,
                        "planned": [],
                        "deleted": [],
                        "freed_bytes": 0,
                    }
                )
            else:
                print("没有需要清理的版本。")
            return 0

        if not yes and not dry_run:
            if json_output:
                print_json(
                    {
                        "ok": True,
                        "dry_run": True,
                        "planned": planned,
                        "deleted": [],
                        "freed_bytes": 0,
                        "message": "未删除；加 --yes 执行",
                    }
                )
            else:
                print("将删除以下历史版本（当前数据不受影响）：")
                for item in planned:
                    print(
                        f"  {item['version_id']}  {item['files']} 文件 / "
                        f"{human_size(item['bytes'])}"
                    )
                print(
                    f"共 {len(planned)} 个版本，约 {human_size(planned_bytes)}。"
                    "未执行删除；确认后加 --yes。"
                )
            return 0

        deleted: list[str] = []
        errors: list[str] = []
        for item in planned:
            version_id = item["version_id"]
            print(
                f"[{'dry-run' if dry_run else 'purge'}] {version_id}",
                file=sys.stderr,
            )
            try:
                app.rclone.purge(app.layout.version_root(version_id), dry_run=dry_run)
                deleted.append(version_id)
            except RcloneError as exc:
                errors.append(f"{version_id}: {exc}")

        summary: dict[str, Any] = {
            "ok": not errors,
            "dry_run": dry_run,
            "planned": planned,
            "deleted": deleted,
            "freed_bytes": planned_bytes,
            "errors": errors,
        }
        if json_output:
            print_json(summary)
        else:
            print(
                f"清理完成：{len(deleted)}/{len(planned)} 个版本，"
                f"释放约 {human_size(planned_bytes)}"
                + ("（dry-run，未实际删除）" if dry_run else "")
            )
            for error in errors:
                print(f"  失败：{error}")
        return 0 if not errors else 1
