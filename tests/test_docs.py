"""文档链接守卫：README 与 docs/ 里的相对链接和锚点必须真实存在。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slug(heading: str) -> str:
    text = heading.strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", text)
    return text.replace(" ", "-")


def headings(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {slug(item) for item in re.findall(r"(?m)^#{1,6}\s+(.*)$", text)}


class DocsLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

    def test_docs_exist(self) -> None:
        self.assertGreaterEqual(len(self.files), 2)
        self.assertTrue((ROOT / "README.md").is_file())

    def test_code_fences_balanced(self) -> None:
        for path in self.files:
            text = path.read_text(encoding="utf-8")
            fences = [line for line in text.splitlines() if line.startswith("```")]
            self.assertEqual(
                len(fences) % 2,
                0,
                f"{path.name} 的代码围栏不成对（{len(fences)} 个）",
            )

    def test_relative_links_resolve(self) -> None:
        problems: list[str] = []
        for path in self.files:
            text = path.read_text(encoding="utf-8")
            for target, anchor in re.findall(
                r"\]\(([^)#\s]+)(?:#([^)]+))?\)", text
            ):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    problems.append(f"{path.name}: 链接指向不存在的文件 {target}")
                    continue
                if anchor and resolved.suffix == ".md":
                    if anchor not in headings(resolved):
                        problems.append(
                            f"{path.name}: 锚点不存在 {target}#{anchor}"
                        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_internal_anchors_resolve(self) -> None:
        problems: list[str] = []
        for path in self.files:
            text = path.read_text(encoding="utf-8")
            own = headings(path)
            for anchor in re.findall(r"\]\(#([^)]+)\)", text):
                if anchor not in own:
                    problems.append(f"{path.name}: 本页锚点不存在 #{anchor}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
