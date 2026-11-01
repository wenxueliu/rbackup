from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from rbackup.config import load_config
from rbackup.webconfig import default_payload
from rbackup.webui import WebState, make_handler


class WebServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = self.root / "rbackup.toml"
        self.token = "test-token-123"
        self.state = WebState.create(self.config, self.token)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        self.state.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict | None = None,
        token: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, str, str]:
        headers = {}
        if token is not None:
            headers["X-RBackup-Token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"
        if origin is not None:
            headers["Origin"] = origin
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return (
                    response.status,
                    response.read().decode("utf-8"),
                    response.headers.get("Content-Type", ""),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), exc.headers.get(
                "Content-Type", ""
            )

    def test_page_requires_token(self) -> None:
        status, body, content_type = self.request("/?token=" + self.token)
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("备份配置", body)
        self.assertIn('name="rbackup-token"', body)

        status, _body, _content_type = self.request("/")
        self.assertEqual(status, 403)

    def test_config_api_requires_token(self) -> None:
        status, _body, _content_type = self.request("/api/config")
        self.assertEqual(status, 403)

        status, body, _content_type = self.request("/api/config", token=self.token)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertFalse(data["exists"])

    def test_save_config(self) -> None:
        payload = default_payload()
        payload["device"] = "web-test-device"
        payload["categories"] = [
            {
                "name": "docs",
                "path": (self.root / "docs").as_posix(),
                "excludes": [],
                "enabled": True,
            }
        ]
        status, body, _content_type = self.request(
            "/api/save",
            method="POST",
            token=self.token,
            body={"payload": payload},
        )
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertTrue(self.config.exists())
        self.assertEqual(load_config(str(self.config)).device, "web-test-device")

        status, body, _content_type = self.request("/api/config", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["payload"]["device"], "web-test-device")

    def test_invalid_payload_returns_json_error(self) -> None:
        payload = default_payload()
        payload["categories"] = []
        status, body, _content_type = self.request(
            "/api/save",
            method="POST",
            token=self.token,
            body={"payload": payload},
        )
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertFalse(data["ok"])
        self.assertIn("类别", data["error"])

    def test_bad_origin_rejected(self) -> None:
        status, body, _content_type = self.request(
            "/api/config",
            method="POST",
            token=self.token,
            origin="https://evil.example",
            body={},
        )
        self.assertEqual(status, 403)
        self.assertIn("Origin", json.loads(body)["error"])

    def test_reload(self) -> None:
        status, body, _content_type = self.request(
            "/api/reload", method="POST", token=self.token, body={}
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_browse_apis_are_routed(self) -> None:
        payload = default_payload()
        for path in (
            "/api/diff",
            "/api/upload",
            "/api/delete",
            "/api/delete-local",
            "/api/restore",
            "/api/rebaseline",
            "/api/backup",
        ):
            status, body, _content_type = self.request(
                path, method="POST", token=self.token, body={"payload": payload}
            )
            self.assertNotEqual(status, 404, f"{path} 未注册：{body}")
            self.assertFalse(json.loads(body)["ok"], body)

    def test_progress_endpoint_is_idle_initially(self) -> None:
        status, body, _content_type = self.request(
            "/api/progress", method="GET", token=self.token
        )
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertFalse(data["active"])
        self.assertEqual(data["overall"], 0)

    def test_progress_endpoint_requires_token(self) -> None:
        status, _body, _content_type = self.request("/api/progress", method="GET")
        self.assertEqual(status, 403)

    def test_audit_endpoint_returns_entries(self) -> None:
        status, body, _content_type = self.request(
            "/api/audit?limit=10", method="GET", token=self.token
        )
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["entries"], list)
        self.assertTrue(data["path"].endswith(".audit.log"))

    def test_audit_endpoint_requires_token(self) -> None:
        status, _body, _content_type = self.request("/api/audit", method="GET")
        self.assertEqual(status, 403)

    def test_config_backups_endpoint(self) -> None:
        status, body, _content_type = self.request(
            "/api/config-backups", method="GET", token=self.token
        )
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["backups"], list)

    def test_page_has_no_duplicate_function_declarations(self) -> None:
        """同名函数声明会互相覆盖，曾导致 titles.forEach is not a function。"""
        from rbackup.webpage import render_page

        page = render_page(self.token)
        script = re.search(r"<script>(.*?)</script>", page, flags=re.S)
        self.assertIsNotNone(script)
        names = re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", script.group(1))
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(duplicates, [], f"页面脚本里有重复函数声明：{duplicates}")

    def test_page_references_only_existing_element_ids(self) -> None:
        from rbackup.webpage import render_page

        page = render_page(self.token)
        script = re.search(r"<script>(.*?)</script>", page, flags=re.S).group(1)
        defined = set(re.findall(r'id="([^"]+)"', page))
        used = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', script))
        self.assertEqual(sorted(used - defined), [], "脚本引用了不存在的元素 id")


if __name__ == "__main__":
    unittest.main()
