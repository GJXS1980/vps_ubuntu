import json
import httpx
import pytest
from fastapi.testclient import TestClient
from conftest import account
from app import db, jobs, main, maintenance

FORM = dict(username="alice", email="alice@example.org", password="Valid-password-123!")


def device(client):
    r = client.post("/api/devices", json={"label": "电脑", "server": 1})
    assert r.status_code == 200, r.text
    assert jobs.process()
    return client.get("/api/devices").json()[0]


def export(client, d, mode="global", kind="conf"):
    return client.post(
        f"/api/devices/{d['id']}/{mode}/{kind}", json={"code": d["fingerprint"]}
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("username", "alice", 409),
        ("email", "alice@example.org", 409),
        ("password", "weak", 422),
    ],
)
def test_registration(client, field, value, code):
    assert client.post("/api/register", json=FORM).status_code == 200
    f = dict(FORM, username="bob", email="bob@example.org")
    f[field] = value
    assert client.post("/api/register", json=f).status_code == code


def test_pending_and_smtp(client):
    assert "未启用" in client.post("/api/register", json=FORM).json()["message"]
    assert (
        client.post(
            "/api/login", json={k: FORM[k] for k in ["username", "password"]}
        ).status_code
        == 403
    )
    assert client.post("/api/forgot", json={"email": FORM["email"]}).status_code == 503


def test_approval_and_revocation(client):
    account(client, "root", "super_admin")
    client.post("/api/register", json=FORM)
    user = client.get("/api/admin/users").json()[-1]["id"]
    url = f"/api/admin/users/{user}"
    assert client.post(url, json={"status": "active", "quota": 1}).status_code == 200
    with TestClient(
        main.app, base_url=main.ORIGIN, headers={"origin": main.ORIGIN}
    ) as other:
        other.post(
            "/api/login", json={"username": "alice", "password": FORM["password"]}
        )
        assert other.get("/api/me").status_code == 200
        client.post(url, json={"status": "disabled", "quota": 1})
        assert other.get("/api/me").status_code == 401


@pytest.mark.parametrize("action", ["logout", "password", "revoke-sessions"])
def test_session_end(client, action):
    account(client)
    assert (
        client.post(
            "/api/" + action,
            json={"old": FORM["password"], "password": "Changed-password123!"},
        ).status_code
        == 200
    )
    assert client.get("/api/me").status_code == 401


def test_csrf_mfa_and_role(client):
    account(client)
    assert client.get("/api/admin/users").status_code == 403
    assert (
        client.post(
            "/api/logout", headers={"origin": "https://other.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/logout", headers={"x-csrf-token": "bad"}).status_code == 403
    )
    account(client, "boss", "admin")
    assert (
        client.post(
            "/api/login", json={"username": "boss", "password": FORM["password"]}
        ).status_code
        == 401
    )
    assert client.get("/api/admin/settings").status_code == 403


def test_throttle(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/login", json={"username": "nobody", "password": "bad"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/login", json={"username": "nobody", "password": "bad"}
        ).status_code
        == 429
    )


def test_downloads(client, caplog):
    account(client)
    d = device(client)
    assert d["status"] == "enabled" and d["address"].startswith("10.66.77.4/")
    assert (
        client.post("/api/devices", json={"server": 1, "label": "第二台"}).status_code
        == 409
    )
    for mode, route in [("global", "0.0.0.0/0"), ("proxy", "10.66.77.1/32")]:
        r = export(client, d, mode)
        assert r.status_code == 200 and route in r.text and "TEST_PRIVATE" in r.text
        assert r.headers["cache-control"] == "no-store"
        assert export(client, d, mode, "qr").content.startswith(b"\x89PNG")
    assert "TEST_PRIVATE" not in caplog.text
    account(client, "bob")
    assert export(client, d).status_code == 404
    client.post("/api/logout")
    assert export(client, d).status_code == 401


def test_mutations(client):
    account(client, "boss", "admin")
    d = device(client)
    for action, status in [
        ("rotate", "enabled"),
        ("disable", "disabled"),
        ("enable", "enabled"),
        ("disable", "disabled"),
        ("delete", "retired"),
    ]:
        assert client.post(f"/api/admin/devices/{d['id']}/{action}").status_code == 200
        assert jobs.process()
        updated = client.get("/api/devices").json()[0]
        assert updated["status"] == status
        if action in ("disable", "rotate"):
            assert export(client, d).status_code == 409
        d = updated


def test_uncertain_create(client, env, monkeypatch):
    account(client)
    result = client.post("/api/devices", json={"server": 1, "label": "手机"}).json()

    assert "job" in result

    def lost(server, path, payload=None):
        receipt = env.call(server, path, payload)
        if path == "operations":
            raise httpx.ReadTimeout("simulated")
        return receipt

    monkeypatch.setattr(jobs, "remote", lost)
    jobs.process()
    with db.transaction() as conn:
        assert (
            conn.execute("SELECT status FROM provision_jobs").fetchone()[0] == "pending"
        )
        conn.execute("UPDATE provision_jobs SET due=0")
    jobs.process()
    assert client.get("/api/devices").json()[0]["status"] == "enabled"
    assert len(json.loads(env.cli["STATE"].read_text())["users"]) == 1


