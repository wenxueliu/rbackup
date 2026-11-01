"""浏览器页面的 A/B 对比与写操作。

这里的函数都以上面表单里提交的 payload 为准（不必先保存配置），
因此每次调用都会重新构造一次 App，保证与保存后的行为一致。
"""

from __future__ import annotations

import shutil
import socket
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .app import App, select_categories
from .errors import UsageError
from .layout import normalize_relpath
from .listing import load_local_files, load_snapshot
from .rclone import MISSING_REMOTE_CODES, RcloneError
from .state import State
from .util import iso_now, mtime_close, new_version_id
from .webconfig import validate_payload

MAX_PATHS = 2000
DEFAULT_ROW_LIMIT = 3000
MTIME_TOLERANCE = 3.0

_STATE_LABELS = {
    "same": "一致",
    "modified": "大小/时间不同",
    "local_only": "只在 A",
    "remote_only": "只在 B",
}


def app_from_payload(payload: dict[str, Any], config_path: Path) -> App:
    """用页面提交的 payload 构造 App；配置不完整时抛 ConfigError。"""
    config = validate_payload(payload, config_path)
    return App.from_config(config)


def clean_paths(raw: Any) -> list[str]:
    """校验并规范化一批相对路径（文件或目录都允许）。"""
    if raw is None:
        raise UsageError("缺少 paths 参数")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise UsageError("paths 必须是字符串数组")
    if len(raw) > MAX_PATHS:
        raise UsageError(f"一次最多操作 {MAX_PATHS} 项，请分批执行")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        path = normalize_relpath(item)
        if not path:
            raise UsageError("不能对类别根目录整体操作，请选择具体文件或文件夹")
        if path in seen:
            continue
        seen.add(path)
        cleaned.append(path)
    if not cleaned:
        raise UsageError("没有指定要操作的路径")
    return cleaned


def _list_dirs(
    app: App, path: str, filters: Iterable[str] = ()
) -> set[str]:
    try:
        rows = app.rclone.list_dirs(path, recursive=True, filters=filters)
    except RcloneError as exc:
        if exc.returncode in MISSING_REMOTE_CODES:
            return set()
        raise
    result: set[str] = set()
    for row in rows:
        if not row.get("IsDir"):
            continue
        value = str(row.get("Path", "")).strip("/")
        if value:
            result.add(value)
    return result


def _file_row(path: str, state: str, left: Any, right: Any) -> dict[str, Any]:
    return {
        "path": path,
        "state": state,
        "label": _STATE_LABELS.get(state, state),
        "local_size": left.size if left is not None else None,
        "remote_size": right.size if right is not None else None,
        "local_mtime": left.mtime if left is not None else None,
        "remote_mtime": right.mtime if right is not None else None,
    }


