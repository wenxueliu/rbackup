from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rbackup.app import App
from rbackup.errors import ConfigError


class AppTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = self.root / "rbackup.toml"
        self.config.write_text(
            """
device = "dev"
remote = "crypt"
[categories.docs]
path = "docs"
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("rbackup.app.Rclone.remote_config", return_value={"type": "local"})
    def test_rejects_non_crypt_remote(self, _remote_config) -> None:
        with self.assertRaises(ConfigError) as ctx:
            App.create(str(self.config))
        self.assertIn("不是 crypt", str(ctx.exception))

    @patch("rbackup.app.Rclone.remote_config", return_value={"type": "crypt"})
    def test_accepts_crypt_remote(self, _remote_config) -> None:
        app = App.create(str(self.config))
        self.assertEqual(app.layout.device, "dev")
        self.assertEqual(app.layout.remote, "crypt")
        self.assertIsNone(app.b_path)

    @patch("rbackup.app.Rclone.remote_config", return_value={"type": "local"})
    def test_doctor_can_create_without_gate(self, _remote_config) -> None:
        app = App.create(str(self.config), require_crypt=False)
        self.assertEqual(app.config.remote, "crypt")

    def test_missing_local_b_is_rejected(self) -> None:
        missing = self.root / "missing-b"
        with patch(
            "rbackup.app.Rclone.remote_config",
            return_value={"type": "crypt", "remote": str(missing)},
        ):
            with self.assertRaises(ConfigError) as ctx:
                App.create(str(self.config))
        self.assertIn("不存在", str(ctx.exception))

    def test_detects_local_b_and_nesting(self) -> None:
        b_path = self.root / "b"
        b_path.mkdir()
        with patch(
            "rbackup.app.Rclone.remote_config",
            return_value={"type": "crypt", "remote": str(b_path)},
        ):
            app = App.create(str(self.config))
            self.assertEqual(app.b_path, b_path.resolve())

        nested = self.root / "sync"
        nested.mkdir()
        self.config.write_text(
            f"""
device = "dev"
remote = "crypt"
[categories.docs]
path = "{nested.as_posix()}/docs"
""",
            encoding="utf-8",
        )
        with patch(
            "rbackup.app.Rclone.remote_config",
            return_value={"type": "crypt", "remote": str(nested)},
        ):
            with self.assertRaises(ConfigError) as ctx:
                App.create(str(self.config))
        self.assertIn("互相嵌套", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
