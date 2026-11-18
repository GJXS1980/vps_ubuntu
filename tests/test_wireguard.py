"""Exercise the management workflow in a temporary directory with a simulated wg."""
import contextlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("wgvps", Path(__file__).resolve().parents[1] /
                                             "bin/wgvps-users.py")
wg = importlib.util.module_from_spec(spec)
if sys.platform == "win32":
    with patch.dict(sys.modules, fcntl=MagicMock()):
        spec.loader.exec_module(wg)
else:
    spec.loader.exec_module(wg)


class Workflow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        paths = {key: root / getattr(wg, key).name for key in ("CONF", "LEGACY", "STATE", "PENDING", "LIVE")}
        mapping = patch.multiple(wg, **paths)
        mapping.start()
        self.addCleanup(mapping.stop)
        counter = itertools.count()
        def fake(*args, data=None):
            if args == ("wg", "pubkey"):
                return "pub-" + data.strip()
            if args in (("wg", "genkey"), ("wg", "genpsk")):
                return str(next(counter))
            raise AssertionError(args)
        runner = patch.object(wg, "run", side_effect=fake)
        runner.start()
        self.addCleanup(runner.stop)
        wg.CONF.write_text("[Interface]\nAddress = 10.66.77.1/24, fd42:66:77::1/64\n"
                           "ListenPort = 51820\nPrivateKey = srv\n[Peer]\nPublicKey = pub-old\n"
                           "PresharedKey = secret\nAllowedIPs = " + wg.addresses("user01"))
        wg.LEGACY.write_text("[Interface]\nPrivateKey = old\nAddress = " + wg.addresses("user01")
                             + "\n[Peer]\nPublicKey = pub-srv\nPresharedKey = secret\n"
                             "Endpoint = 192.0.2.1:51820\n")

    def cmd(self, command, user="user02", mode="proxy", count=25):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            wg.manage(SimpleNamespace(command=command, endpoint="192.0.2.1", user=user, mode=mode, count=count))
        return stream.getvalue()

    def test_lifecycle(self):
        self.cmd("init")
        users = json.loads(wg.STATE.read_text())["users"]
        for field in ("public", "private", "psk"):
            self.assertEqual(len({user[field] for user in users.values()}), 25)
        self.assertEqual(len({wg.addresses(u) for u in users}), 25)
        self.assertEqual(users["user01"]["private"], "old")
        self.assertEqual(wg.CONF.read_text().count("[Peer]"), 25)
        other = self.cmd("export", "user25")
        initial = self.cmd("export")
        self.cmd("mode")
        proxy = self.cmd("export")
        self.assertIn("AllowedIPs = 10.66.77.1/32", proxy)
        self.assertNotIn("DNS =", proxy)
        with patch.object(wg.subprocess, "run") as qr:
            self.cmd("qr")
            self.assertEqual(qr.call_args.kwargs["input"], proxy)
        self.cmd("disable")
        self.assertNotIn("# user02\n", wg.CONF.read_text())
        with self.assertRaises(ValueError):
            self.cmd("export")
        self.cmd("rotate")
        self.cmd("init")
        self.assertIn("user02 disabled proxy", self.cmd("list"))
        self.cmd("enable")
        self.cmd("mode", mode="global")
        rotated = self.cmd("export")
        self.assertNotEqual(wg.section(initial)["Interface"]["PrivateKey"],
                            wg.section(rotated)["Interface"]["PrivateKey"])
        self.assertNotEqual(wg.section(initial)["Peer"]["PresharedKey"],
                            wg.section(rotated)["Peer"]["PresharedKey"])
        self.assertEqual(self.cmd("export", "user25"), other)
        self.assertIn("AllowedIPs = 0.0.0.0/0, ::/0", rotated)

    def test_retry(self):
        self.cmd("init")
        wg.LIVE.touch()
        with patch.object(wg, "run", side_effect=["stripped config", OSError("sync failed")]) as run:
            with self.assertRaises(OSError):
                self.cmd("disable")
            self.assertEqual(run.call_args.args, ("wg", "syncconf", "wgvps", "/dev/stdin"))
            self.assertEqual(run.call_args.kwargs["data"], "stripped config\n")
        self.assertTrue(wg.PENDING.exists())
        with patch.object(wg, "run", side_effect=["stripped config", ""]):
            self.assertIn("user02 disabled global", self.cmd("list"))
        self.assertFalse(wg.PENDING.exists())
        self.assertNotIn("# user02\n", wg.CONF.read_text())

    def test_links_and_dual_profiles(self):
        self.cmd("init")

        def redeem(code):
            with patch.object(sys, "stdin", io.StringIO(code)):
                return json.loads(self.cmd("redeem"))

        first = self.cmd("issue")
        code = self.cmd("issue")
        with self.assertRaises(ValueError):
            redeem(first)
        bundle = redeem(code)
        self.assertEqual(bundle["name"], "user02")
        full, proxy = [wg.section(bundle["profiles"][m]) for m in ("global", "proxy")]
        self.assertEqual(full["Interface"]["PrivateKey"], proxy["Interface"]["PrivateKey"])
        self.assertEqual(proxy["Peer"]["AllowedIPs"], "10.66.77.1/32")
        self.assertEqual(full["Peer"]["AllowedIPs"], "0.0.0.0/0, ::/0")
        with self.assertRaises(ValueError):
            redeem(code)
        for action in ("rotate", "disable"):
            code = self.cmd("issue")
            self.cmd(action)
            self.cmd("enable")
            with self.assertRaises(ValueError):
                redeem(code)
        with patch.object(wg.time, "time", return_value=100):
            code = self.cmd("issue")
        with patch.object(wg.time, "time", return_value=700), self.assertRaises(ValueError):
            redeem(code)

    def test_admin_bundles(self):
        self.cmd("init")
        before = wg.STATE.read_bytes()
        bundles = json.loads(self.cmd("bundles"))
        self.assertEqual(len(bundles), 25)
        self.assertEqual(bundles[1], json.loads(self.cmd("bundle")))
        self.assertEqual(wg.STATE.read_bytes(), before)
        self.cmd("disable")
        with self.assertRaises(ValueError):
            self.cmd("bundle")
        remaining = json.loads(self.cmd("bundles"))
        self.assertEqual(remaining, [b for b in bundles if b["name"] != "user02"])

    def test_dynamic_customers_and_legacy_state(self):
        self.cmd("init")
        before = self.cmd("export", "user25")
        def named(action, name, user="user25"):
            with patch.object(sys, "stdin", io.StringIO(name)):
                return self.cmd(action, user)
        named("rename", "研发 A")
        self.assertIn("user25 enabled global 研发 A", self.cmd("list"))
        self.assertEqual(before, self.cmd("export", "user25"))
        with self.assertRaises(wg.CustomerError):
            named("add", "研发 a")
        self.assertEqual(named("add", "上海 客户").strip(), "user26")
        with self.assertRaises(wg.CustomerError):
            self.cmd("delete", "user26")
        old = self.cmd("export", "user26")
        self.cmd("disable", "user26")
        self.cmd("delete", "user26")
        self.assertEqual(named("add", "新客户").strip(), "user27")
        new = self.cmd("export", "user27")
        self.assertEqual(wg.section(old)["Interface"]["Address"], wg.section(new)["Interface"]["Address"])
        self.assertNotEqual(wg.section(old)["Interface"]["PrivateKey"], wg.section(new)["Interface"]["PrivateKey"])
        self.cmd("init", count=1)
        self.assertEqual(len(self.cmd("list").splitlines()), 26)

    def test_capacity_and_removing_bootstrap_peer(self):
        self.cmd("init", count=253)
        with patch.object(sys, "stdin", io.StringIO("额外客户")), self.assertRaises(wg.CustomerError):
            self.cmd("add")
        self.cmd("disable", "user01")
        self.cmd("delete", "user01")
        self.assertFalse(wg.LEGACY.exists())
        with patch.object(sys, "stdin", io.StringIO("补位")):
            self.assertEqual(self.cmd("add").strip(), "user254")
        self.assertIn("10.66.77.2/32", self.cmd("export", "user254"))
