from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from .config import Category
from .layout import Layout
from .rclone import MISSING_REMOTE_CODES, Rclone, RcloneError
from .util import human_size, mtime_close, safe_text


@dataclass(frozen=True)
class RemoteFile:
    category: str
    path: str
    size: int
    mtime: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
        }


@dataclass(frozen=True)
class Change:
    kind: str  # added / modified / deleted
    category: str
    path: str
    old_size: int | None = None
    new_size: int | None = None
    old_mtime: str | None = None
    new_mtime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "category": self.category,
            "path": self.path,
            "old_size": self.old_size,
            "new_size": self.new_size,
            "old_mtime": self.old_mtime,
            "new_mtime": self.new_mtime,
        }


@dataclass
class Snapshot:
    categories: dict[str, dict[str, RemoteFile]]

    @classmethod
    def empty(cls, categories: Iterable[str] = ()) -> "Snapshot":
        return cls({name: {} for name in categories})

    def ensure(self, categories: Iterable[str]) -> "Snapshot":
        for name in categories:
            self.categories.setdefault(name, {})
        return self

    def all_files(self) -> Iterable[RemoteFile]:
        for files in self.categories.values():
            yield from files.values()

    def category_digest(self, category: str) -> str:
        digest = hashlib.sha256()
        files = self.categories.get(category, {})
        for path in sorted(files):
            item = files[path]
            digest.update(category.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(item.size).encode("ascii"))
            digest.update(b"\0")
            digest.update(item.mtime.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def digest(self) -> str:
        digest = hashlib.sha256()
        for category in sorted(self.categories):
            digest.update(category.encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(self.category_digest(category)))
        return digest.hexdigest()

    def counts(self, category: str | None = None) -> dict[str, int]:
        if category is None:
            files = list(self.all_files())
        else:
            files = list(self.categories.get(category, {}).values())
        return {
            "files": len(files),
            "bytes": sum(item.size for item in files),
        }

    def diff(self, other: "Snapshot") -> list[Change]:
        changes: list[Change] = []
        categories = sorted(set(self.categories) | set(other.categories))
        for category in categories:
            old_files = self.categories.get(category, {})
            new_files = other.categories.get(category, {})
            for path in sorted(set(old_files) | set(new_files)):
                old = old_files.get(path)
                new = new_files.get(path)
                if old is None and new is not None:
                    changes.append(
                        Change(
                            "added",
                            category,
                            path,
                            new_size=new.size,
                            new_mtime=new.mtime,
                        )
                    )
                elif old is not None and new is None:
                    changes.append(
                        Change(
                            "deleted",
                            category,
                            path,
                            old_size=old.size,
                            old_mtime=old.mtime,
                        )
                    )
                elif old is not None and new is not None:
                    if old.size != new.size or old.mtime != new.mtime:
                        changes.append(
                            Change(
                                "modified",
                                category,
                                path,
                                old_size=old.size,
                                new_size=new.size,
                                old_mtime=old.mtime,
                                new_mtime=new.mtime,
                            )
                        )
        changes.sort(key=lambda item: (item.category, item.path, item.kind))
        return changes

    def summary(self) -> dict[str, Any]:
        return {
            "files": self.counts()["files"],
            "bytes": self.counts()["bytes"],
            "categories": {
                name: self.counts(name) for name in sorted(self.categories)
            },
            "digest": self.digest(),
        }


def _row_file(category: str, row: dict[str, Any]) -> RemoteFile:
    path = str(row.get("Path", "")).lstrip("/")
    raw_size = row.get("Size", 0)
    try:
        size = int(raw_size)
    except (TypeError, ValueError):
        size = 0
    return RemoteFile(
        category=category,
        path=path,
        size=max(0, size),
        mtime=str(row.get("ModTime", "") or ""),
    )


def load_snapshot(rclone: Rclone, layout: Layout, *, timeout: float | None = 300) -> Snapshot:
    """一次递归列出本设备前缀，再按第一层目录归类。

    _state 和 _versions 是设备前缀的同级目录，不会混进来。
    """
    try:
        rows = rclone.list_files(layout.device_root, timeout=timeout)
    except RcloneError as exc:
        if exc.returncode in MISSING_REMOTE_CODES:
            return Snapshot.empty()
        raise
    snapshot = Snapshot.empty()
    for row in rows:
        if row.get("IsDir"):
            continue
        path = str(row.get("Path", "")).lstrip("/")
        if not path:
            continue
        category, separator, relative = path.partition("/")
        if not separator or not relative:
            category, relative = "", path
        snapshot.categories.setdefault(category, {})[relative] = _row_file(
            category, {**row, "Path": relative}
        )
    return snapshot


def load_local_files(
    rclone: Rclone,
    category: Category,
    *,
    timeout: float | None = 300,
) -> dict[str, RemoteFile] | None:
    """用 rclone 读取本地目录，确保过滤规则与备份时完全一致。"""
    if not category.path.exists() or not category.path.is_dir():
        return None
    rows = rclone.list_files(str(category.path), filters=category.excludes, timeout=timeout)
    result: dict[str, RemoteFile] = {}
    for row in rows:
        if row.get("IsDir"):
            continue
        path = str(row.get("Path", "")).lstrip("/")
        if not path:
            continue
        result[path] = _row_file(category.name, {**row, "Path": path})
    return result


def compare_local_remote(
    local: dict[str, RemoteFile] | None,
    remote: dict[str, RemoteFile],
    *,
    tolerance: float = 3.0,
) -> dict[str, Any]:
    """只读比较本地与远端当前树；不下载、不写状态。"""
    if local is None:
        return {
            "local_missing": True,
            "remote_only": sorted(remote),
            "local_only": [],
            "modified": [],
            "same": 0,
        }
    remote_only = sorted(set(remote) - set(local))
    local_only = sorted(set(local) - set(remote))
    modified: list[dict[str, Any]] = []
    same = 0
    for path in sorted(set(local) & set(remote)):
        left = local[path]
        right = remote[path]
        reasons: list[str] = []
        if left.size != right.size:
            reasons.append("size")
        if not mtime_close(left.mtime, right.mtime, tolerance=tolerance):
            reasons.append("mtime")
        if reasons:
            modified.append(
                {
                    "path": path,
                    "reasons": reasons,
                    "local_size": left.size,
                    "remote_size": right.size,
                    "local_mtime": left.mtime,
                    "remote_mtime": right.mtime,
                }
            )
        else:
            same += 1
    return {
        "local_missing": False,
        "remote_only": remote_only,
        "local_only": local_only,
        "modified": modified,
        "same": same,
    }


def change_counts(changes: Iterable[Change]) -> dict[str, int]:
    counts = {"added": 0, "modified": 0, "deleted": 0}
    for change in changes:
        counts[change.kind] = counts.get(change.kind, 0) + 1
    return counts


def describe_change(change: Change) -> str:
    markers = {"added": "+", "modified": "~", "deleted": "-"}
    marker = markers.get(change.kind, "?")
    size = change.new_size if change.new_size is not None else change.old_size
    return (
        f"  {marker} [{change.category}] {safe_text(change.path)} "
        f"({human_size(size) if size is not None else '-'})"
    )
