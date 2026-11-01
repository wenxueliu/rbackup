"""写操作的审计日志。

每次删除、恢复、上传、重设基线、保存配置都追加一行 JSON，便于事后定位
“谁在什么时候动了哪些文件”。日志是纯文本 JSONL，可以直接 ``tail`` /
``grep`` / ``jq``，不依赖数据库。

文件位置：与配置文件同目录的 ``<配置文件名>.audit.log``。写日志失败不会影响
主操作（只在 stderr 记一条警告）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .util import iso_now

log = logging.getLogger(__name__)

# 单个事件里最多记多少个路径，避免一次删几千个文件把日志撑爆
MAX_ITEMS = 100

_KNOWN_OPS = {
    "config.save",
    "config.restore",
    "backup",
    "upload",
    "delete",
    "delete-local",
    "restore",
    "rebaseline",
}


def audit_path(config_path: Path) -> Path:
    path = Path(config_path).expanduser()
    return path.with_name(path.name + ".audit.log")


def record(
    config_path: Path,
    op: str,
    *,
    items: Iterable[str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """追加一条审计记录，返回实际写入的字典（便于测试）。"""
    entry: dict[str, Any] = {"ts": iso_now(), "op": op}
    if items is not None:
        listed = [str(item) for item in items]
        entry["items"] = listed[:MAX_ITEMS]
        entry["count"] = len(listed)
        if len(listed) > MAX_ITEMS:
            entry["items_truncated"] = True
    for key, value in fields.items():
        if value is not None:
            entry[key] = value

    path = audit_path(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("写审计日志失败（%s）：%s", path, exc)
    return entry


def read_entries(config_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    """读取最近的审计记录（最新的在最后）。坏行会被跳过。"""
    path = audit_path(config_path)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    entries.append(parsed)
    except OSError as exc:
        log.warning("读取审计日志失败（%s）：%s", path, exc)
        return []
    if limit > 0:
        return entries[-limit:]
    return entries
