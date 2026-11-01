from __future__ import annotations

from typing import Any

from .app import App, select_categories
from .listing import compare_local_remote, load_local_files, load_snapshot
from .util import human_size, print_json, safe_text


def run_diff(
    app: App,
    names: list[str] | tuple[str, ...] | None,
    *,
    json_output: bool = False,
    check: bool = False,
    max_items: int = 200,
) -> int:
    selected = select_categories(app, names)
    remote = load_snapshot(app.rclone, app.layout)
    categories: dict[str, Any] = {}
    has_differences = False

    for name, category in selected.items():
        local = load_local_files(app.rclone, category)
        comparison = compare_local_remote(local, remote.categories.get(name, {}))
        if (
            comparison["remote_only"]
            or comparison["local_only"]
            or comparison["modified"]
        ):
            has_differences = True
        categories[name] = comparison

    result = {
        "device": app.layout.device,
        "remote": app.layout.remote,
        "has_differences": has_differences,
        "categories": categories,
        "exit_code": 3 if check and has_differences else 0,
    }
    if json_output:
        print_json(result)
        return result["exit_code"]

    for name, info in categories.items():
        print(f"\n[{name}]")
        if info.get("local_missing"):
            print("  本地目录不存在；以下远端文件全部只在 B。")
        print(
            f"  远端独有: {len(info['remote_only'])}  "
            f"本地未备份: {len(info['local_only'])}  "
            f"有差异: {len(info['modified'])}  相同: {info['same']}"
        )
        if info["remote_only"]:
            print("  远端独有（A 已删除或 B 新增，可 restore）：")
            for path in info["remote_only"][:max_items]:
                print(f"    {safe_text(path)}")
            if len(info["remote_only"]) > max_items:
                print(f"    … 还有 {len(info['remote_only']) - max_items} 项")
        if info["local_only"]:
            print("  本地未备份（只在 A）：")
            for path in info["local_only"][:max_items]:
                print(f"    {safe_text(path)}")
            if len(info["local_only"]) > max_items:
                print(f"    … 还有 {len(info['local_only']) - max_items} 项")
        if info["modified"]:
            print("  大小/时间不同：")
            for item in info["modified"][:max_items]:
                reasons = ",".join(item["reasons"])
                print(
                    f"    {safe_text(item['path'])}  "
                    f"本地 {human_size(item['local_size'])} / "
                    f"远端 {human_size(item['remote_size'])}  ({reasons})"
                )
            if len(info["modified"]) > max_items:
                print(f"    … 还有 {len(info['modified']) - max_items} 项")

    print(
        "\n存在本地/远端差异。" if has_differences else "\n本地与远端当前版本一致。"
    )
    return result["exit_code"]
