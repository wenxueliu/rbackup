from __future__ import annotations

import os
import unittest

from rbackup.errors import UsageError
from rbackup.layout import Layout, normalize_relpath, validate_version_id


class LayoutTests(unittest.TestCase):
    def test_normalize_basic(self) -> None:
        self.assertEqual(normalize_relpath(""), "")
        self.assertEqual(normalize_relpath("a//b/./c"), "a/b/c")
        self.assertEqual(normalize_relpath("a/b/"), "a/b")
        self.assertEqual(normalize_relpath(" a "), " a ")

    @unittest.skipUnless(os.name == "nt", "Windows 路径习惯")
    def test_normalize_windows_separator(self) -> None:
        self.assertEqual(normalize_relpath("sub\\file.txt"), "sub/file.txt")

    def test_reject_traversal_and_absolute(self) -> None:
        for value in ("../secret", "a/../../b", "/abs/path", "C:/Windows/x"):
            with self.subTest(value=value):
                with self.assertRaises(UsageError):
                    normalize_relpath(value)

    def test_version_id(self) -> None:
        self.assertEqual(
            validate_version_id("20261030T235653Z-a1b2c3"),
            "20261030T235653Z-a1b2c3",
        )
        with self.assertRaises(UsageError):
            validate_version_id("2026-10-30")

    def test_layout_paths(self) -> None:
        layout = Layout(remote="crypt", device="dev")
        self.assertEqual(layout.state_file, "crypt:_state/dev/last-run.json")
        self.assertEqual(layout.category_root("docs"), "crypt:dev/docs")
        self.assertEqual(
            layout.category_file("docs", "sub/a.txt"), "crypt:dev/docs/sub/a.txt"
        )
        version = "20261030T235653Z-a1b2c3"
        self.assertEqual(layout.version_root(version), f"crypt:_versions/dev/{version}")
        self.assertEqual(
            layout.version_file(version, "docs", "sub/a.txt"),
            f"crypt:_versions/dev/{version}/docs/sub/a.txt",
        )


if __name__ == "__main__":
    unittest.main()