def compute_diff(
    app: App,
    names: list[str] | tuple[str, ...] | None = None,
    *,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> dict[str, Any]:
    """只读对比 A 与 B 当前版本，返回文件与文件夹两级结果。"""
    if names:
        selected = select_categories(app, names)
    else:
        selected = dict(app.config.categories)
    if not selected:
        raise UsageError("配置中没有类别")

    snapshot = load_snapshot(app.rclone, app.layout)
    categories: list[dict[str, Any]] = []
    truncated = False

    for name, category in selected.items():
        local = load_local_files(app.rclone, category)
        remote_files = snapshot.categories.get(name, {})
        local_files = local or {}

        dirs: list[dict[str, Any]] = []
        if local is not None:
            local_dirs = _list_dirs(app, str(category.path), category.excludes)
            remote_dirs = _list_dirs(app, app.layout.category_root(name))
            for path in sorted(local_dirs | remote_dirs):
                dirs.append(
                    {
                        "path": path,
                        "in_a": path in local_dirs,
                        "in_b": path in remote_dirs,
                    }
                )

        counts = {"same": 0, "modified": 0, "local_only": 0, "remote_only": 0}
        interesting: list[dict[str, Any]] = []
        same: list[dict[str, Any]] = []
        for path in sorted(set(local_files) | set(remote_files)):
            left = local_files.get(path)
            right = remote_files.get(path)
            if left is not None and right is not None:
                unchanged = left.size == right.size and mtime_close(
                    left.mtime, right.mtime, MTIME_TOLERANCE
                )
                state = "same" if unchanged else "modified"
            elif left is not None:
                state = "local_only"
            elif right is not None:
                state = "remote_only"
            else:  # pragma: no cover - 并集不会出现这种情况
                continue
            counts[state] += 1
            row = _file_row(path, state, left, right)
            (same if state == "same" else interesting).append(row)

        budget = max(0, row_limit - len(dirs))
        if len(interesting) + len(same) > budget:
            truncated = True
            files = interesting[:budget]
            if len(interesting) < budget:
                files.extend(same[: budget - len(interesting)])
        else:
            files = interesting + same

        categories.append(
            {
                "name": name,
                "local_path": str(category.path),
                "local_missing": local is None,
                "enabled": category.enabled,
                "excludes": list(category.excludes),
                "dirs": dirs,
                "files": files,
                "counts": counts,
                "dir_count": len(dirs),
            }
        )

    return {
        "ok": True,
        "device": app.layout.device,
        "remote": app.layout.remote,
        "b_path": str(app.b_path) if app.b_path else None,
        "truncated": truncated,
        "row_limit": row_limit,
        "categories": categories,
    }


def upload_paths(
    app: App,
    category_name: str,
    paths: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """把 A 中的文件或文件夹上传到 B 的当前版本，旧内容进 _versions。"""
    category = app.config.category(category_name)
    if not category.enabled:
        raise UsageError(f"类别 {category_name!r} 已禁用，请先启用")
    if not category.path.exists() or not category.path.is_dir():
        raise UsageError(f"类别 {category_name!r} 的 A 目录不存在：{category.path}")

    cleaned = clean_paths(paths)
    version_id = new_version_id()
    version_root = app.layout.version_category(version_id, category_name)
    destination_root = app.layout.category_root(category_name)

    results: list[dict[str, Any]] = []
    for relpath in cleaned:
        source = category.path / PurePosixPath(relpath)
        if not source.exists():
            results.append(
                {"path": relpath, "ok": False, "error": "A 中不存在该路径"}
            )
            continue
        is_dir = source.is_dir()
        parent = PurePosixPath(relpath).parent
        parent_text = "" if parent == PurePosixPath(".") else parent.as_posix()
        # 让旧版本落到 _versions/<vid>/<类别>/<原始相对目录>，与 backup 的布局一致
        backup_dir = version_root + (f"/{parent_text}" if parent_text else "")
        destination = f"{destination_root}/{relpath}"
        try:
            if is_dir:
                app.rclone.copy(
                    str(source),
                    destination,
                    backup_dir=backup_dir,
                    dry_run=dry_run,
                    filters=category.excludes,
                    create_empty_dirs=app.config.create_empty_dirs,
                )
            else:
                app.rclone.copyto(
                    str(source),
                    destination,
                    backup_dir=backup_dir,
                    dry_run=dry_run,
                )
        except RcloneError as exc:
            results.append(
                {
                    "path": relpath,
                    "ok": False,
                    "kind": "dir" if is_dir else "file",
                    "error": str(exc)[:2000],
                }
            )
            continue
        results.append(
            {"path": relpath, "ok": True, "kind": "dir" if is_dir else "file"}
        )

    uploaded = sum(1 for item in results if item["ok"])
    return {
        "ok": True,
        "dry_run": dry_run,
        "category": category_name,
        "version_id": version_id,
        "results": results,
        "uploaded": uploaded,
        "failed": len(results) - uploaded,
        "state_stale": bool(uploaded) and not dry_run,
    }


def delete_paths(
    app: App,
    category_name: str,
    paths: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """删除 B 当前版本中的文件或文件夹。不产生 _versions 记录。"""
    app.config.category(category_name)  # 仅校验类别存在
    cleaned = clean_paths(paths)

    results: list[dict[str, Any]] = []
    for relpath in cleaned:
        target = app.layout.category_file(category_name, relpath)
        try:
            info = app.rclone.stat(target)
        except RcloneError as exc:
            results.append(
                {"path": relpath, "ok": False, "error": str(exc)[:2000]}
            )
            continue
        if info is None:
            results.append(
                {"path": relpath, "ok": False, "error": "B 中不存在该路径"}
            )
            continue
        is_dir = bool(info.get("IsDir"))
        try:
            if is_dir:
                app.rclone.purge(target, dry_run=dry_run)
            else:
                app.rclone.deletefile(target, dry_run=dry_run)
        except RcloneError as exc:
            results.append(
                {
                    "path": relpath,
                    "ok": False,
                    "kind": "dir" if is_dir else "file",
                    "error": str(exc)[:2000],
                }
            )
            continue
        results.append(
            {"path": relpath, "ok": True, "kind": "dir" if is_dir else "file"}
        )

    deleted = sum(1 for item in results if item["ok"])
    return {
        "ok": True,
        "dry_run": dry_run,
        "category": category_name,
        "results": results,
        "deleted": deleted,
        "failed": len(results) - deleted,
        "state_stale": bool(deleted) and not dry_run,
    }


def delete_local_paths(
    app: App,
    category_name: str,
    paths: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """删除 A 中的文件或文件夹（明文源）。B 保持不变，因此不产生基线漂移。"""
    category = app.config.category(category_name)
    if not category.enabled:
        raise UsageError(f"类别 {category_name!r} 已禁用，请先启用")
    if not category.path.exists() or not category.path.is_dir():
        raise UsageError(f"类别 {category_name!r} 的 A 目录不存在：{category.path}")

    cleaned = clean_paths(paths)
    root = category.path.resolve()
    results: list[dict[str, Any]] = []

    for relpath in cleaned:
        target = category.path / PurePosixPath(relpath)
        try:
            resolved = target.resolve(strict=False)
        except OSError as exc:
            results.append(
                {"path": relpath, "ok": False, "error": f"无法解析路径：{exc}"}
            )
            continue
        # 双保险：normalize_relpath 已拒绝 ..，这里再挡住符号链接指到 A 之外的情况
        if resolved == root or root not in resolved.parents:
            results.append(
                {
                    "path": relpath,
                    "ok": False,
                    "error": "解析后的路径不在 A 目录内，已拒绝",
                }
            )
            continue
        if not target.exists() and not target.is_symlink():
            results.append(
                {"path": relpath, "ok": False, "error": "A 中不存在该路径"}
            )
            continue

        is_link = target.is_symlink()
        is_dir = target.is_dir() and not is_link
        if not dry_run:
            try:
                if is_link or target.is_file():
                    target.unlink()
                elif is_dir:
                    shutil.rmtree(target)
                else:
                    results.append(
                        {
                            "path": relpath,
                            "ok": False,
                            "error": "不是普通文件或目录，已跳过",
                        }
                    )
                    continue
            except OSError as exc:
                results.append(
                    {
                        "path": relpath,
                        "ok": False,
                        "kind": "dir" if is_dir else "file",
                        "error": str(exc)[:2000],
                    }
                )
                continue
        results.append(
            {"path": relpath, "ok": True, "kind": "dir" if is_dir else "file"}
        )

    deleted = sum(1 for item in results if item["ok"])
    return {
        "ok": True,
        "dry_run": dry_run,
        "category": category_name,
        "results": results,
        "deleted": deleted,
        "failed": len(results) - deleted,
        # 只动 A 不影响 B，基线仍然有效
        "state_stale": False,
    }


def rebaseline(
    app: App, names: list[str] | tuple[str, ...] | None = None
) -> dict[str, Any]:
    """按 B 的当前内容重写 _state 基线，用于消除手工操作后的漂移。"""
    if names:
        selected = select_categories(app, names)
    else:
        selected = app.config.enabled_categories()
        if not selected:
            raise UsageError("配置中没有启用的类别")

    snapshot = load_snapshot(app.rclone, app.layout)
    state = app.state.load()
    if state is None:
        version_id = new_version_id()
        state = State(
            device=app.layout.device,
            remote=app.layout.remote,
            run_id=version_id,
            version_id=version_id,
            started_at=iso_now(),
            hostname=socket.gethostname(),
            rclone_version=app.rclone.version(),
        )

    updated: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for name in selected:
        files = snapshot.categories.get(name, {})
        entry = dict(state.categories.get(name) or {})
        entry.update(
            {
                "status": "ok",
                "files": len(files),
                "bytes": sum(item.size for item in files.values()),
                "digest": snapshot.category_digest(name),
                "version_id": state.version_id,
                "updated_at": iso_now(),
            }
        )
        entry.pop("error", None)
        state.categories[name] = entry
        updated.append(name)
        counts[name] = {"files": entry["files"], "bytes": entry["bytes"]}

    state.status = "ok"
    state.error = None
    state.finished_at = iso_now()
    app.state.save(state)
    return {
        "ok": True,
        "updated": updated,
        "version_id": state.version_id,
        "counts": counts,
    }
