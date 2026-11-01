from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import RbackupError
from .layout import Layout
from .rclone import MISSING_REMOTE_CODES, Rclone, RcloneError
from .util import iso_now, json_bytes


SCHEMA_VERSION = 1


class StateError(RbackupError):
    pass


@dataclass
class State:
    device: str
    remote: str
    run_id: str
    version_id: str
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str | None = None
    hostname: str = ""
    rclone_version: str = ""
    schema: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "device": self.device,
            "remote": self.remote,
            "run_id": self.run_id,
            "version_id": self.version_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "error": self.error,
            "hostname": self.hostname,
            "rclone": self.rclone_version,
            "categories": self.categories,
        }

    def to_bytes(self) -> bytes:
        return json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        schema = data.get("schema", 0)
        if type(schema) is not int or schema > SCHEMA_VERSION:
            raise StateError(
                f"状态文件版本 {schema!r} 高于本工具支持的 {SCHEMA_VERSION}，请升级 rbackup"
            )
        if schema < 1:
            raise StateError(f"状态文件版本无效：{schema!r}")
        required = ("device", "remote", "run_id", "version_id", "started_at")
        for key in required:
            if not isinstance(data.get(key), str):
                raise StateError(f"状态文件缺少字符串字段 {key!r}")
        categories = data.get("categories", {})
        if not isinstance(categories, dict):
            raise StateError("状态文件的 categories 必须是对象")
        for name, entry in categories.items():
            if not isinstance(entry, dict):
                raise StateError(f"状态文件类别 {name!r} 必须是对象")
            for field_name in ("files", "bytes"):
                value = entry.get(field_name)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int)
                ):
                    raise StateError(
                        f"状态文件类别 {name!r} 的 {field_name} 必须是整数"
                    )
            digest = entry.get("digest")
            if digest is not None and not isinstance(digest, str):
                raise StateError(f"状态文件类别 {name!r} 的 digest 必须是字符串")
        return cls(
            device=data["device"],
            remote=data["remote"],
            run_id=data["run_id"],
            version_id=data["version_id"],
            started_at=data["started_at"],
            finished_at=data.get("finished_at"),
            status=data.get("status", "unknown"),
            categories=categories,
            error=data.get("error"),
            hostname=data.get("hostname", ""),
            rclone_version=data.get("rclone", ""),
            schema=schema,
        )

    def category_digest(self, category: str) -> str | None:
        entry = self.categories.get(category) or {}
        digest = entry.get("digest")
        return digest if isinstance(digest, str) and digest else None

    def summary(self) -> dict[str, Any]:
        total_files = 0
        total_bytes = 0
        for entry in self.categories.values():
            files = entry.get("files", 0)
            size = entry.get("bytes", 0)
            if isinstance(files, int):
                total_files += files
            if isinstance(size, int):
                total_bytes += size
        return {
            "device": self.device,
            "version_id": self.version_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "files": total_files,
            "bytes": total_bytes,
            "categories": len(self.categories),
        }


class StateStore:
    def __init__(self, rclone: Rclone, layout: Layout) -> None:
        self.rclone = rclone
        self.layout = layout

    def load(self) -> State | None:
        try:
            raw = self.rclone.cat(self.layout.state_file)
        except RcloneError as exc:
            if exc.returncode in MISSING_REMOTE_CODES:
                return None
            raise StateError(
                f"无法读取远端状态文件 {self.layout.state_file}：{exc}"
            ) from exc
        try:
            data = json.loads(raw.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise StateError(
                f"远端状态文件不是合法 JSON：{self.layout.state_file}；"
                "为避免误覆盖，已停止。请检查/修复该文件，或确认后删除它再重新备份。"
            ) from exc
        if not isinstance(data, dict):
            raise StateError("远端状态文件顶层必须是对象")
        state = State.from_dict(data)
        if state.device != self.layout.device:
            raise StateError(
                f"状态文件的 device={state.device!r} 与配置的 {self.layout.device!r} 不一致"
            )
        if state.remote and state.remote != self.layout.remote:
            raise StateError(
                f"状态文件的 remote={state.remote!r} 与配置的 {self.layout.remote!r} 不一致"
            )
        return state

    def save(self, state: State) -> None:
        state.finished_at = state.finished_at or iso_now()
        self.rclone.rcat(self.layout.state_file, state.to_bytes())
