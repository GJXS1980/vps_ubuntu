import hashlib
import sqlite3
import json
import time
import httpx
from .db import audit, now, rows, transaction, uid
from .remote import remote


def enqueue(db, device, action, job_id=None, **fields):
    key = job_id or uid()
    payload = dict(key=key, device=device, action=action, **fields)
    db.execute(
        "INSERT INTO provision_jobs(id,device,request,status) VALUES(?,?,?,'pending')",
        (key, device, json.dumps(payload)),
    )
    db.execute("UPDATE devices SET status='pending' WHERE id=?", (device,))
    return key


def process():
    # Serialize a claim with completion. A dead worker releases SQLite's lock.
    with transaction() as db:
        job = db.execute(
            "SELECT * FROM provision_jobs WHERE status='pending' AND due<=? ORDER BY due,rowid LIMIT 1",
            (now(),),
        ).fetchone()
        if not job:
            return False
        q = json.loads(job["request"])
        d = db.execute("SELECT * FROM devices WHERE id=?", (job["device"],)).fetchone()
        server = db.execute(
            "SELECT * FROM vpn_servers WHERE id=?", (d["server"],)
        ).fetchone()
        try:
            result = remote(server, "results/" + job["id"])
            if result is None:
                owner = db.execute(
                    "SELECT status FROM users WHERE id=?", (d["user"],)
                ).fetchone()
                if (
                    q["action"] in ("create", "enable", "adopt")
                    and owner[0] != "active"
                ):
                    db.execute(
                        "UPDATE provision_jobs SET status='failed',error='账号未启用' WHERE id=?",
                        (job["id"],),
                    )
                    db.execute(
                        "UPDATE devices SET status='error' WHERE id=?", (d["id"],)
                    )
                    return True
                result = remote(server, "operations", q)
            expected = hashlib.sha256(
                json.dumps(q, sort_keys=True).encode()
            ).hexdigest()
            if (
                result.get("signature") != expected
                or result["device"] != d["id"]
                or result["action"] != q["action"]
            ):
                raise ValueError("receipt mismatch")
            if q["action"] == "delete":
                db.execute("DELETE FROM wireguard_peers WHERE device=?", (d["id"],))
                status = "retired"
            else:
                db.execute(
                    """INSERT INTO wireguard_peers VALUES(?,?,?,?,?) ON CONFLICT(device)
                    DO UPDATE SET fingerprint=excluded.fingerprint,address=excluded.address""",
                    (
                        d["id"],
                        server["id"],
                        result["peer"],
                        result["fingerprint"],
                        result["address"],
                    ),
                )
                status = "enabled" if result["enabled"] else "disabled"
            db.execute("UPDATE devices SET status=? WHERE id=?", (status, d["id"]))
            db.execute(
                "UPDATE provision_jobs SET status='done',error='' WHERE id=?",
                (job["id"],),
            )
            audit(db, None, "worker." + q["action"], d["id"])
        except (
            OSError,
            ValueError,
            KeyError,
            sqlite3.IntegrityError,
            httpx.HTTPError,
        ) as exc:
            conflict = isinstance(
                exc, httpx.HTTPStatusError
            ) and exc.response.status_code in (409, 422)
            db.execute(
                "UPDATE provision_jobs SET status=?,tries=tries+1,due=?,error=? WHERE id=?",
                (
                    "failed" if conflict else "pending",
                    now() + min(300, 2 ** min(8, job["tries"] + 1)),
                    "远端拒绝操作" if conflict else "远端结果待确认",
                    job["id"],
                ),
            )
            if conflict:
                db.execute("UPDATE devices SET status='error' WHERE id=?", (d["id"],))
        return True


def reconcile():
    with transaction(False) as db:
        servers = rows(db, "SELECT * FROM vpn_servers")
    for server in servers:
        try:
            with transaction() as db:
                snap = remote(server, "peers")
                if snap.get("version") != 1:
                    raise ValueError("版本不兼容")
                db.execute(
                    "UPDATE vpn_servers SET checked=?,health=? WHERE id=?",
                    (
                        now(),
                        snap.get("warning")
                        or ("正常" if snap["live"] else "接口未启动"),
                        server["id"],
                    ),
                )
                indexed = {r["name"]: r for r in snap["rows"]}
                for p in rows(
                    db,
                    """SELECT p.*,u.status AS account FROM wireguard_peers p JOIN devices d ON p.device=d.id
                    JOIN users u ON u.id=d.user WHERE p.server=? AND d.status!='pending'""",
                    (server["id"],),
                ):
                    r = indexed.get(p["peer"])
                    if not r or r["device"] != p["device"]:
                        status, metrics = "missing", {}
                    else:
                        status, metrics = (
                            "enabled" if r["enabled"] else "disabled",
                            dict(r, sampled=snap["time"]),
                        )
                        db.execute(
                            "UPDATE wireguard_peers SET fingerprint=? WHERE device=?",
                            (r["fingerprint"], p["device"]),
                        )
                    db.execute(
                        "UPDATE devices SET status=?,metrics=? WHERE id=?",
                        (status, json.dumps(metrics), p["device"]),
                    )
                    if status == "enabled" and p["account"] != "active":
                        enqueue(
                            db,
                            p["device"],
                            "disable",
                            peer=p["peer"],
                            fingerprint=r["fingerprint"],
                        )
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            with transaction() as db:
                db.execute(
                    "UPDATE vpn_servers SET checked=?,health='管理连接异常' WHERE id=?",
                    (now(), server["id"]),
                )
                if server["health"] != "管理连接异常":
                    audit(db, None, "agent.unreachable", server["id"])


if __name__ == "__main__":
    last = 0
    while True:
        if time.monotonic() - last >= 30:
            reconcile()
            last = time.monotonic()
        if not process():
            time.sleep(1)
