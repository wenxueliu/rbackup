from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .app import App
from .errors import UsageError
from .layout import normalize_relpath, validate_version_id
from .util import print_json


def run_restore(
    app: App,
    category_name: str,
    remote_path: str,
    destination: str,
    *,
    version_id: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
) -> int:
    category = app.config.category(category_name)
    relpath = normalize_relpath(remote_path)
    if version_id:
        validate_version_id(version_id)
        source = app.layout.version_file(version_id, category_name, relpath)
    else:
        source = app.layout.category_file(category_name, relpath)

    info = app.rclone.stat(source)
    if info is None:
        hint = "当前版本" if not version_id else f"版本 {version_id}"
        raise UsageError(f"{hint}中不存在：{category_name}/{relpath}".rstrip("/"))

    is_dir = bool(info.get("IsDir"))
    destination_path = Path(destination).expanduser().resolve(strict=False)
    overwrite = False

    if is_dir:
        if destination_path.exists() and not destination_path.is_dir():
            raise UsageError(f"目标是文件，但恢复源是目录：{destination_path}")
        if destination_path.exists() and any(destination_path.iterdir()):
            overwrite = True
            if not force and not dry_run:
                raise UsageError(
                    f"目标目录非空：{destination_path}\n"
                    "为避免覆盖，请换一个空目录，或确认后加 --force（copy 不会删除目标中多出的文件）。"
                )
        if not dry_run:
            destination_path.mkdir(parents=True, exist_ok=True)
        print(
            f"{'[dry-run] ' if dry_run else ''}恢复目录 {source} -> {destination_path}",
            file=sys.stderr,
        )
        app.rclone.copy(
            source,
            str(destination_path),
            dry_run=dry_run,
            create_empty_dirs=True,
        )
    else:
        if destination_path.exists() and destination_path.is_dir():
            name = PurePosixPath(relpath).name or "restored"
            destination_path = destination_path / name
        if destination_path.exists() and not force and not dry_run:
            raise UsageError(
                f"目标文件已存在：{destination_path}\n确认覆盖请加 --force。"
            )
        overwrite = destination_path.exists()
        if not dry_run:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"{'[dry-run] ' if dry_run else ''}恢复文件 {source} -> {destination_path}",
            file=sys.stderr,
        )
        app.rclone.copyto(source, str(destination_path), dry_run=dry_run)

    result: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "category": category_name,
        "remote_path": relpath,
        "version_id": version_id,
        "source": source,
        "destination": str(destination_path),
        "is_dir": is_dir,
        "overwrite": overwrite,
        "local_source": str(category.path),
    }
    if json_output:
        print_json(result)
    else:
        print(
            f"恢复完成：{source} -> {destination_path}"
            + ("（dry-run，未写入）" if dry_run else "")
        )
    return 0
