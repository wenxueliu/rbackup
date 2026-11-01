from __future__ import annotations

import json
import unittest

from rbackup.layout import Layout
from rbackup.rclone import RcloneError
from rbackup.state import State, StateError, StateStore


class FakeRclone:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}
        self.inputs: dict[str, bytes] = {}

    def cat(self, path: str) -> str:
        if path not in self.objects:
            raise RcloneError("missing", returncode=3)
        return self.objects[path]

    def rcat(self, path: str, data: bytes, *, timeout: float = 120) -> None:
        self.objects[path] = data.decode("utf-8")
        self.inputs[path] = data


class StateTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        state = State(
            device="dev",
            remote="crypt",
            run_id="20261030T235653Z-a1b2c3",
            version_id="20261030T235653Z-a1b2c3",
            started_at="2026-10-30T23:56:53Z",
            finished_at="2026-10-30T23:56:54Z",
            status="ok",
            categories={
                "docs": {
                    "status": "ok",
                    "files": 2,
                    "bytes": 30,
                    "digest": "abc",
                }
            },
        )
        restored = State.from_dict(json.loads(state.to_bytes()))
        self.assertEqual(restored.device, "dev")
        self.assertEqual(restored.category_digest("docs"), "abc")
        self.assertEqual(restored.summary()["files"], 2)

    def test_bad_schema(self) -> None:
        with self.assertRaises(StateError):
            State.from_dict(
                {
                    "schema": 99,
                    "device": "d",
                    "remote": "r",
                    "run_id": "x",
                    "version_id": "x",
                    "started_at": "y",
                }
            )

    def test_store_roundtrip(self) -> None:
        fake = FakeRclone()
        layout = Layout("crypt", "dev")
        store = StateStore(fake, layout)  # type: ignore[arg-type]
        self.assertIsNone(store.load())
        state = State(
            device="dev",
            remote="crypt",
            run_id="20261030T235653Z-a1b2c3",
            version_id="20261030T235653Z-a1b2c3",
            started_at="2026-10-30T23:56:53Z",
            status="ok",
        )
        store.save(state)
        loaded = store.load()
        assert loaded is not None
        self.assertEqual(loaded.device, "dev")
        self.assertEqual(
            fake.inputs[layout.state_file][:1],
            b"{",
        )

    def test_device_mismatch(self) -> None:
        fake = FakeRclone()
        layout = Layout("crypt", "dev")
        fake.objects[layout.state_file] = json.dumps(
            {
                "schema": 1,
                "device": "other",
                "remote": "crypt",
                "run_id": "x",
                "version_id": "x",
                "started_at": "y",
                "categories": {},
            }
        )
        store = StateStore(fake, layout)  # type: ignore[arg-type]
        with self.assertRaises(StateError):
            store.load()


if __name__ == "__main__":
    unittest.main()
