from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = Path(os.environ.get("RBACKUP_TEST_TMP", str(ROOT / ".test-tmp")))
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
DEVICE = "test-dev"


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


@unittest.skipUnless(find_rclone(), "需要 rclone 才能运行端到端测试")
class IntegrationTests(unittest.TestCase):
    rclone_bin = find_rclone() or "rclone"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rbackup-it-", dir=TEST_TMP_ROOT)
        self.root = Path(self._tmp.name)
        self.local = self.root / "local" / "docs"
        (self.local / "sub").mkdir(parents=True)
        self.remote_root = self.root / "remote"
        self.remote_root.mkdir()
        self.rclone_conf = self.root / "rclone.conf"
        self.config = self.root / "rbackup.toml"
        self.staging = self.root / "staging"
        self.staging.mkdir()

        (self.local / "a.txt").write_bytes(b"hello v1")
        (self.local / "sub" / "b.bin").write_bytes(b"binary-v1")

        self._rclone("config", "create", "base", "local")
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
excludes = ["**/.git/**"]
enabled = true
""",
            encoding="utf-8",
        )
        self.addCleanup(self._tmp.cleanup)

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

    def cli(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "rbackup",
                "--config",
                str(self.config),
                *args,
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )

    def cli_json(self, *args: str, timeout: float = 120) -> tuple[int, dict, str]:
        completed = self.cli(*args, timeout=timeout)
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                f"CLI {' '.join(args)} 未返回 JSON：{exc}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )
        return completed.returncode, data, completed.stderr

    def remote_ls(self, suffix: str = "") -> list[str]:
        target = f"crypt:{DEVICE}" + (f"/{suffix}" if suffix else "")
        output = self._rclone("lsf", "-R", target).stdout
        return [line for line in output.splitlines() if line]

    def remote_cat(self, path: str) -> str:
        return self._rclone("cat", f"crypt:{DEVICE}/{path}").stdout

    def write_remote(self, relative: str, data: bytes) -> None:
        staged = self.staging / "payload.bin"
        staged.write_bytes(data)
        self._rclone(
            "copyto",
            str(staged),
            f"crypt:{DEVICE}/docs/{relative}",
        )

    def state(self) -> dict:
        raw = self._rclone("cat", f"crypt:_state/{DEVICE}/last-run.json").stdout
        return json.loads(raw)

    def versions(self) -> list[dict]:
        code, data, stderr = self.cli_json("versions", "--json")
        self.assertEqual(code, 0, stderr)
        return data["versions"]

    # ---------- tests ----------

    def test_backup_encrypted_remote_and_state(self) -> None:
        completed = self.cli("backup")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        listed = self.remote_ls()
        self.assertIn("docs/a.txt", listed)
        self.assertIn("docs/sub/b.bin", listed)

        state = self.state()
        self.assertEqual(state["device"], DEVICE)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["categories"]["docs"]["files"], 2)
        self.assertGreater(len(state["categories"]["docs"]["digest"]), 20)

        physical_names = [path.name for path in self.remote_root.rglob("*")]
        self.assertNotIn("a.txt", physical_names)
        self.assertNotIn("docs", physical_names)

        # 本地不产生密文/镜像
        self.assertEqual(
            sorted(path.relative_to(self.local).as_posix() for path in self.local.rglob("*") if path.is_file()),
            ["a.txt", "sub/b.bin"],
        )

    def test_web_check_uses_local_b(self) -> None:
        from rbackup.config import load_config
        from rbackup.webconfig import config_to_payload
        from rbackup.webui import WebState

        state = WebState.create(self.config, "test-token")
        payload = config_to_payload(load_config(str(self.config)))
        result = state.check(payload)
        self.assertTrue(result["passed"], result["checks"])
        self.assertEqual(result["b_path"], str(self.remote_root.resolve()))
        config_check = next(
            item for item in result["checks"] if item["name"] == "config"
        )
        self.assertEqual(config_check["detail"], str(self.config.resolve()))

    def test_doctor_detects_local_b(self) -> None:
        completed = self.cli("doctor")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("b_local", completed.stdout)
        self.assertIn(str(self.remote_root), completed.stdout)
        self.assertIn("A/B 目录不嵌套", completed.stdout)

    def test_unicode_and_spaces_in_names(self) -> None:
        nested = self.local / "子 目录"
        nested.mkdir()
        (nested / "文件 名.txt").write_bytes(b"unicode ok")
        self.assertEqual(self.cli("backup").returncode, 0)
        self.assertIn("docs/子 目录/文件 名.txt", self.remote_ls())

        destination = self.root / "restore-unicode" / "文件 名.txt"
        restored = self.cli(
            "restore", "docs", "子 目录/文件 名.txt", "--dest", str(destination)
        )
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(destination.read_bytes(), b"unicode ok")

    def test_versioning_and_copy_does_not_delete(self) -> None:
        self.assertEqual(self.cli("backup").returncode, 0)
        (self.local / "a.txt").write_bytes(b"hello v2 longer")
        self.assertEqual(self.cli("backup").returncode, 0)

        versions = self.versions()
        self.assertEqual(len(versions), 1)
        version_id = versions[0]["version_id"]
        self.assertEqual(
            self._rclone(
                "cat", f"crypt:_versions/{DEVICE}/{version_id}/docs/a.txt"
            ).stdout,
            "hello v1",
        )
        self.assertEqual(self.remote_cat("docs/a.txt"), "hello v2 longer")

        (self.local / "sub" / "b.bin").unlink()
        code, diff, stderr = self.cli_json("diff", "--json")
        self.assertEqual(code, 0, stderr)
        self.assertIn("sub/b.bin", diff["categories"]["docs"]["remote_only"])

        backed_up = self.cli("backup", "--verify")
        self.assertEqual(backed_up.returncode, 0, backed_up.stdout + backed_up.stderr)
        self.assertIs(self.state()["categories"]["docs"]["verified"], True)
        self.assertEqual(self.remote_cat("docs/sub/b.bin"), "binary-v1")

        verified = self.cli("verify", "--one-way")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_existing_remote_without_state_requires_force(self) -> None:
        self.write_remote("a.txt", b"preexisting remote")
        refused = self.cli("backup")
        self.assertEqual(refused.returncode, 3, refused.stdout + refused.stderr)
        self.assertEqual(self.remote_cat("docs/a.txt"), "preexisting remote")

        forced = self.cli("backup", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(self.remote_cat("docs/a.txt"), "hello v1")
        version_id = self.versions()[0]["version_id"]
        self.assertEqual(
            self._rclone(
                "cat", f"crypt:_versions/{DEVICE}/{version_id}/docs/a.txt"
            ).stdout,
            "preexisting remote",
        )

    def test_remote_drift_requires_force_and_is_versioned(self) -> None:
        self.assertEqual(self.cli("backup").returncode, 0)
        before = self.state()
        self.write_remote("a.txt", b"remote changed")
        drift = self.cli("backup")
        self.assertEqual(drift.returncode, 3, drift.stdout + drift.stderr)
        self.assertEqual(self.state()["version_id"], before["version_id"])

        checked = self.cli("status", "--check")
        self.assertEqual(checked.returncode, 3, checked.stdout + checked.stderr)

        forced = self.cli("backup", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(self.remote_cat("docs/a.txt"), "hello v1")
        versions = self.versions()
        self.assertEqual(len(versions), 1)
        version_id = versions[0]["version_id"]
        self.assertEqual(
            self._rclone(
                "cat", f"crypt:_versions/{DEVICE}/{version_id}/docs/a.txt"
            ).stdout,
            "remote changed",
        )

    def test_restore_current_and_version(self) -> None:
        self.assertEqual(self.cli("backup").returncode, 0)
        (self.local / "a.txt").write_bytes(b"version two")
        self.assertEqual(self.cli("backup").returncode, 0)
        version_id = self.versions()[0]["version_id"]

        current_dest = self.root / "restore" / "a.txt"
        restored = self.cli("restore", "docs", "a.txt", "--dest", str(current_dest))
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(current_dest.read_bytes(), b"version two")

        old_dest = self.root / "restore-old" / "a.txt"
        restored = self.cli(
            "restore",
            "docs",
            "a.txt",
            "--version",
            version_id,
            "--dest",
            str(old_dest),
        )
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(old_dest.read_bytes(), b"hello v1")

        no_force = self.cli("restore", "docs", "a.txt", "--dest", str(current_dest))
        self.assertEqual(no_force.returncode, 2)
        with_force = self.cli(
            "restore", "docs", "a.txt", "--dest", str(current_dest), "--force"
        )
        self.assertEqual(with_force.returncode, 0, with_force.stderr)

        directory = self.root / "restore-dir"
        restored = self.cli("restore", "docs", "--dest", str(directory))
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual((directory / "sub" / "b.bin").read_bytes(), b"binary-v1")

    def test_watch_reports_remote_change(self) -> None:
        self.assertEqual(self.cli("backup").returncode, 0)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "rbackup",
                "--config",
                str(self.config),
                "watch",
                "--json",
                "--interval",
                "1",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self.addCleanup(self._stop_process, process)
        events: queue.Queue[str] = queue.Queue()

        def read_lines() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                events.put(line)

        threading.Thread(target=read_lines, daemon=True).start()
        baseline = json.loads(events.get(timeout=20))
        self.assertEqual(baseline["event"], "baseline")
        self.assertEqual(baseline["files"], 2)

        self.write_remote("watch-new.txt", b"from B")
        deadline = time.time() + 20
        batch = None
        while time.time() < deadline:
            event = json.loads(events.get(timeout=20))
            if event.get("event") == "batch":
                batch = event
                break
        self.assertIsNotNone(batch)
        assert batch is not None
        paths = {(item["category"], item["path"], item["kind"]) for item in batch["changes"]}
        self.assertIn(("docs", "watch-new.txt", "added"), paths)

    def test_prune_keeps_newest_versions(self) -> None:
        self.assertEqual(self.cli("backup").returncode, 0)
        (self.local / "a.txt").write_bytes(b"second version")
        self.assertEqual(self.cli("backup").returncode, 0)
        (self.local / "a.txt").write_bytes(b"third version longer")
        self.assertEqual(self.cli("backup").returncode, 0)
        self.assertEqual(len(self.versions()), 2)

        plan = self.cli("prune", "--keep", "1", "--json")
        self.assertEqual(plan.returncode, 0, plan.stderr)
        plan_data = json.loads(plan.stdout)
        self.assertEqual(plan_data["deleted"], [])
        self.assertEqual(len(self.versions()), 2)

        executed = self.cli("prune", "--keep", "1", "--yes", "--json")
        self.assertEqual(executed.returncode, 0, executed.stderr)
        data = json.loads(executed.stdout)
        self.assertEqual(len(data["deleted"]), 1)
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(self.remote_cat("docs/a.txt"), "third version longer")

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if process.stdout is not None:
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
