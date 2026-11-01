from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rbackup import webfiles
from rbackup.backup import run_backup
from rbackup.config import load_config
from rbackup.errors import UsageError
from rbackup.listing import load_snapshot
from rbackup.webconfig import config_to_payload

ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = Path(os.environ.get("RBACKUP_TEST_TMP", str(ROOT / ".test-tmp")))
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
DEVICE = "web-dev"


def find_rclone() -> str | None:
    env = os.environ.get("RBACKUP_RCLONE")
    if env and Path(env).exists():
        return str(Path(env))
    found = shutil.which("rclone")
    if found:
        return found
    candidates = sorted((ROOT / ".tools").glob("**/rclone.exe"))
    if candidates:
        return str(candidates[-1])
    return None


def quiet(callable_):
    """吞掉 rclone/备份的进度输出，让测试结果干净。"""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
        io.StringIO()
    ):
        return callable_()


@unittest.skipUnless(find_rclone(), "需要 rclone 才能运行端到端测试")
class WebFilesTests(unittest.TestCase):
    rclone_bin = find_rclone() or "rclone"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rbackup-wf-", dir=TEST_TMP_ROOT)
        self.root = Path(self._tmp.name)
        self.local = self.root / "local" / "docs"
        (self.local / "sub").mkdir(parents=True)
        self.remote_root = self.root / "remote"
        self.remote_root.mkdir()
        self.rclone_conf = self.root / "rclone.conf"
        self.config = self.root / "rbackup.toml"

        (self.local / "a.txt").write_bytes(b"hello v1")
        (self.local / "sub" / "b.bin").write_bytes(b"binary-v1")

        password = self._rclone("obscure", "testpass").stdout.strip()
        password2 = self._rclone("obscure", "testsalt").stdout.strip()
        self._rclone(
            "config",
            "create",
            "crypt",
            "crypt",
            f"remote={self.remote_root.as_posix()}",
            f"password={password}",
            f"password2={password2}",
            "filename_encryption=standard",
            "directory_name_encryption=true",
        )
        self._rclone("lsd", "crypt:")

        self.config.write_text(
            f"""
device = "{DEVICE}"
remote = "crypt"
rclone_bin = "{Path(self.rclone_bin).as_posix()}"
rclone_config = "{self.rclone_conf.as_posix()}"
poll_interval = 1
transfers = 2
checkers = 2
retries = 1

[categories.docs]
path = "{self.local.as_posix()}"
excludes = []
enabled = true
""",
            encoding="utf-8",
        )
        self.addCleanup(self._tmp.cleanup)

        self.payload = config_to_payload(load_config(str(self.config)))
        self.app = webfiles.app_from_payload(self.payload, self.config)
        quiet(lambda: run_backup(self.app, ["docs"], json_output=False))

    # ---------- helpers ----------

    def _rclone(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [self.rclone_bin, "--config", str(self.rclone_conf), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if check and completed.returncode != 0:
            self.fail(
                f"rclone {' '.join(args)} 失败：{completed.returncode}\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        return completed

    def fresh_app(self):
        return webfiles.app_from_payload(self.payload, self.config)

    def remote_files(self, suffix: str = "") -> list[str]:
        target = f"crypt:{DEVICE}" + (f"/{suffix}" if suffix else "")
        output = self._rclone("lsf", "-R", target).stdout
        return [line for line in output.splitlines() if line]

    def remote_cat(self, path: str) -> str:
        return self._rclone("cat", f"crypt:{DEVICE}/{path}").stdout

    # ---------- 对比 ----------

    def test_diff_reports_each_state(self) -> None:
        (self.local / "a.txt").write_bytes(b"hello v2 changed")
        (self.local / "only-local.txt").write_bytes(b"new")
        (self.local / "sub" / "b.bin").unlink()

        data = webfiles.compute_diff(self.fresh_app(), ["docs"])
        self.assertTrue(data["ok"])
        category = data["categories"][0]
        states = {row["path"]: row["state"] for row in category["files"]}
        self.assertEqual(states["a.txt"], "modified")
        self.assertEqual(states["only-local.txt"], "local_only")
        self.assertEqual(states["sub/b.bin"], "remote_only")
        self.assertEqual(category["counts"]["modified"], 1)
        self.assertEqual(category["counts"]["local_only"], 1)
        self.assertEqual(category["counts"]["remote_only"], 1)

    def test_diff_lists_directories_both_sides(self) -> None:
        data = webfiles.compute_diff(self.fresh_app(), ["docs"])
        category = data["categories"][0]
        dirs = {row["path"]: row for row in category["dirs"]}
        self.assertIn("sub", dirs)
        self.assertTrue(dirs["sub"]["in_a"])
        self.assertTrue(dirs["sub"]["in_b"])

        (self.local / "newdir").mkdir()
        (self.local / "newdir" / "x.txt").write_bytes(b"x")
        data = webfiles.compute_diff(self.fresh_app(), ["docs"])
        dirs = {row["path"]: row for row in data["categories"][0]["dirs"]}
        self.assertTrue(dirs["newdir"]["in_a"])
        self.assertFalse(dirs["newdir"]["in_b"])

    # ---------- 上传 ----------

    def test_upload_file_and_directory(self) -> None:
        (self.local / "new.txt").write_bytes(b"new-file")
        (self.local / "newdir").mkdir()
        (self.local / "newdir" / "x.txt").write_bytes(b"x-content")

        result = webfiles.upload_paths(
            self.fresh_app(), "docs", ["new.txt", "newdir"]
        )
        self.assertEqual(result["uploaded"], 2, result)
        self.assertEqual(result["failed"], 0, result)
        self.assertTrue(result["state_stale"])
        files = self.remote_files("docs")
        self.assertIn("new.txt", files)
        self.assertIn("newdir/x.txt", files)
        self.assertEqual(self.remote_cat("docs/newdir/x.txt"), "x-content")

    def test_upload_keeps_old_content_in_versions(self) -> None:
        (self.local / "a.txt").write_bytes(b"hello v2")
        result = webfiles.upload_paths(self.fresh_app(), "docs", ["a.txt"])
        self.assertEqual(result["uploaded"], 1, result)
        version_id = result["version_id"]

        self.assertEqual(self.remote_cat("docs/a.txt"), "hello v2")
        old = self._rclone(
            "cat", f"crypt:_versions/{DEVICE}/{version_id}/docs/a.txt"
        ).stdout
        self.assertEqual(old, "hello v1")

    def test_upload_nested_file_keeps_versions_under_same_relative_dir(self) -> None:
        (self.local / "sub" / "b.bin").write_bytes(b"binary-v2")
        result = webfiles.upload_paths(self.fresh_app(), "docs", ["sub/b.bin"])
        self.assertEqual(result["uploaded"], 1, result)
        version_id = result["version_id"]

        self.assertEqual(self.remote_cat("docs/sub/b.bin"), "binary-v2")
        old = self._rclone(
            "cat", f"crypt:_versions/{DEVICE}/{version_id}/docs/sub/b.bin"
        ).stdout
        self.assertEqual(old, "binary-v1")

    def test_upload_rejects_missing_source(self) -> None:
        result = webfiles.upload_paths(self.fresh_app(), "docs", ["nope.txt"])
        self.assertEqual(result["uploaded"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertIn("不存在", result["results"][0]["error"])

    # ---------- 删除 ----------

    def test_delete_file_and_directory(self) -> None:
        app = self.fresh_app()
        result = webfiles.delete_paths(app, "docs", ["a.txt"])
        self.assertEqual(result["deleted"], 1, result)
        self.assertNotIn("a.txt", self.remote_files("docs"))

        result = webfiles.delete_paths(self.fresh_app(), "docs", ["sub"])
        self.assertEqual(result["deleted"], 1, result)
        files = self.remote_files("docs")
        self.assertFalse([name for name in files if name.startswith("sub")])

    def test_delete_missing_reports_error(self) -> None:
        result = webfiles.delete_paths(self.fresh_app(), "docs", ["missing.txt"])
        self.assertEqual(result["failed"], 1)
        self.assertIn("不存在", result["results"][0]["error"])

    def test_delete_does_not_create_versions(self) -> None:
        webfiles.delete_paths(self.fresh_app(), "docs", ["a.txt"])
        output = self._rclone("lsf", f"crypt:_versions", check=False).stdout
        self.assertEqual([line for line in output.splitlines() if line], [])

    # ---------- 删除 A ----------

    def test_delete_local_file_keeps_remote_copy(self) -> None:
        result = webfiles.delete_local_paths(self.fresh_app(), "docs", ["a.txt"])
        self.assertEqual(result["deleted"], 1, result)
        self.assertFalse(result["state_stale"])
        self.assertFalse((self.local / "a.txt").exists())
        # B 不受影响
        self.assertIn("a.txt", self.remote_files("docs"))
        self.assertEqual(self.remote_cat("docs/a.txt"), "hello v1")

    def test_delete_local_directory(self) -> None:
        result = webfiles.delete_local_paths(self.fresh_app(), "docs", ["sub"])
        self.assertEqual(result["deleted"], 1, result)
        self.assertFalse((self.local / "sub").exists())
        self.assertTrue((self.local / "a.txt").exists())
        self.assertIn("sub/b.bin", self.remote_files("docs"))

    def test_delete_local_dry_run_keeps_files(self) -> None:
        result = webfiles.delete_local_paths(
            self.fresh_app(), "docs", ["a.txt"], dry_run=True
        )
        self.assertEqual(result["deleted"], 1)
        self.assertTrue(result["dry_run"])
        self.assertTrue((self.local / "a.txt").exists())

    def test_delete_local_missing_reports_error(self) -> None:
        result = webfiles.delete_local_paths(self.fresh_app(), "docs", ["nope.txt"])
        self.assertEqual(result["failed"], 1)
        self.assertIn("不存在", result["results"][0]["error"])

    def test_delete_local_rejects_escape(self) -> None:
        with self.assertRaises(UsageError):
            webfiles.delete_local_paths(self.fresh_app(), "docs", ["../outside.txt"])

    def test_delete_local_refuses_symlink_escape(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        victim = outside / "victim.txt"
        victim.write_bytes(b"do not delete")
        link = self.local / "link.txt"
        try:
            link.symlink_to(victim)
        except (OSError, NotImplementedError):
            self.skipTest("当前环境无法创建符号链接")
        result = webfiles.delete_local_paths(self.fresh_app(), "docs", ["link.txt"])
        # 链接本身指向 A 之外，应被拒绝
        self.assertEqual(result["failed"], 1, result)
        self.assertTrue(victim.exists())

    # ---------- 基线 ----------

    def test_rebaseline_clears_drift(self) -> None:
        webfiles.delete_paths(self.fresh_app(), "docs", ["a.txt"])

        app = self.fresh_app()
        snapshot = load_snapshot(app.rclone, app.layout)
        state = app.state.load()
        self.assertIsNotNone(state)
        self.assertNotEqual(
            state.category_digest("docs"), snapshot.category_digest("docs")
        )

        result = webfiles.rebaseline(app, ["docs"])
        self.assertIn("docs", result["updated"])

        app = self.fresh_app()
        state = app.state.load()
        snapshot = load_snapshot(app.rclone, app.layout)
        self.assertEqual(
            state.category_digest("docs"), snapshot.category_digest("docs")
        )
        self.assertEqual(state.status, "ok")

    # ---------- 路径校验 ----------

    def test_rejects_unsafe_paths(self) -> None:
        for bad in ["../escape", "/absolute", "C:/windows", ""]:
            with self.assertRaises(UsageError, msg=bad):
                webfiles.clean_paths([bad])
        with self.assertRaises(UsageError):
            webfiles.clean_paths("not-a-list")
        with self.assertRaises(UsageError):
            webfiles.clean_paths([])

    def test_accepts_nested_relative_paths(self) -> None:
        cleaned = webfiles.clean_paths(["./sub/b.bin", "sub//b.bin", "sub\\b.bin"])
        self.assertEqual(cleaned, ["sub/b.bin"])


if __name__ == "__main__":
    unittest.main()
