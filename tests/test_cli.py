from __future__ import annotations

import unittest

from rbackup.cli import build_parser


class CliParserTests(unittest.TestCase):
    def test_global_config_before_command(self) -> None:
        args = build_parser().parse_args(["--config", "x.toml", "backup", "docs", "--json"])
        self.assertEqual(args.command, "backup")
        self.assertEqual(args.config, "x.toml")
        self.assertEqual(args.categories, ["docs"])
        self.assertTrue(args.json_output)

    def test_config_after_command(self) -> None:
        args = build_parser().parse_args(["status", "--config", "x.toml", "--check"])
        self.assertEqual(args.config, "x.toml")
        self.assertTrue(args.check)

    def test_web_command(self) -> None:
        args = build_parser().parse_args(["web", "--port", "9000", "--no-browser"])
        self.assertEqual(args.command, "web")
        self.assertEqual(args.port, 9000)
        self.assertTrue(args.no_browser)

    def test_restore_requires_dest(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["restore", "docs", "a.txt"])


if __name__ == "__main__":
    unittest.main()
