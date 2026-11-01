from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from rbackup.config import Category, Config
from rbackup.rclone import Rclone, RcloneError, parse_progress


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


class ProgressParseTests(unittest.TestCase):
    def test_parses_percent_bytes_speed_eta(self) -> None:
        info = parse_progress("12.345 MiB / 41.454 MiB, 30%, 6.005 MiB/s, ETA 5s")
        self.assertIsNotNone(info)
        self.assertEqual(info["percent"], 30)
        self.assertAlmostEqual(info["total_bytes"], 41.454 * 1024**2, places=2)
        self.assertAlmostEqual(info["speed"], 6.005 * 1024**2, places=2)
        self.assertEqual(info["eta"], "5s")

    def test_handles_concatenated_segments(self) -> None:
        """rclone 写管道时各段之间没有分隔符，必须取最后一段。"""
        text = (
            "7.059 MiB / 41.454 MiB, 17%, 0 B/s, ETA -"
            "14.059 MiB / 41.454 MiB, 34%, 10.059 MiB/s, ETA 2s"
            "41.454 MiB / 41.454 MiB, 100%, 10.015 MiB/s, ETA 0s"
        )
        info = parse_progress(text)
        self.assertEqual(info["percent"], 100)

    def test_done_without_eta_has_no_eta(self) -> None:
        info = parse_progress("41.454 MiB / 41.454 MiB, 100%, 0 B/s, ETA -")
        self.assertEqual(info["percent"], 100)
        self.assertIsNone(info["eta"])

    def test_returns_none_without_progress(self) -> None:
        self.assertIsNone(parse_progress("2026/01/01 NOTICE: something happened"))

    @patch("rbackup.rclone.subprocess.Popen")
    def test_copyto_streams_progress_to_callback(self, popen) -> None:
        class FakeStdout:
            def __init__(self) -> None:
                self.chunks = [
                    b"5.000 MiB / 10.000 MiB, 50%, 2.000 MiB/s, ETA 2s",
                    b"10.000 MiB / 10.000 MiB, 100%, 2.000 MiB/s, ETA 0s",
                    b"",
                ]

            def read1(self, _size: int) -> bytes:
                return self.chunks.pop(0) if self.chunks else b""

        class FakeStderr:
            def read(self) -> bytes:
                return b""

        class FakeProc:
            returncode = 0

            def __init__(self) -> None:
                self.stdout = FakeStdout()
                self.stderr = FakeStderr()

            def poll(self):
                return 0

            def wait(self) -> int:
                return 0

            def kill(self) -> None:
                pass

        popen.return_value = FakeProc()
        seen: list[int] = []
        rclone = Rclone(make_config())
        rclone.copyto("C:/docs/a.bin", "crypt:dev/docs/a.bin", on_progress=lambda i: seen.append(i["percent"]))
        self.assertEqual(seen, [50, 100])


if __name__ == "__main__":
    unittest.main()
