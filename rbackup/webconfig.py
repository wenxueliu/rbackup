from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import Config, load_config
from .errors import ConfigError

_STRING_FIELDS = (
    "device",
    "remote",
    "rclone_bin",
    "rclone_config",
    "bwlimit",
    "state_prefix",
    "versions_prefix",
)
_INT_FIELDS = {
    "transfers": (1, 64),
    "checkers": (1, 64),
    "retries": (0, 20),
    "keep_versions": (1, 100000),
}
_BOOL_FIELDS = ("follow_symlinks", "create_empty_dirs")


def _default_device() -> str:
    host = socket.gethostname().strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", host).strip("-._")
    return cleaned[:64] or "device"


def default_payload() -> dict[str, Any]:
    return {
        "device": _default_device(),
        "remote": "b_crypt",
        "rclone_bin": "rclone",
        "rclone_config": "",
        "poll_interval": 5.0,
        "transfers": 4,
        "checkers": 8,
        "retries": 3,
        "bwlimit": "",
        "state_prefix": "_state",
        "versions_prefix": "_versions",
        "follow_symlinks": False,
        "create_empty_dirs": True,
        "keep_versions": 30,
        "categories": [
            {
                "name": "documents",
                "path": "~/Documents",
                "excludes": ["**/.git/**", "**/node_modules/**"],
                "enabled": True,
            }
        ],
    }


def config_to_payload(config: Config) -> dict[str, Any]:
    return {
        "device": config.device,
        "remote": config.remote,
        "rclone_bin": config.rclone_bin,
        "rclone_config": config.rclone_config.as_posix() if config.rclone_config else "",
        "poll_interval": config.poll_interval,
        "transfers": config.transfers,
        "checkers": config.checkers,
        "retries": config.retries,
        "bwlimit": config.bwlimit or "",
        "state_prefix": config.state_prefix,
        "versions_prefix": config.versions_prefix,
        "follow_symlinks": config.follow_symlinks,
        "create_empty_dirs": config.create_empty_dirs,
        "keep_versions": config.keep_versions,
        "categories": [
            {
                "name": name,
                "path": category.path.as_posix(),
                "excludes": list(category.excludes),
                "enabled": category.enabled,
            }
            for name, category in config.categories.items()
        ],
    }


def _str(value: Any, field: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(f"{field} 必须是字符串")
    return value


def _int(value: Any, field: str, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ConfigError(f"{field} 必须是整数")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{field} 必须是整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} 必须是整数") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{field} 必须在 {minimum}..{maximum} 之间")
    return parsed


def _float(value: Any, field: str, default: float) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ConfigError(f"{field} 必须是数字")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} 必须是数字") from exc


def _bool(value: Any, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{field} 必须是 true 或 false")
    return value


def normalize_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("配置内容必须是 JSON 对象")
    defaults = default_payload()
    payload: dict[str, Any] = {}
    for field in _STRING_FIELDS:
        payload[field] = _str(raw.get(field), field, defaults[field])
    payload["poll_interval"] = _float(
        raw.get("poll_interval"), "poll_interval", defaults["poll_interval"]
    )
    if not 1 <= payload["poll_interval"] <= 86400:
        raise ConfigError("poll_interval 必须在 1..86400 秒之间")
    for field, (minimum, maximum) in _INT_FIELDS.items():
        payload[field] = _int(
            raw.get(field), field, defaults[field], minimum, maximum
        )
    for field in _BOOL_FIELDS:
        payload[field] = _bool(raw.get(field), field, defaults[field])

    raw_categories = raw.get("categories")
    if raw_categories is None:
        raw_categories = defaults["categories"]
    if not isinstance(raw_categories, list) or not raw_categories:
        raise ConfigError("至少需要一个类别")
    categories: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_categories, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"第 {index} 个类别必须是对象")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"第 {index} 个类别缺少 name")
        path = entry.get("path")
        if not isinstance(path, str):
            raise ConfigError(f"类别 {name!r} 的 path 必须是字符串")
        raw_excludes = entry.get("excludes", [])
        if isinstance(raw_excludes, str):
            raw_excludes = [
                line.strip() for line in raw_excludes.splitlines() if line.strip()
            ]
        if not isinstance(raw_excludes, list) or not all(
            isinstance(item, str) for item in raw_excludes
        ):
            raise ConfigError(f"类别 {name!r} 的 excludes 必须是字符串数组")
        categories.append(
            {
                "name": name,
                "path": path,
                "excludes": raw_excludes,
                "enabled": _bool(entry.get("enabled"), "enabled", True),
            }
        )
    payload["categories"] = categories
    return payload


def payload_to_toml(payload: dict[str, Any]) -> str:
    normalized = normalize_payload(payload)
    lines = [
        "# rbackup 配置",
        "# 由 rbackup web 配置页生成；保存时旧文件会备份为 .bak。",
        "",
    ]
    for field in (
        "device",
        "remote",
        "rclone_bin",
        "rclone_config",
        "poll_interval",
        "transfers",
        "checkers",
        "retries",
        "bwlimit",
        "state_prefix",
        "versions_prefix",
        "follow_symlinks",
        "create_empty_dirs",
        "keep_versions",
    ):
        value = normalized[field]
        if field == "poll_interval" and isinstance(value, float) and value.is_integer():
            rendered = str(int(value))
        else:
            rendered = json.dumps(value, ensure_ascii=False)
        lines.append(f"{field} = {rendered}")
    lines.append("")
    for category in normalized["categories"]:
        table = "categories." + json.dumps(category["name"], ensure_ascii=False)
        lines.append(f"[{table}]")
        lines.append(
            f"path = {json.dumps(category['path'], ensure_ascii=False)}"
        )
        lines.append(
            "excludes = "
            + json.dumps(category["excludes"], ensure_ascii=False)
        )
        lines.append(f"enabled = {'true' if category['enabled'] else 'false'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@contextmanager
def _temp_config(
    payload: dict[str, Any], config_path: Path
) -> Iterator[tuple[Config, Path]]:
    text = payload_to_toml(payload)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=".rbackup-web-", suffix=".toml", dir=config_path.parent
    )
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        config = load_config(str(temp_path))
        yield config, temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def validate_payload(payload: dict[str, Any], config_path: Path) -> Config:
    with _temp_config(payload, config_path) as (config, _temp):
        return config


def save_payload(
    payload: dict[str, Any], config_path: Path
) -> tuple[Config, Path | None]:
    """先写临时文件并用正式加载器校验，再原子替换；旧配置备份为 .bak。"""
    config_path = config_path.expanduser().resolve(strict=False)
    with _temp_config(payload, config_path) as (_config, temp_path):
        backup: Path | None = None
        if config_path.exists():
            backup = config_path.with_name(config_path.name + ".bak")
            try:
                shutil.copy2(config_path, backup)
            except OSError as exc:
                raise ConfigError(f"备份旧配置失败：{backup}：{exc}") from exc
        try:
            os.replace(temp_path, config_path)
        except OSError as exc:
            raise ConfigError(f"保存配置失败：{config_path}：{exc}") from exc
    return load_config(str(config_path)), backup


def read_payload(config_path: Path) -> tuple[dict[str, Any], bool, str | None]:
    """返回 (payload, exists, load_error)。无效配置回退到默认值以便页面修复。"""
    path = config_path.expanduser().resolve(strict=False)
    if not path.exists():
        return default_payload(), False, None
    try:
        return config_to_payload(load_config(str(path))), True, None
    except ConfigError as exc:
        return default_payload(), True, str(exc)
