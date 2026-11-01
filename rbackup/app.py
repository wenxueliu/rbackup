from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import Category, Config, load_config
from .errors import ConfigError, UsageError
from .layout import Layout
from .rclone import Rclone
from .state import StateStore


def local_target_path(value: str | None) -> Path | None:
    """如果 crypt remote 的底层是本地绝对目录，返回规范化路径。

    `quark:path` 这类云端路径不是本地路径，返回 None。
    """
    if not value:
        return None
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        return None
    return candidate.resolve(strict=False)


def validate_b_not_nested(config: Config, b_path: Path) -> None:
    """A 的类别目录与本地 B 不能相同或互相嵌套。

    B 在 A 内：rclone 会把 B 的密文再次备份进自己，可能递归。
    A 在 B 内：网盘客户端同步 B 时会把 A 的明文也上传，破坏加密边界。
    """
    for name, category in config.categories.items():
        a_path = category.path
        if a_path == b_path or a_path in b_path.parents or b_path in a_path.parents:
            raise ConfigError(
                f"本地 B 目录 {b_path} 与类别 {name!r} 的 A 目录 {a_path} "
                "相同或互相嵌套。请把 B 放在 A 之外，且不要把 A 放进 B 的同步范围。"
            )


@dataclass
class App:
    config: Config
    rclone: Rclone
    layout: Layout
    state: StateStore
    b_path: Path | None = None

    @classmethod
    def create(
        cls, config_path: str | None = None, *, require_crypt: bool = True
    ) -> "App":
        return cls.from_config(load_config(config_path), require_crypt=require_crypt)

    @classmethod
    def from_config(cls, config: Config, *, require_crypt: bool = True) -> "App":
        rclone = Rclone(config)
        b_path: Path | None = None
        if require_crypt:
            remote_config = rclone.remote_config(config.remote)
            remote_type = remote_config.get("type", "")
            if remote_type != "crypt":
                raise ConfigError(
                    f"remote {config.remote!r} 的类型是 {remote_type!r}，不是 crypt。"
                    "为避免把明文上传到 B，已停止。请配置一个 rclone crypt remote，"
                    "并把它填到 remote。"
                )
            b_path = local_target_path(remote_config.get("remote"))
            if b_path is not None:
                if not b_path.exists():
                    raise ConfigError(
                        f"本地 B 同步目录不存在：{b_path}\n"
                        "请先创建 B，并确认网盘客户端正在同步它。"
                    )
                if not b_path.is_dir():
                    raise ConfigError(f"本地 B 路径不是目录：{b_path}")
                validate_b_not_nested(config, b_path)
        layout = Layout(
            remote=config.remote,
            device=config.device,
            state_prefix=config.state_prefix,
            versions_prefix=config.versions_prefix,
        )
        return cls(
            config=config,
            rclone=rclone,
            layout=layout,
            state=StateStore(rclone, layout),
            b_path=b_path,
        )


def select_categories(
    app: App, names: list[str] | tuple[str, ...] | None
) -> dict[str, Category]:
    enabled = app.config.enabled_categories()
    if not names:
        if not enabled:
            raise UsageError("配置中没有启用的类别")
        return enabled
    selected: dict[str, Category] = {}
    for name in names:
        category = app.config.category(name)
        if not category.enabled:
            raise UsageError(f"类别 {name!r} 在配置中被禁用")
        selected[name] = category
    if not selected:
        raise UsageError("没有选择任何类别")
    return selected
