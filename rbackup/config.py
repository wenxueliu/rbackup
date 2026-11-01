from __future__ import annotations

import json
import os
import re
import socket
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError


_TOP_LEVEL_KEYS = {
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
    "categories",
}
_CATEGORY_KEYS = {"path", "excludes", "enabled"}


def _type_name(value: Any) -> str:
    return type(value).__name__


def _string(
    table: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
    required: bool = False,
    where: str = "",
) -> str | None:
    if key not in table:
        if required:
            raise ConfigError(f"{where}缺少必填项 {key!r}")
        return default
    value = table[key]
    if not isinstance(value, str):
        raise ConfigError(f"{where}{key} 必须是字符串，实际为 {_type_name(value)}")
    return value


def _integer(
    table: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    where: str = "",
) -> int:
    if key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where}{key} 必须是整数")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{where}{key} 必须在 {minimum}..{maximum} 之间")
    return value


def _boolean(table: dict[str, Any], key: str, default: bool, *, where: str = "") -> bool:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{where}{key} 必须是 true 或 false")
    return value


def validate_segment(value: str, kind: str, *, max_length: int = 100) -> str:
    """校验会进入 rclone 远端路径的一段名称。

    允许中文和内部空格，但拒绝路径分隔符、控制字符、Windows 不友好结尾，
    避免设备名/类别名改变目录层级或产生不可移植路径。
    """
    if not value:
        raise ConfigError(f"{kind} 不能为空")
    if value != value.strip():
        raise ConfigError(f"{kind} 不能以空白开头或结尾：{value!r}")
    if value in {".", ".."}:
        raise ConfigError(f"{kind} 不能是 {value!r}")
    if len(value) > max_length:
        raise ConfigError(f"{kind} 太长（最多 {max_length} 个字符）")
    forbidden = set('/\\:*?"<>|')
    for char in value:
        if char in forbidden or ord(char) < 32 or ord(char) == 127:
            raise ConfigError(f"{kind} 含非法字符 {char!r}：{value!r}")
    if value.endswith("."):
        raise ConfigError(f"{kind} 不能以 '.' 结尾：{value!r}")
    return value


def _resolve_path(value: str, base_dir: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)


def _normalize_remote(value: str) -> str:
    remote = value.strip()
    if remote.endswith(":"):
        remote = remote[:-1]
    if not remote:
        raise ConfigError("remote 不能为空")
    if ":" in remote or "/" in remote or "\\" in remote:
        raise ConfigError(
            f"remote 只写 rclone 配置名（如 b_crypt），不要带冒号或路径：{value!r}"
        )
    return validate_segment(remote, "remote")


def _validate_prefix(value: str, key: str) -> str:
    prefix = value.strip().strip("/")
    if "/" in prefix or "\\" in prefix:
        raise ConfigError(f"{key} 只能是单层目录名：{value!r}")
    return validate_segment(prefix, key, max_length=64)


@dataclass(frozen=True)
class Category:
    name: str
    path: Path
    excludes: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    path: Path
    device: str
    remote: str
    categories: dict[str, Category]
    rclone_bin: str = "rclone"
    rclone_config: Path | None = None
    poll_interval: float = 15.0
    transfers: int = 4
    checkers: int = 8
    retries: int = 3
    bwlimit: str | None = None
    state_prefix: str = "_state"
    versions_prefix: str = "_versions"
    follow_symlinks: bool = False
    create_empty_dirs: bool = True
    keep_versions: int = 30

    def enabled_categories(self) -> dict[str, Category]:
        return {name: cat for name, cat in self.categories.items() if cat.enabled}

    def category(self, name: str) -> Category:
        try:
            category = self.categories[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.categories)) or "（无）"
            raise ConfigError(f"未知类别 {name!r}；已配置：{known}") from exc
        return category

    def public_dict(self) -> dict[str, Any]:
        return {
            "config": str(self.path),
            "device": self.device,
            "remote": self.remote,
            "rclone_bin": self.rclone_bin,
            "rclone_config": str(self.rclone_config) if self.rclone_config else None,
            "poll_interval": self.poll_interval,
            "transfers": self.transfers,
            "checkers": self.checkers,
            "retries": self.retries,
            "state_prefix": self.state_prefix,
            "versions_prefix": self.versions_prefix,
            "categories": {
                name: {
                    "path": str(cat.path),
                    "excludes": list(cat.excludes),
                    "enabled": cat.enabled,
                }
                for name, cat in self.categories.items()
            },
        }


