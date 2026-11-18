import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import uuid
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
BACK = ROOT / "wireguard-portal/backend"
sys.path.insert(0, str(BACK))
os.environ.setdefault("PORTAL_DATA", tempfile.mkdtemp(prefix="portal-pytest-"))
from app import auth, db, jobs, main, maintenance


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "portal.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", db.setup)
    monkeypatch.setattr(db, "engine", engine)
    for module in (auth, db, maintenance):
        monkeypatch.setattr(module, "DATA", tmp_path)
    cfg = Config(str(BACK / "alembic.ini"))
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "fcntl", types.ModuleType("fcntl"))
    cli = runpy.run_path(str(ROOT / "bin/wgvps-users.py"))["manage"].__globals__
    bridge_path = ROOT / "wireguard-portal/agent/bridge.py"
    bridge = runpy.run_path(str(bridge_path))
    for key, file in {
        "CONF": "wgvps.conf",
        "STATE": "state.json",
        "PENDING": "pending.json",
        "LIVE": "live",
        "LEGACY": "legacy.conf",
    }.items():
        cli[key] = tmp_path / file
    cli["LIVE"].touch()
    cli["run"] = lambda *args, **kwargs: ""
    cli["keys"] = lambda: dict(
        private="TEST_PRIVATE", public=uuid.uuid4().hex, psk="TEST_PSK"
    )
    state = dict(
        base="[Interface]", users={}, endpoint="192.0.2.1", server_public="TEST_SERVER"
    )
    cli["STATE"].write_text(json.dumps(state))

    def call(server, path, payload=None):
        if path == "peers":
            q = {"action": "inventory"}
        elif path.startswith("results/"):
            q = {"action": "result", "key": path.split("/")[1]}
        else:
            q = payload
        return bridge["dispatch"](cli, json.loads(cli["STATE"].read_text()), q)

    for module in (jobs, main):
        monkeypatch.setattr(module, "remote", call)
    maintenance.secret(tmp_path / "backup.key", maintenance.Fernet.generate_key())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO vpn_servers(id,name,address) VALUES(1,'测试节点','10.203.91.1')"
        )
    yield types.SimpleNamespace(cli=cli, bridge=bridge, call=call, root=tmp_path)
    engine.dispose()


@pytest.fixture
def client(env):
    with TestClient(
        main.app, base_url=main.ORIGIN, headers={"origin": main.ORIGIN}
    ) as c:
        yield c


def account(c, name="alice", role="user"):
    import pyotp

    body = dict(
        username=name, email=name + "@example.org", password="Valid-password-123!"
    )
    assert c.post("/api/register", json=body).status_code == 200
    with db.transaction() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username=?", (name,)
        ).fetchone()[0]
        conn.execute("UPDATE users SET status='active' WHERE id=?", (user,))
        conn.execute("UPDATE user_roles SET role=? WHERE user=?", (role, user))
    login = dict(username=name, password=body["password"])
    if role != "user":
        seed = pyotp.random_base32()
        auth.otp_path(user).write_text(seed)
        login["otp"] = pyotp.TOTP(seed).now()
    res = c.post("/api/login", json=login)
    assert res.status_code == 200, res.text
    c.headers["x-csrf-token"] = res.json()["csrf"]
    return user
