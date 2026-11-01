from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rbackup import audit


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = self.root / "rbackup.toml"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_log_lives_next_to_config(self) -> None:
        self.assertEqual(
            audit.audit_path(self.config), self.root / "rbackup.toml.audit.log"
        )

    def test_record_appends_json_lines(self) -> None:
        audit.record(self.config, "delete", category="docs", items=["a.txt", "b.txt"])
        audit.record(self.config, "restore", category="docs", restored=1)

        entries = audit.read_entries(self.config)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["op"], "delete")
        self.assertEqual(entries[0]["items"], ["a.txt", "b.txt"])
        self.assertEqual(entries[0]["count"], 2)
        self.assertEqual(entries[1]["op"], "restore")
        self.assertTrue(entries[0]["ts"])

        raw = audit.audit_path(self.config).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw), 2)
        self.assertEqual(json.loads(raw[0])["op"], "delete")

    def test_items_are_truncated(self) -> None:
        many = [f"file-{index}.bin" for index in range(audit.MAX_ITEMS + 20)]
        audit.record(self.config, "delete", items=many)
        entry = audit.read_entries(self.config)[0]
        self.assertEqual(len(entry["items"]), audit.MAX_ITEMS)
        self.assertEqual(entry["count"], len(many))
        self.assertTrue(entry["items_truncated"])

    def test_read_skips_broken_lines(self) -> None:
        path = audit.audit_path(self.config)
        path.write_text(
            '{"op": "delete"}\n不是 JSON\n\n{"op": "upload"}\n', encoding="utf-8"
        )
        entries = audit.read_entries(self.config)
        self.assertEqual([item["op"] for item in entries], ["delete", "upload"])

    def test_limit_keeps_latest(self) -> None:
        for index in range(5):
            audit.record(self.config, "delete", category=f"c{index}")
        entries = audit.read_entries(self.config, 2)
        self.assertEqual([item["category"] for item in entries], ["c3", "c4"])

    def test_missing_log_returns_empty(self) -> None:
        self.assertEqual(audit.read_entries(self.config), [])

    def test_none_fields_are_omitted(self) -> None:
        entry = audit.record(self.config, "backup", version=None, ok=True)
        self.assertNotIn("version", entry)
        self.assertTrue(entry["ok"])


if __name__ == "__main__":
    unittest.main()
