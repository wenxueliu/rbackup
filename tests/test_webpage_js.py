"""在 Node 里跑页面过滤逻辑：状态 / A 列 / B 列。

过滤是纯函数，但写在页面脚本里，Python 测试覆盖不到；这里把函数源码抽出来，
配一个最小 harness 真跑一遍。机器上没有 node 时整组跳过。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rbackup.webpage import render_page

NODE = shutil.which("node")

FUNCTIONS = ("dirState", "itemSides", "sideMatches", "keepItem")


def function_source(script: str, name: str) -> str:
    """按大括号配对抽出 function 定义。"""
    match = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", script)
    if not match:
        raise AssertionError(f"页面脚本里找不到函数 {name}")
    start = match.start()
    index = script.index("{", match.end())
    depth = 0
    for position in range(index, len(script)):
        char = script[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script[start : position + 1]
    raise AssertionError(f"函数 {name} 没有闭合")


def run_js(script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "harness.js"
        path.write_text(script, encoding="utf-8")
        return subprocess.run(
            [NODE, str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )


@unittest.skipUnless(NODE, "需要 node 才能校验页面脚本逻辑")
class FilterLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        page = render_page("token")
        script = re.search(r"<script>(.*?)</script>", page, flags=re.S)
        assert script is not None
        cls.sources = {
            name: function_source(script.group(1), name) for name in FUNCTIONS
        }

    def check(self, cases: list[list]) -> None:
        payload = json.dumps(cases, ensure_ascii=False)
        harness = (
            "\n".join(self.sources.values())
            + "\nconst cases = "
            + payload
            + ";\n"
            "const bad = [];\n"
            "for (const [kind, item, filters, expected] of cases) {\n"
            "  const got = keepItem(kind, item, filters);\n"
            "  if (got !== expected) {\n"
            "    bad.push(JSON.stringify({ kind, item, filters, expected, got }));\n"
            "  }\n"
            "}\n"
            "if (bad.length) { console.error(bad.join('\\n')); process.exit(1); }\n"
            "console.log('ok');\n"
        )
        result = run_js(harness)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_state_filter(self) -> None:
        same = {"path": "a", "state": "same"}
        modified = {"path": "a", "state": "modified"}
        local_only = {"path": "a", "state": "local_only"}
        remote_only = {"path": "a", "state": "remote_only"}
        all_yes = {"state": "all", "a": "all", "b": "all"}

        self.check(
            [
                ["file", same, all_yes, True],
                ["file", same, {"state": "diff", "a": "all", "b": "all"}, False],
                ["file", modified, {"state": "diff", "a": "all", "b": "all"}, True],
                ["file", local_only, {"state": "diff", "a": "all", "b": "all"}, True],
                ["file", remote_only, {"state": "diff", "a": "all", "b": "all"}, True],
                ["file", same, {"state": "same", "a": "all", "b": "all"}, True],
                ["file", same, {"state": "modified", "a": "all", "b": "all"}, False],
                ["file", modified, {"state": "modified", "a": "all", "b": "all"}, True],
                ["file", local_only, {"state": "local", "a": "all", "b": "all"}, True],
                ["file", remote_only, {"state": "local", "a": "all", "b": "all"}, False],
                ["file", remote_only, {"state": "remote", "a": "all", "b": "all"}, True],
            ]
        )

    def test_side_filters(self) -> None:
        local_only = {"path": "a", "state": "local_only"}
        remote_only = {"path": "a", "state": "remote_only"}
        both = {"path": "a", "state": "same"}

        self.check(
            [
                # 只在 A：A 有、B 没有
                ["file", local_only, {"state": "all", "a": "yes", "b": "no"}, True],
                ["file", local_only, {"state": "all", "a": "yes", "b": "yes"}, False],
                ["file", local_only, {"state": "all", "a": "no", "b": "all"}, False],
                # 只在 B：A 没有、B 有
                ["file", remote_only, {"state": "all", "a": "no", "b": "yes"}, True],
                ["file", remote_only, {"state": "all", "a": "yes", "b": "all"}, False],
                ["file", remote_only, {"state": "all", "a": "all", "b": "no"}, False],
                # 两边都有
                ["file", both, {"state": "all", "a": "yes", "b": "yes"}, True],
                ["file", both, {"state": "all", "a": "no", "b": "all"}, False],
            ]
        )

    def test_directory_rows(self) -> None:
        both = {"path": "d", "in_a": True, "in_b": True}
        only_a = {"path": "d", "in_a": True, "in_b": False}
        only_b = {"path": "d", "in_a": False, "in_b": True}

        self.check(
            [
                ["dir", both, {"state": "diff", "a": "all", "b": "all"}, False],
                ["dir", only_a, {"state": "diff", "a": "all", "b": "all"}, True],
                ["dir", both, {"state": "same", "a": "all", "b": "all"}, True],
                ["dir", only_a, {"state": "local", "a": "all", "b": "all"}, True],
                ["dir", only_b, {"state": "remote", "a": "all", "b": "all"}, True],
                ["dir", only_a, {"state": "all", "a": "yes", "b": "no"}, True],
                ["dir", only_b, {"state": "all", "a": "no", "b": "yes"}, True],
                # 目录没有「大小/时间不同」这种状态
                ["dir", both, {"state": "modified", "a": "all", "b": "all"}, False],
            ]
        )

    def test_combined_filters(self) -> None:
        local_only = {"path": "a", "state": "local_only"}
        # 状态说「只看差异」，A 列说「无」→ 互相矛盾，结果应为空
        self.check([["file", local_only, {"state": "diff", "a": "no", "b": "all"}, False]])


if __name__ == "__main__":
    unittest.main()