def default_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "rbackup" / "config.toml"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "rbackup" / "config.toml"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "rbackup" / "config.toml"


def discover_config(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(os.path.expandvars(os.path.expanduser(explicit))).resolve(strict=False)
        if not path.exists():
            raise ConfigError(f"配置文件不存在：{path}")
        return path
    env_path = os.environ.get("RBACKUP_CONFIG")
    if env_path:
        path = Path(os.path.expandvars(os.path.expanduser(env_path))).resolve(strict=False)
        if not path.exists():
            raise ConfigError(f"RBACKUP_CONFIG 指向的文件不存在：{path}")
        return path
    local = (Path.cwd() / "rbackup.toml").resolve(strict=False)
    if local.exists():
        return local
    return default_config_path()


def _parse_category(name: str, table: Any, base_dir: Path) -> Category:
    where = f"categories.{name}."
    if not isinstance(table, dict):
        raise ConfigError(f"categories.{name} 必须是一个表（[categories.{name}]）")
    unknown = set(table) - _CATEGORY_KEYS
    if unknown:
        raise ConfigError(f"{where}存在未知配置项：{', '.join(sorted(unknown))}")
    validate_segment(name, "类别名", max_length=64)
    raw_path = _string(table, "path", required=True, where=where)
    assert raw_path is not None
    if not raw_path.strip():
        raise ConfigError(f"{where}path 不能为空")
    path = _resolve_path(raw_path, base_dir)
    raw_excludes = table.get("excludes", [])
    if not isinstance(raw_excludes, list) or not all(
        isinstance(item, str) for item in raw_excludes
    ):
        raise ConfigError(f"{where}excludes 必须是字符串数组")
    excludes: list[str] = []
    for pattern in raw_excludes:
        if not pattern:
            raise ConfigError(f"{where}excludes 不能包含空字符串")
        if "\x00" in pattern:
            raise ConfigError(f"{where}excludes 含 NUL 字符")
        excludes.append(pattern)
    enabled = _boolean(table, "enabled", True, where=where)
    return Category(name=name, path=path, excludes=tuple(excludes), enabled=enabled)


def load_config(explicit: str | None = None) -> Config:
    path = discover_config(explicit)
    try:
        raw = path.read_bytes()
        # Windows 记事本/部分编辑器会带 UTF-8 BOM；tomllib 不接受 BOM。
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        data = tomllib.loads(raw.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"配置文件不存在：{path}\n先运行 `rbackup init --config \"{path}\"` 生成模板。"
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"配置文件不是 UTF-8 编码：{path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 TOML 语法错误：{path}\n{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}：{exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是 TOML 表")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"配置文件存在未知配置项：{', '.join(sorted(unknown))}")

    device_raw = _string(data, "device", required=True)
    remote_raw = _string(data, "remote", required=True)
    assert device_raw is not None and remote_raw is not None
    device = validate_segment(device_raw.strip(), "device", max_length=64)
    remote = _normalize_remote(remote_raw)

    state_prefix = _validate_prefix(
        _string(data, "state_prefix", default="_state") or "_state", "state_prefix"
    )
    versions_prefix = _validate_prefix(
        _string(data, "versions_prefix", default="_versions") or "_versions",
        "versions_prefix",
    )
    if state_prefix == versions_prefix:
        raise ConfigError("state_prefix 与 versions_prefix 不能相同")
    if state_prefix == device or versions_prefix == device:
        raise ConfigError("state_prefix/versions_prefix 不能与 device 相同")
    if state_prefix == remote or versions_prefix == remote:
        raise ConfigError("state_prefix/versions_prefix 不能与 remote 同名，避免混淆")

    categories_table = data.get("categories")
    if not isinstance(categories_table, dict) or not categories_table:
        raise ConfigError("至少配置一个 [categories.<类别名>]")
    categories: dict[str, Category] = {}
    folded: dict[str, str] = {}
    for name, table in categories_table.items():
        category = _parse_category(name, table, path.parent)
        folded_name = name.casefold()
        if folded_name in folded:
            raise ConfigError(
                f"类别名大小写冲突：{folded[folded_name]!r} 与 {name!r}"
            )
        folded[folded_name] = name
        categories[name] = category

    poll_interval_raw = data.get("poll_interval", 15.0)
    if isinstance(poll_interval_raw, bool) or not isinstance(
        poll_interval_raw, (int, float)
    ):
        raise ConfigError("poll_interval 必须是数字（秒）")
    poll_interval = float(poll_interval_raw)
    if not 1.0 <= poll_interval <= 86400:
        raise ConfigError("poll_interval 必须在 1..86400 秒之间")

    rclone_bin = (_string(data, "rclone_bin", default="rclone") or "rclone").strip()
    if not rclone_bin:
        raise ConfigError("rclone_bin 不能为空")
    rclone_bin = os.path.expandvars(os.path.expanduser(rclone_bin))
    if (os.sep in rclone_bin or (os.altsep and os.altsep in rclone_bin)) and not Path(
        rclone_bin
    ).is_absolute():
        rclone_bin = str((path.parent / rclone_bin).resolve(strict=False))
    rclone_config_raw = (_string(data, "rclone_config", default="") or "").strip()
    rclone_config: Path | None = None
    if rclone_config_raw:
        rclone_config = _resolve_path(rclone_config_raw, path.parent)
        if not rclone_config.exists():
            raise ConfigError(f"rclone_config 指向的文件不存在：{rclone_config}")

    bwlimit = (_string(data, "bwlimit", default="") or "").strip() or None
    if bwlimit is not None and "\x00" in bwlimit:
        raise ConfigError("bwlimit 含 NUL 字符")

    return Config(
        path=path,
        device=device,
        remote=remote,
        categories=categories,
        rclone_bin=rclone_bin,
        rclone_config=rclone_config,
        poll_interval=poll_interval,
        transfers=_integer(data, "transfers", 4, minimum=1, maximum=64),
        checkers=_integer(data, "checkers", 8, minimum=1, maximum=64),
        retries=_integer(data, "retries", 3, minimum=0, maximum=20),
        bwlimit=bwlimit,
        state_prefix=state_prefix,
        versions_prefix=versions_prefix,
        follow_symlinks=_boolean(data, "follow_symlinks", False),
        create_empty_dirs=_boolean(data, "create_empty_dirs", True),
        keep_versions=_integer(data, "keep_versions", 30, minimum=1, maximum=100000),
    )


