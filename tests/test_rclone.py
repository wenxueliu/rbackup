from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from rbackup.config import Category, Config
from rbackup.rclone import Rclone, RcloneError


def make_config(**overrides: object) -> Config:
    data = dict(
        path=Path("C:/config.toml"),
        device="dev",
        remote="crypt",
        categories={"docs": Category("docs", Path("C:/docs"))},
        rclone_bin="rclone",
        rclone_config=Path("C:/rclone.conf"),
    )
    data.update(overrides)
    return Config(**data)  # type: ignore[arg-type]


class RcloneCommandTests(unittest.TestCase):
    @patch("rbackup.rclone.subprocess.run")
    def test_copy_uses_backup_dir_and_never_sync(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        rclone = Rclone(make_config())
        rclone.copy(
            "C:/docs",
            "crypt:dev/docs",
            backup_dir="crypt:_versions/dev/v1/docs",
            filters=("**/.git/**",),
        )
        argv = run.call_args.args[0]
        self.assertIn("copy", argv)
        self.assertNotIn("sync", argv)
        self.assertIn("--backup-dir", argv)
        self.assertIn("crypt:_versions/dev/v1/docs", argv)
        self.assertIn("--exclude=**/.git/**", argv)
        self.assertIn("crypt:dev/docs", argv)
        self.assertTrue(any("--config" == item for item in argv))

    @patch("rbackup.rclone.subprocess.run")
    def test_rcat_streams_input(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        rclone = Rclone(make_config())
        rclone.rcat("crypt:_state/dev/last-run.json", b'{"a":1}')
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["input"], b'{"a":1}')
        argv = run.call_args.args[0]
        self.assertIn("rcat", argv)
        self.assertIn("--size", argv)
        self.assertIn("7", argv)

    @patch("rbackup.rclone.subprocess.run")
    def test_failure_raises_with_stderr(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 2, b"", b"boom")
        rclone = Rclone(make_config())
        with self.assertRaises(RcloneError) as ctx:
            rclone.run(["lsjson", "crypt:dev"])
        self.assertEqual(ctx.exception.returncode, 2)
        self.assertIn("boom", str(ctx.exception))

    @patch("rbackup.rclone.subprocess.run")
    def test_remote_type(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [], 0, b"[crypt]\ntype = crypt\npassword = secret\n", b""
        )
        rclone = Rclone(make_config())
        self.assertEqual(rclone.remote_type("crypt"), "crypt")

    @patch("rbackup.rclone.subprocess.run")
    def test_remote_type_error_does_not_echo_config(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [], 1, b"password = should-not-leak", b""
        )
        rclone = Rclone(make_config())
        with self.assertRaises(RcloneError) as ctx:
            rclone.remote_type("crypt")
        self.assertNotIn("should-not-leak", str(ctx.exception))

    @patch("rbackup.rclone.subprocess.run")
    def test_lsjson_parses_list_and_single(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [], 0, b'[{"Path":"a.txt","Size":3,"IsDir":false}]', b""
        )
        rclone = Rclone(make_config())
        rows = rclone.list_files("crypt:dev/docs")
        self.assertEqual(rows[0]["Path"], "a.txt")

        run.return_value = subprocess.CompletedProcess(
            [], 0, b'{"Path":"a.txt","Size":3,"IsDir":false}', b""
        )
        self.assertEqual(rclone.stat("crypt:dev/docs/a.txt")["Size"], 3)


if __name__ == "__main__":
    unittest.main()
