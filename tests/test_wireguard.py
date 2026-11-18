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

    def cmd(self, command, user="user02", mode="proxy"):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            wg.manage(SimpleNamespace(command=command, endpoint="192.0.2.1", user=user, mode=mode))
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
