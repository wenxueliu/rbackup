from __future__ import annotations

import sys
from typing import Any

from .app import App, select_categories
from .errors import VerifyError
from .util import print_json


def _looks_like_unsupported(output: str) -> bool:
    lowered = output.lower()
    needles = (
        "doesn't support",
        "does not support",
        "not support checksum",
        "no hashes",
        "hash type not supported",
        "unsupported hash",
    )
    return any(needle in lowered for needle in needles)


def verify_category(
    app: App,
    category_name: str,
    *,
    one_way: bool,
) -> dict[str, Any]:
    category = app.config.category(category_name)
    if not category.path.exists() or not category.path.is_dir():
        raise VerifyError(
            f"本地目录不存在，无法 cryptcheck：{category.path}（A 可能已删除该目录）"
        )
    result = app.rclone.cryptcheck(
        str(category.path),
        app.layout.category_root(category_name),
        one_way=one_way,
        filters=category.excludes,
        timeout=None,
    )
    combined = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    ).strip()
    unsupported = result.returncode != 0 and _looks_like_unsupported(combined)
    return {
        "category": category_name,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "one_way": one_way,
        "unsupported": unsupported,
        "output": combined[-8000:],
    }


def run_verify(
    app: App,
    names: list[str] | tuple[str, ...] | None,
    *,
    one_way: bool = False,
    json_output: bool = False,
) -> int:
    selected = select_categories(app, names)
    results: list[dict[str, Any]] = []
    for name in selected:
        try:
            result = verify_category(app, name, one_way=one_way)
        except VerifyError as exc:
            result = {
                "category": name,
                "ok": False,
                "returncode": None,
                "one_way": one_way,
                "unsupported": False,
                "output": str(exc),
            }
        results.append(result)
        if not json_output:
            state = "通过" if result["ok"] else "失败"
            if result.get("unsupported"):
                state = "失败（底层远端不支持 checksum）"
            print(f"[{name}] cryptcheck {state}（退出码 {result['returncode']}）")
            if result["output"]:
                print(result["output"])
            print()

    summary = {
        "ok": all(item["ok"] for item in results),
        "one_way": one_way,
        "categories": results,
    }
    if json_output:
        print_json(summary)
    else:
        passed = sum(1 for item in results if item["ok"])
        print(f"校验完成：{passed}/{len(results)} 个类别通过")
        if any(item.get("unsupported") for item in results):
            print(
                "提示：cryptcheck 需要底层远端提供 checksum；"
                "如果 Quark 后端不支持，rclone 会直接报错而不会下载文件。",
                file=sys.stderr,
            )
    return 0 if summary["ok"] else 4