def _toml_string(value: str) -> str:
    # JSON 字符串转义是 TOML 基本字符串的子集，这里只用于生成配置模板。
    return json.dumps(value, ensure_ascii=False)


def _default_device() -> str:
    host = socket.gethostname().strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", host).strip("-._")
    return cleaned[:64] or "device"


def init_config(
    path: Path,
    *,
    device: str | None = None,
    remote: str = "b_crypt",
    force: bool = False,
) -> Path:
    target = path.expanduser().resolve(strict=False)
    if target.exists() and not force:
        raise ConfigError(f"配置文件已存在：{target}\n如需覆盖请加 --force")
    chosen_device = validate_segment(
        (device or _default_device()).strip(), "device", max_length=64
    )
    chosen_remote = _normalize_remote(remote)
    content = f"""# rbackup 配置
# 一台设备一个 device 前缀；不要在两台设备上使用同一个 device。
device = {_toml_string(chosen_device)}
# B 是本地同步目录时，这个 crypt remote 的底层 remote 应指向 B，
# 例如： [b_crypt]
#        type = crypt
#        remote = D:/QuarkSync/rbackup
remote = {_toml_string(chosen_remote)}

# rclone 可执行文件；留空则从 PATH 查找。
rclone_bin = "rclone"
# 可选：显式指定 rclone.conf（默认使用 rclone 自己的配置路径）。
# rclone_config = "C:/Users/you/.config/rclone/rclone.conf"

# watch 轮询间隔（秒）。B 在本地时可设小一些（如 2-5 秒）。
poll_interval = 5
transfers = 4
checkers = 8
retries = 3
# bwlimit = "8M"

# 云端布局；每台设备只写自己的 device 前缀。
state_prefix = "_state"
versions_prefix = "_versions"
follow_symlinks = false
create_empty_dirs = true
keep_versions = 30

[categories.documents]
path = "~/Documents"
excludes = ["**/.git/**", "**/node_modules/**"]
enabled = true

# [categories.photos]
# path = "D:/Photos"
# excludes = []
"""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ConfigError(f"无法写入配置文件 {target}：{exc}") from exc
    return target
