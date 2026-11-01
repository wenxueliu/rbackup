from __future__ import annotations

import unittest

from rbackup.listing import (
    RemoteFile,
    Snapshot,
    change_counts,
    compare_local_remote,
)


def file(path: str, size: int = 1, mtime: str = "2026-10-30T00:00:00Z") -> RemoteFile:
    return RemoteFile(category="docs", path=path, size=size, mtime=mtime)


class SnapshotTests(unittest.TestCase):
    def test_digest_is_order_independent(self) -> None:
        left = Snapshot({"docs": {"a": file("a"), "b": file("b", 2)}})
        right = Snapshot({"docs": {"b": file("b", 2), "a": file("a")}})
        self.assertEqual(left.category_digest("docs"), right.category_digest("docs"))
        self.assertEqual(left.digest(), right.digest())

    def test_digest_changes_with_size_or_mtime(self) -> None:
        base = Snapshot({"docs": {"a": file("a")}})
        self.assertNotEqual(
            base.category_digest("docs"),
            Snapshot({"docs": {"a": file("a", 2)}}).category_digest("docs"),
        )
        self.assertNotEqual(
            base.category_digest("docs"),
            Snapshot(
                {"docs": {"a": file("a", 1, "2026-10-30T00:00:03Z")}}
            ).category_digest("docs"),
        )

    def test_diff(self) -> None:
        old = Snapshot(
            {
                "docs": {
                    "keep": file("keep"),
                    "change": file("change", 1),
                    "delete": file("delete"),
                }
            }
        )
        new = Snapshot(
            {
                "docs": {
                    "keep": file("keep"),
                    "change": file("change", 2),
                    "add": file("add"),
                }
            }
        )
        changes = old.diff(new)
        self.assertEqual(
            [(item.kind, item.path) for item in changes],
            [("added", "add"), ("modified", "change"), ("deleted", "delete")],
        )
        self.assertEqual(change_counts(changes), {"added": 1, "modified": 1, "deleted": 1})

    def test_counts(self) -> None:
        snapshot = Snapshot({"docs": {"a": file("a", 3), "b": file("b", 4)}})
        self.assertEqual(snapshot.counts("docs"), {"files": 2, "bytes": 7})


class CompareTests(unittest.TestCase):
    def test_local_missing(self) -> None:
        result = compare_local_remote(None, {"a": file("a")})
        self.assertTrue(result["local_missing"])
        self.assertEqual(result["remote_only"], ["a"])

    def test_compare(self) -> None:
        local = {
            "same": file("same"),
            "changed": file("changed", 1),
            "local-only": file("local-only"),
        }
        remote = {
            "same": file("same"),
            "changed": file("changed", 2),
            "remote-only": file("remote-only"),
        }
        result = compare_local_remote(local, remote)
        self.assertEqual(result["remote_only"], ["remote-only"])
        self.assertEqual(result["local_only"], ["local-only"])
        self.assertEqual([item["path"] for item in result["modified"]], ["changed"])
        self.assertEqual(result["same"], 1)

    def test_mtime_tolerance(self) -> None:
        local = {"a": file("a", 1, "2026-10-30T00:00:00Z")}
        remote = {"a": file("a", 1, "2026-10-30T00:00:01Z")}
        result = compare_local_remote(local, remote, tolerance=3)
        self.assertEqual(result["modified"], [])


if __name__ == "__main__":
    unittest.main()
