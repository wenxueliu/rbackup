from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .app import App
from .errors import UsageError
from .layout import validate_version_id
from .rclone import MISSING_REMOTE_CODES, RcloneError
from .util import human_size, print_json, version_sort_key


@dataclass
class VersionStats:
    version_id: str
    categories: dict[str, dict[str, int]] = field(default_factory=dict)
    files: int = 0
    bytes: int = 0

    @property
    def timestamp(self) -> datetime | None:
        return version_timestamp(self.version_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z")
            if self.timestamp
            else None,
            "files": self.files,
            "bytes": self.bytes,
            "categories": self.categories,
        }


def version_timestamp(version_id: str) -> datetime | None:
    try:
        return datetime.strptime(version_id[:16], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def list_version_dirs(app: App) -> list[str]:
    try:
        rows = app.rclone.list_dirs(app.layout.versions_root)
    except RcloneError as exc:
        if exc.returncode in MISSING_REMOTE_CODES:
            return []
        raise
    versions: list[str] = []
    for row in rows:
        if not row.get("IsDir"):
            continue
        name = str(row.get("Path", "")).strip("/").split("/")[0]
        if not name:
            continue
        try:
            validate_version_id(name)
        except UsageError:
            continue
        versions.append(name)
    return sorted(set(versions), key=lambda value: (version_sort_key(value), value), reverse=True)


def collect_versions(
    app: App, *, category: str | None = None
) -> list[VersionStats]:
    version_ids = list_version_dirs(app)
    if not version_ids:
        return []
    try:
        rows = app.rclone.list_files(app.layout.versions_root)
    except RcloneError as exc:
        if exc.returncode in MISSING_REMOTE_CODES:
            return []
        raise
    by_version: dict[str, VersionStats] = {
        version_id: VersionStats(version_id) for version_id in version_ids
    }
    for row in rows:
        if row.get("IsDir"):
            continue
        path = str(row.get("Path", "")).strip("/")
        parts = path.split("/")
        if len(parts) < 3:
            continue
        version_id, cat = parts[0], parts[1]
        if version_id not in by_version:
            continue
        if category is not None and cat != category:
            continue
        try:
            size = int(row.get("Size", 0))
        except (TypeError, ValueError):
            size = 0
        stats = by_version[version_id]
        bucket = stats.categories.setdefault(cat, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += max(0, size)
        stats.files += 1
        stats.bytes += max(0, size)
    return [by_version[version_id] for version_id in version_ids if by_version[version_id].files > 0]


def run_versions(
    app: App,
    category: str | None,
    *,
    json_output: bool = False,
) -> int:
    if category is not None:
        app.config.category(category)
    versions = collect_versions(app, category=category)
    if json_output:
        print_json(
            {
                "device": app.layout.device,
                "category": category,
                "versions": [item.to_dict() for item in versions],
            }
        )
        return 0
    if not versions:
        print("没有找到历史版本。")
        return 0
    print(f"设备 {app.layout.device} 的历史版本（新 → 旧）：")
    for item in versions:
        categories = ", ".join(
            f"{name}: {stats['files']} 文件 / {human_size(stats['bytes'])}"
            for name, stats in sorted(item.categories.items())
        )
        stamp = item.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if item.timestamp else "?"
        print(f"  {item.version_id}  {stamp}  {categories}")
    return 0