@pytest.mark.parametrize("bad", ["capacity", "down", "version"])
def test_vps_unavailable(client, monkeypatch, bad):
    account(client)

    def mock(*args):
        if bad == "down":
            raise httpx.ConnectError("offline")
        return dict(version=2 if bad == "version" else 1, live=True, free=0)

    monkeypatch.setattr(main, "remote", mock)
    assert client.post(
        "/api/devices", json={"server": 1, "label": "手机"}
    ).status_code in (409, 503)
    assert client.get("/api/health").status_code == 200


def test_external_change(client, env):
    account(client, "boss", "admin")
    d = device(client)
    state = json.loads(env.cli["STATE"].read_text())
    state["users"][d["peer"]]["enabled"] = False
    env.cli["apply_state"](state)
    jobs.reconcile()
    assert client.get("/api/devices").json()[0]["status"] == "disabled"
    state["users"].clear()
    env.cli["apply_state"](state)
    jobs.reconcile()
    assert client.get("/api/devices").json()[0]["status"] == "missing"
    assert client.post(f"/api/admin/devices/{d['id']}/delete").json() == {
        "status": "retired"
    }


def test_backup_restore(client, env):
    account(client, "boss", "super_admin")
    blob = client.post("/api/admin/backup").content
    assert b"SQLite" not in blob and b"TEST_PRIVATE" not in blob
    file = env.root / "backup.enc"
    file.write_bytes(blob)
    with db.transaction() as conn:
        conn.execute("UPDATE users SET status='disabled'")
    maintenance.restore(file)
    with db.transaction(False) as conn:
        assert conn.execute("SELECT status FROM users").fetchone()[0] == "active"
        assert not conn.execute("SELECT * FROM sessions").fetchone()


def test_agent_idempotency_and_binding(env):
    q = dict(action="create", device=db.uid(), key=db.uid(), label="phone")
    a = env.call(None, "operations", q)
    assert a == env.call(None, "operations", q)
    for bad in [
        dict(q, label="different"),
        dict(
            action="export",
            peer=a["peer"],
            fingerprint=a["fingerprint"],
            device=db.uid(),
            mode="global",
        ),
        dict(
            action="export",
            peer="user01;echo",
            fingerprint=a["fingerprint"],
            device=q["device"],
            mode="global",
        ),
    ]:
        with pytest.raises(ValueError):
            env.call(None, "operations", bad)


def test_web_restore(client, env):
    import pyotp
    from app.auth import otp_path

    user = account(client, "boss", "super_admin")
    blob = client.post("/api/admin/backup").content
    client.post("/api/register", json=FORM)
    assert client.post("/api/admin/restore", content=blob).status_code == 400
    headers = {
        "x-confirm-restore": "RESTORE",
        "x-admin-otp": pyotp.TOTP(otp_path(user).read_text()).now(),
    }
    assert (
        client.post(
            "/api/admin/restore", content=b"invalid", headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post("/api/admin/restore", content=blob, headers=headers).status_code
        == 200
    )
    assert client.get("/api/me").status_code == 401
    with db.transaction(False) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_registration_modes(client):
    account(client, "boss", "super_admin")

    def mode(name):
        assert (
            client.post(
                "/api/admin/settings", json={"registration": name, "quota": 2}
            ).status_code
            == 200
        )

    mode("closed")
    assert client.post("/api/register", json=FORM).status_code == 403
    mode("invite")
    assert client.post("/api/register", json=FORM).status_code == 400
    code = client.post("/api/admin/invite").json()["code"]
    assert (
        client.post("/api/register", json=dict(FORM, invite=code)).json()["status"]
        == "active"
    )
    assert client.post("/api/register", json=dict(FORM, invite=code)).status_code == 400
    mode("auto")
    assert (
        client.post(
            "/api/register", json=dict(FORM, email="bob@example.org", username="bob")
        ).json()["status"]
        == "active"
    )


def test_mail_reset(client, monkeypatch):
    assert account(client)
    messages = []
    monkeypatch.setenv("SMTP_HOST", "test.invalid")
    monkeypatch.setattr(
        main, "email_code", lambda addr, purpose, code: messages.append(code)
    )
    client.post("/api/verification")
    assert client.post("/api/verify", json={"code": messages.pop()}).status_code == 200
    client.post("/api/forgot", json={"email": FORM["email"]})
    raw = messages.pop()
    assert (
        client.post(
            "/api/reset", json={"code": raw, "password": "Replacement-password!"}
        ).status_code
        == 200
    )
    assert client.get("/api/me").status_code == 401
    assert (
        client.post(
            "/api/reset", json={"code": raw, "password": "Replacement-password!"}
        ).status_code
        == 400
    )


def test_adopt_and_history(client, env):
    user = account(client, "boss", "super_admin")
    state = json.loads(env.cli["STATE"].read_text())
    name = env.cli["allocate_peer"](state, "older", reserved_hosts=(2, 3), first_id=3)
    env.cli["apply_state"](state)
    snap = client.get("/api/admin/servers/1/peers").json()["rows"][0]
    assert snap["device"] is None
    request = dict(
        server=1, user=user, label="old", peer=name, fingerprint=snap["fingerprint"]
    )
    assert client.post("/api/admin/adopt", json=request).status_code == 200
    assert jobs.process()
    assert client.get("/api/devices").json()[0]["peer"] == name
    new = json.loads(env.cli["STATE"].read_text())
    assert new["users"][name]["private"] == state["users"][name]["private"]


def test_error_and_manual_retry(client, env, monkeypatch):
    account(client, "boss", "admin")
    job = client.post("/api/devices", json={"label": "手机", "server": 1}).json()["job"]

    def conflict(server, path, payload=None):
        if payload:
            raise httpx.HTTPStatusError(
                "拒绝",
                request=httpx.Request("POST", "https://test"),
                response=httpx.Response(409),
            )
        return env.call(server, path, payload)

    monkeypatch.setattr(jobs, "remote", conflict)
    jobs.process()
    assert client.get("/api/devices").json()[0]["status"] == "error"
    assert client.post("/api/admin/jobs/" + job + "/retry").status_code == 200
    monkeypatch.setattr(jobs, "remote", env.call)
    jobs.process()
    assert client.get("/api/devices").json()[0]["status"] == "enabled"


def test_duplicate_request(client):
    from concurrent.futures import ThreadPoolExecutor

    account(client)
    header = {"Idempotency-Key": db.uid()}

    def create(_):
        return client.post(
            "/api/devices", json={"label": "laptop", "server": 1}, headers=header
        ).json()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(create, range(3)))
    assert all(r == results[0] for r in results) and "job" in results[0]
    jobs.process()
    assert create(None) == results[0]
    assert (
        client.post(
            "/api/devices", json={"label": "other", "server": 1}, headers=header
        ).status_code
        == 409
    )
    assert len(client.get("/api/devices").json()) == 1


