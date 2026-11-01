from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import UsageError
from .util import VERSION_ID_RE


_VERSION_RE = re.compile(VERSION_ID_RE)


def normalize_relpath(raw: str) -> str:
    """把用户输入的远端相对路径规范化为 rclone 的 '/' 形式。

    拒绝绝对路径、盘符和 '..'，防止 restore 把文件写到目标目录之外。
    空字符串表示类别根目录。
    """
    if raw is None:
        return ""
    value = raw
    if os.name == "nt":
        value = value.replace("\\", "/")
    if value in {"", ".", "/"}:
        return ""
    if value.startswith("/"):
        raise UsageError(f"远端路径必须是相对路径：{raw!r}")
    if re.match(r"^[A-Za-z]:", value):
        raise UsageError(f"远端路径不能带盘符：{raw!r}")
    parts: list[str] = []
    for part in value.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise UsageError(f"远端路径不能包含 '..'：{raw!r}")
        if "\x00" in part:
            raise UsageError("远端路径含 NUL 字符")
        parts.append(part)
    return "/".join(parts)


def validate_version_id(value: str) -> str:
    if not _VERSION_RE.fullmatch(value):
        raise UsageError(
            f"版本 ID 格式无效：{value!r}；应形如 20261030T235653Z-a1b2c3"
        )
    return value


@dataclass(frozen=True)
class Layout:
    remote: str
    device: str
    state_prefix: str = "_state"
    versions_prefix: str = "_versions"

    def path(self, *parts: str) -> str:
        cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
        suffix = "/".join(cleaned)
        return f"{self.remote}:{suffix}" if suffix else f"{self.remote}:"

    @property
    def device_root(self) -> str:
        return self.path(self.device)

    def category_root(self, category: str) -> str:
        return self.path(self.device, category)

    def category_file(self, category: str, relpath: str) -> str:
        relpath = normalize_relpath(relpath)
        return self.path(self.device, category, relpath) if relpath else self.category_root(
            category
        )

    @property
    def versions_root(self) -> str:
        return self.path(self.versions_prefix, self.device)

    def version_root(self, version_id: str) -> str:
        return self.path(self.versions_prefix, self.device, validate_version_id(version_id))

    def version_category(self, version_id: str, category: str) -> str:
        return self.path(
            self.versions_prefix, self.device, validate_version_id(version_id), category
        )

    def version_file(self, version_id: str, category: str, relpath: str) -> str:
        base = self.version_category(version_id, category)
        relpath = normalize_relpath(relpath)
        return f"{base}/{relpath}" if relpath else base

    @property
    def state_file(self) -> str:
        return self.path(self.state_prefix, self.device, "last-run.json")

    @property
    def state_root(self) -> str:
        return self.path(self.state_prefix, self.device)

    def relative_category_path(self, category: str, relpath: str = "") -> PurePosixPath:
        relpath = normalize_relpath(relpath)
        return PurePosixPath(category) / relpath if relpath else PurePosixPath(category)
