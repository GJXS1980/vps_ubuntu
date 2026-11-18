"""Disposable loopback HTTPS backend for Playwright. Requires built frontend."""

import ipaddress
import os
from pathlib import Path
import runpy
import sys
import tempfile

base = Path(tempfile.mkdtemp(prefix="portal-browser-"))
os.environ.update(
    PORTAL_DATA=str(base),
    PORTAL_ORIGIN="https://127.0.0.1:" + os.getenv("PORTAL_TEST_PORT", "17444"),
)
BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACK))
from alembic import command
from alembic.config import Config
from fastapi.staticfiles import StaticFiles
import uvicorn
from app.main import app

if __name__ == "__main__":
    command.upgrade(Config(str(BACK / "alembic.ini")), "head")
    server = base / "server"
    server.mkdir()
    generator = runpy.run_path(str(BACK.parent / "scripts/management-link.py"))
    generator["certs"](base, server, ipaddress.IPv4Address("127.0.0.1"))
    import base64, json, secrets, threading, time, types, uuid
    import pyotp
    from app import auth, db, jobs, main

    seed = pyotp.random_base32()
    password = secrets.token_urlsafe(24)
    with db.transaction() as conn:
        user = conn.execute(
            "INSERT INTO users(username,email,hash,status) VALUES('test-admin','admin@example.org',?,'active')",
            (auth.password_hash(password),),
        ).lastrowid
        conn.execute("INSERT INTO user_roles VALUES(?,'super_admin')", (user,))
        auth.otp_path(user).write_text(seed)
        conn.execute(
            "INSERT INTO vpn_servers(id,name,address) VALUES(1,'浏览器测试节点','10.203.91.1')"
        )
    credential = Path(os.environ["PORTAL_TEST_CREDENTIALS"])
    credential.write_text(
        json.dumps(
            dict(
                pid=os.getpid(),
                password=password,
                seed=base64.b64encode(base64.b32decode(seed)).decode(),
            )
        )
    )
    if sys.platform == "win32":
        sys.modules["fcntl"] = types.ModuleType("fcntl")
    cli = runpy.run_path(str(BACK.parents[1] / "bin/wgvps-users.py"))[
        "manage"
    ].__globals__
    for key, file in {
        "CONF": "wgvps.conf",
        "STATE": "state.json",
        "PENDING": "pending.json",
        "LIVE": "live",
        "LEGACY": "legacy.conf",
    }.items():
        cli[key] = base / file
    cli["LIVE"].touch()
    cli["run"] = lambda *args, **kwargs: ""
    cli["keys"] = lambda: dict(
        private="BROWSER_TEST_KEY", public=uuid.uuid4().hex, psk="TEST_PSK"
    )
    cli["STATE"].write_text(
        json.dumps(
            dict(
                base="[Interface]",
                users={},
                endpoint="192.0.2.1",
                server_public="TEST_SERVER",
            )
        )
    )
    bridge = runpy.run_path(str(BACK.parent / "agent/bridge.py"))

    def transport(server, path, payload=None):
        q = (
            {"action": "inventory"}
            if path == "peers"
            else {"action": "result", "key": path.split("/")[-1]}
            if path.startswith("results/")
            else payload
        )
        return bridge["dispatch"](cli, json.loads(cli["STATE"].read_text()), q)

    jobs.remote = main.remote = transport

    def work():
        while True:
            jobs.process()
            time.sleep(0.2)

    threading.Thread(target=work, daemon=True).start()
    app.mount("/", StaticFiles(directory=sys.argv[1], html=True))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("PORTAL_TEST_PORT", "17444")),
        ssl_certfile=str(server / "server.crt"),
        ssl_keyfile=str(server / "server.key"),
        access_log=False,
    )
