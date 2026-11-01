from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rbackup.config import load_config
from rbackup.errors import ConfigError
from rbackup.webconfig import (
    config_to_payload,
    default_payload,
    normalize_payload,
    payload_to_toml,
    read_payload,
    save_payload,
    validate_payload,
)


class WebConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = self.root / "rbackup.toml"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_roundtrip(self) -> None:
        payload = default_payload()
        payload["device"] = "web-device"
        payload["categories"] = [
            {
                "name": "我的 文档",
                "path": (self.root / "docs").as_posix(),
                "excludes": ["**/.git/**"],
                "enabled": True,
            }
        ]
        text = payload_to_toml(payload)
        self.assertIn('categories."我的 文档"', text)
        path = self.root / "roundtrip.toml"
        path.write_text(text, encoding="utf-8")
        config = load_config(str(path))
        self.assertEqual(config.device, "web-device")
        self.assertEqual(config.categories["我的 文档"].path, (self.root / "docs").resolve())
        restored = config_to_payload(config)
        self.assertEqual(restored["categories"][0]["name"], "我的 文档")
        self.assertEqual(restored["categories"][0]["excludes"], ["**/.git/**"])

    def test_validate_and_save_backup(self) -> None:
        payload = default_payload()
        payload["categories"] = [
            {
                "name": "docs",
                "path": (self.root / "docs").as_posix(),
                "excludes": [],
                "enabled": True,
            }
        ]
        first_device = payload["device"]
        config = validate_payload(payload, self.config)
        self.assertEqual(config.device, first_device)
        saved, backup = save_payload(payload, self.config)
        self.assertTrue(self.config.exists())
        self.assertIsNone(backup)
        self.assertEqual(saved.categories["docs"].path, (self.root / "docs").resolve())

        payload["device"] = "second-device"
        saved, backup = save_payload(payload, self.config)
        self.assertIsNotNone(backup)
        assert backup is not None
        self.assertTrue(backup.exists())
        self.assertEqual(saved.device, "second-device")
        self.assertEqual(load_config(str(backup)).device, first_device)

    def test_duplicate_category_rejected(self) -> None:
        payload = default_payload()
        payload["categories"] = [
            {"name": "Docs", "path": "a", "excludes": [], "enabled": True},
            {"name": "docs", "path": "b", "excludes": [], "enabled": True},
        ]
        with self.assertRaises(ConfigError):
            validate_payload(payload, self.config)

    def test_normalize_rejects_bad_types(self) -> None:
        with self.assertRaises(ConfigError):
            normalize_payload({"transfers": "many"})
        with self.assertRaises(ConfigError):
            normalize_payload({"categories": []})
        with self.assertRaises(ConfigError):
            normalize_payload({"categories": [{"name": "x", "path": 3}]})

    def test_read_missing_and_invalid(self) -> None:
        payload, exists, error = read_payload(self.config)
        self.assertFalse(exists)
        self.assertIsNone(error)
        self.assertIn("categories", payload)

        self.config.write_text("not = [valid", encoding="utf-8")
        payload, exists, error = read_payload(self.config)
        self.assertTrue(exists)
        self.assertIsNotNone(error)
        self.assertIn("categories", payload)


if __name__ == "__main__":
    unittest.main()
