import base64
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import wgvps_web as web


class Portal(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        Path(folder.name, "password").write_bytes(b"test-secret")
        env = patch.dict(os.environ, WEB_ADDRESS="10.0.0.1", WEB_NETWORK="10.0.0.0/24",
                         CREDENTIALS_DIRECTORY=folder.name)
        env.start()
        self.addCleanup(env.stop)

    def request(self, path, fields=None, admin=False, binary=False, **kwargs):
        body = urlencode(fields or {}).encode()
        env = {"PATH_INFO": path, "REQUEST_METHOD": "POST" if fields is not None else "GET",
               "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body)),
               "wsgi.input": io.BytesIO(body), "HTTP_HOST": "10.0.0.1:8443", "REMOTE_ADDR": "10.0.0.9"}
        if admin:
            env["HTTP_AUTHORIZATION"] = "Basic " + base64.b64encode(b"admin:test-secret").decode()
        env.update(kwargs)
        status = []
        payload = web.application(env, lambda s, headers: status.append(s))[0]
        return int(status[0][:3]), payload if binary else payload.decode()

    def test_access(self):
        with patch.object(web, "manager") as manager:
            self.assertEqual(self.request("/admin")[0], 401)
            self.assertEqual(self.request("/", REMOTE_ADDR="203.0.113.2")[0], 403)
            self.assertEqual(self.request("/", HTTP_HOST="other.local")[0], 403)
            self.assertEqual(self.request("/admin", {"user": "user02"}, admin=True)[0], 403)
            self.assertEqual(self.request("/")[0], 200)
            manager.assert_not_called()

    def test_issue_and_download(self):
        with patch.object(web, "manager", return_value=b"user02 enabled global") as manager:
            status, html = self.request("/admin", admin=True)
            csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', html)[1]
            manager.return_value = b"a" * 32
            status, html = self.request("/admin", {"csrf": csrf, "action": "issue", "user": "user02"},
                                        admin=True)
            self.assertEqual(status, 200)
            self.assertIn("https://10.0.0.1:8443/#" + "a" * 32, html)
            manager.assert_called_with("issue", "user02")
            manager.return_value = json.dumps({"name": "user02", "profiles": {
                "global": "full profile", "proxy": "proxy profile"}}).encode()
            with patch.object(web.subprocess, "run") as qr:
                qr.return_value.stdout = b"qr"
                status, html = self.request("/", {"code": "a" * 32})
            self.assertEqual(status, 200)
            self.assertIn('download="user02-global.conf"', html)
            self.assertIn('download="user02-proxy.conf"', html)
            self.assertEqual(qr.call_count, 2)

    def test_admin_direct_export(self):
        import zipfile
        bundle = {"name": "user25", "profiles": {"global": "full", "proxy": "split"}}
        with patch.object(web, "manager", return_value=b"user25 enabled global") as manager:
            _, html = self.request("/admin", admin=True)
            csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', html)[1]
            form = {"csrf": csrf, "action": "bundle", "user": "user25"}
            manager.return_value = json.dumps(bundle).encode()
            with patch.object(web.subprocess, "run") as qr:
                qr.return_value.stdout = b"png"
                status, html = self.request("/admin", form, admin=True)
            self.assertEqual(status, 200)
            self.assertIn('download="user25-global.conf"', html)
            self.assertIn('download="user25-proxy.conf"', html)
            manager.assert_called_with("bundle", "user25")
            form = {"csrf": csrf, "action": "archive"}
            self.assertEqual(self.request("/admin", form)[0], 401)
            self.assertEqual(self.request("/admin", form, admin=True, HTTP_ORIGIN="https://other")[0], 403)
            manager.return_value = json.dumps([bundle]).encode()
            status, payload = self.request("/admin", form, admin=True, binary=True)
            self.assertEqual(status, 200)
            manager.assert_called_with("bundles")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertEqual(archive.read("user25/user25-global.conf"), b"full")
                self.assertEqual(archive.read("user25/user25-proxy.conf"), b"split")