def test_migration_preserves_users(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, event
    from conftest import BACK

    engine = create_engine("sqlite:///" + (tmp_path / "upgrade.db").as_posix())
    event.listen(engine, "connect", db.setup)
    monkeypatch.setattr(db, "engine", engine)
    cfg = Config(str(BACK / "alembic.ini"))
    command.upgrade(cfg, "001")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO vpn_servers(id,name,address) VALUES(1,'原节点','10.0.0.1')"
        )
    command.upgrade(cfg, "head")
    engine.dispose()
    with db.transaction(False) as conn:
        server = conn.execute("SELECT * FROM vpn_servers").fetchone()
        assert server["health"] == "未采样" and server["name"] == "原节点"
    engine.dispose()


def test_bootstrap_repeat(env, monkeypatch):
    import sys
    import pyotp
    import builtins

    monkeypatch.setattr(sys, "argv", ["maintenance", "bootstrap", "local-admin"])
    monkeypatch.setattr(builtins, "input", lambda _: "admin@example.org")
    monkeypatch.setattr(maintenance.os, "isatty", lambda _: True)
    seed = pyotp.random_base32()
    monkeypatch.setattr(pyotp, "random_base32", lambda: seed)
    monkeypatch.setattr(
        maintenance.getpass,
        "getpass",
        lambda prompt: (
            pyotp.TOTP(seed).now() if "动态" in prompt else "Local-admin-password!"
        ),
    )
    maintenance.main()
    maintenance.main()
    with db.transaction(False) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert (
            conn.execute("SELECT hash FROM users")
            .fetchone()[0]
            .startswith("$argon2id$")
        )
    assert (env.root / "mfa-1.key").read_text() == seed


def test_fixed_session_replaced(client):
    client.cookies.set("sid", "fixed-session", domain="localhost.local", path="/")
    account(client)
    assert (
        client.cookies.get("sid", domain="localhost.local", path="/") != "fixed-session"
    )
    old = client.cookies.get("sid", domain="localhost.local", path="/")
    client.post("/api/login", json={"username": "alice", "password": FORM["password"]})
    with TestClient(main.app, base_url=main.ORIGIN) as stale:
        stale.cookies.set("sid", old)
        assert stale.get("/api/me").status_code == 401


def test_local_commit_failure(client, env, monkeypatch):
    from contextlib import contextmanager

    account(client)
    client.post("/api/devices", json={"label": "测试", "server": 1})

    @contextmanager
    def failed():
        with db.transaction() as conn:
            yield conn
            raise OSError("simulated local storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(jobs, "transaction", failed)
        with pytest.raises(OSError):
            jobs.process()
    assert client.get("/api/devices").json()[0]["status"] == "pending"
    jobs.process()
    assert client.get("/api/devices").json()[0]["status"] == "enabled"
    assert len(json.loads(env.cli["STATE"].read_text())["users"]) == 1
