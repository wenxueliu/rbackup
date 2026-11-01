from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rbackup.config import init_config, load_config
from rbackup.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, text: str) -> Path:
        path = self.root / "rbackup.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_minimal(self) -> None:
        cfg = self.write(
            f"""
device = "laptop"
remote = "quark_enc:"
poll_interval = 7

[categories.docs]
path = "docs"
excludes = ["**/.git/**"]
"""
        )
        loaded = load_config(str(cfg))
        self.assertEqual(loaded.device, "laptop")
        self.assertEqual(loaded.remote, "quark_enc")
        self.assertEqual(loaded.poll_interval, 7.0)
        self.assertEqual(loaded.categories["docs"].path, (self.root / "docs").resolve())
        self.assertEqual(loaded.categories["docs"].excludes, ("**/.git/**",))

    def test_utf8_bom_is_accepted(self) -> None:
        path = self.root / "bom.toml"
        path.write_bytes(
            b"\xef\xbb\xbf"
            + b'device = "laptop"\nremote = "q"\n[categories.docs]\npath = "docs"\n'
        )
        loaded = load_config(str(path))
        self.assertEqual(loaded.device, "laptop")

    def test_unknown_top_level_key(self) -> None:
        cfg = self.write(
            """
device = "laptop"
remote = "q"
typo = true
[categories.docs]
path = "docs"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(str(cfg))

    def test_duplicate_casefold_category(self) -> None:
        cfg = self.write(
            """
device = "laptop"
remote = "q"
[categories.Docs]
path = "docs"
[categories.docs]
path = "docs2"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(str(cfg))

    def test_invalid_device(self) -> None:
        cfg = self.write(
            """
device = "bad/device"
remote = "q"
[categories.docs]
path = "docs"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(str(cfg))

    def test_prefix_collision(self) -> None:
        cfg = self.write(
            """
device = "laptop"
remote = "q"
state_prefix = "_versions"
versions_prefix = "_versions"
[categories.docs]
path = "docs"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(str(cfg))

    def test_missing_rclone_config(self) -> None:
        cfg = self.write(
            """
device = "laptop"
remote = "q"
rclone_config = "missing.conf"
[categories.docs]
path = "docs"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(str(cfg))

    def test_init_and_force(self) -> None:
        target = self.root / "nested" / "config.toml"
        path = init_config(target, device="my-pc", remote="quark_enc")
        self.assertTrue(path.exists())
        loaded = load_config(str(path))
        self.assertEqual(loaded.device, "my-pc")
        self.assertIn("documents", loaded.categories)
        with self.assertRaises(ConfigError):
            init_config(target, device="my-pc")
        init_config(target, device="other-pc", force=True)
        self.assertEqual(load_config(str(target)).device, "other-pc")


if __name__ == "__main__":
    unittest.main()
