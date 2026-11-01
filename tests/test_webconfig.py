from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rbackup.config import load_config
from rbackup.errors import ConfigError
from rbackup.webconfig import (
    CONFIG_BACKUP_KEEP,
    config_backup_dir,
    config_to_payload,
    default_payload,
    list_config_backups,
    normalize_payload,
    payload_to_toml,
    read_payload,
    restore_config_backup,
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

    # ---------- 配置历史备份 ----------

    def _payload(self, device: str):
        payload = default_payload()
        payload["device"] = device
        payload["categories"] = [
            {
                "name": "docs",
                "path": (self.root / "docs").as_posix(),
                "excludes": [],
                "enabled": True,
            }
        ]
        return payload

    def test_save_creates_history_backup(self) -> None:
        save_payload(self._payload("one"), self.config)
        self.assertEqual(list_config_backups(self.config), [])

        _saved, history = save_payload(self._payload("two"), self.config)
        self.assertIsNotNone(history)
        assert history is not None
        self.assertTrue(history.exists())
        self.assertEqual(history.parent, config_backup_dir(self.config))
        self.assertEqual(load_config(str(history)).device, "one")

        backups = list_config_backups(self.config)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["name"], history.name)

    def test_history_keeps_only_latest(self) -> None:
        save_payload(self._payload("v0"), self.config)
        for index in range(1, CONFIG_BACKUP_KEEP + 6):
            save_payload(self._payload(f"v{index}"), self.config)
        backups = list_config_backups(self.config)
        self.assertEqual(len(backups), CONFIG_BACKUP_KEEP)

    def test_list_is_newest_first(self) -> None:
        save_payload(self._payload("v0"), self.config)
        for index in range(1, 4):
            save_payload(self._payload(f"v{index}"), self.config)
        backups = list_config_backups(self.config)
        self.assertEqual(len(backups), 3)
        self.assertGreaterEqual(backups[0]["mtime"], backups[-1]["mtime"])

    def test_restore_history_backup(self) -> None:
        save_payload(self._payload("原始"), self.config)
        save_payload(self._payload("改过的"), self.config)
        self.assertEqual(load_config(str(self.config)).device, "改过的")

        backups = list_config_backups(self.config)
        source, safety = restore_config_backup(self.config, backups[0]["name"])
        self.assertTrue(source.exists())
        self.assertIsNotNone(safety)
        self.assertEqual(load_config(str(self.config)).device, "原始")
        # 覆盖前的配置被保住
        assert safety is not None
        self.assertEqual(load_config(str(safety)).device, "改过的")

    def test_restore_rejects_path_traversal(self) -> None:
        save_payload(self._payload("x"), self.config)
        with self.assertRaises(ConfigError):
            restore_config_backup(self.config, "../rbackup.toml")
        with self.assertRaises(ConfigError):
            restore_config_backup(self.config, "missing.toml")

    def test_restore_rejects_invalid_backup(self) -> None:
        save_payload(self._payload("x"), self.config)
        directory = config_backup_dir(self.config)
        directory.mkdir(parents=True, exist_ok=True)
        broken = directory / "broken.toml"
        broken.write_text("not = [valid", encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            restore_config_backup(self.config, broken.name)
        self.assertIn("无法解析", str(ctx.exception))
        # 当前配置没被破坏
        self.assertEqual(load_config(str(self.config)).device, "x")


if __name__ == "__main__":
    unittest.main()
