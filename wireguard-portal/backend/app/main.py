import io
import ipaddress
import os
import re
import secrets
import sqlite3
from typing import Literal
import httpx
import pyotp
import qrcode
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .auth import (
    DUMMY,
    consume,
    current,
    digest,
    email_code,
    matches,
    otp_path,
    password_hash,
    token,
)
from .db import audit, now, rows, transaction, uid
from .jobs import enqueue
from .remote import remote

app = FastAPI(title="WireGuard 用户中心", docs_url=None, redoc_url=None)
ORIGIN = os.getenv("PORTAL_ORIGIN", "https://localhost:8444")
from urllib.parse import urlsplit

app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(ORIGIN).hostname])
ADMIN = ("super_admin", "admin")
SUPER = ("super_admin",)


@app.middleware("http")
async def protection(req: Request, call_next):
    if req.method not in ("GET", "HEAD") and req.headers.get("origin") != ORIGIN:
        return JSONResponse({"detail": "请求来源无效"}, status_code=403)
    res = await call_next(req)
    res.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
    )
    return res


@app.exception_handler(RequestValidationError)
async def invalid(req, exc):
    return JSONResponse({"detail": "请求字段格式不正确"}, status_code=422)


@app.exception_handler(sqlite3.IntegrityError)
async def duplicate(req, exc):
    return JSONResponse({"detail": "记录已存在或有任务正在处理"}, status_code=409)


class Form(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=256)


class Login(Form):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(max_length=128)
    otp: str = ""


class Register(Form):
    username: str = Field(pattern=r"^[\w-]{2,40}$")
    email: EmailStr
    password: str
    invite: str = ""


class Code(Form):
    code: str


class Reset(Code):
    password: str


class Change(Form):
    old: str
    password: str


class Mail(Form):
    email: EmailStr


class Device(Form):
    label: str = Field(pattern=r"^[\w -]{1,40}$")
    server: int


class Server(Form):
    name: str = Field(min_length=1, max_length=40)
    address: ipaddress.IPv4Address


class Settings(Form):
    registration: Literal["closed", "invite", "review", "auto"]
    quota: int = Field(ge=1, le=253)


class Account(Form):
    status: Literal["active", "disabled", "pending"]
    quota: int = Field(ge=1, le=253)


class Adopt(Device):
    user: int
    peer: str = Field(pattern=r"^user[0-9]{2,16}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def checked_remote(server, path, payload=None):
    try:
        return remote(server, path, payload)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            409 if exc.response.status_code == 409 else 502, "远端拒绝操作，请重新同步"
        )
    except (httpx.HTTPError, OSError, ValueError):
        raise HTTPException(503, "VPS 管理连接不可用")


def client_address(req):
    # Only nginx is published; it overwrites this header on every request.
    return req.headers.get("x-portal-client", req.client.host)


def limit(subject, maximum):
    with transaction() as db:
        db.execute("DELETE FROM attempts WHERE until<=?", (now(),))
        db.execute(
            """INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(subject)
            DO UPDATE SET count=count+1""",
            (subject, now() + 300),
        )
        count = db.execute(
            "SELECT count FROM attempts WHERE subject=?", (subject,)
        ).fetchone()[0]
    if count > maximum:
        raise HTTPException(429, "请求过于频繁，五分钟后重试")


@app.get("/api/health")
def health():
    with transaction(False) as db:
        db.execute("SELECT value FROM app_settings LIMIT 1").fetchone()
    return {"version": 1, "smtp": bool(os.getenv("SMTP_HOST"))}


@app.post("/api/register")
def register(f: Register, req: Request):
    limit("register:" + client_address(req), 30)
    with transaction() as db:
        cfg = dict(db.execute("SELECT name,value FROM app_settings"))
        if cfg["registration"] == "closed":
            raise HTTPException(403, "注册已关闭")
        if cfg["registration"] == "invite":
            consume(db, f.invite, "invite")
        status = "pending" if cfg["registration"] == "review" else "active"
        user = db.execute(
            "INSERT INTO users(username,email,hash,status,quota) VALUES(?,?,?,?,?)",
            (
                f.username.strip().casefold(),
                str(f.email).casefold(),
                password_hash(f.password),
                status,
                int(cfg["quota"]),
            ),
        ).lastrowid
        db.execute("INSERT INTO user_roles VALUES(?,'user')", (user,))
        audit(db, user, "register", user)
    return {
        "status": status,
        "message": "注册成功，邮箱可在个人设置验证"
        if os.getenv("SMTP_HOST")
        else "邮件功能未启用，审核状态以管理员处理结果为准",
    }


@app.post("/api/login")
def login(f: Login, req: Request, res: Response):
    name = f.username.casefold()
    limit("login:" + client_address(req), 100)
    limit("account:" + digest(name), 10)
    with transaction() as db:
        u = db.execute(
            "SELECT u.*,r.role FROM users u JOIN user_roles r ON r.user=u.id WHERE username=?",
            (name,),
        ).fetchone()
        if not matches(u["hash"] if u else DUMMY, f.password) or not u:
            raise HTTPException(401, "登录凭据无效")
        if u["status"] != "active":
            raise HTTPException(
                403, "账号待审核" if u["status"] == "pending" else "账号已停用"
            )
        if u["role"] in ADMIN:
            step = now() // 30
            if step <= u["otp_step"] or not pyotp.TOTP(
                otp_path(u["id"]).read_text().strip()
            ).verify(f.otp):
                raise HTTPException(401, "动态验证码无效或已使用")
            db.execute("UPDATE users SET otp_step=? WHERE id=?", (step, u["id"]))
        db.execute("DELETE FROM attempts WHERE subject=?", ("account:" + digest(name),))
        db.execute(
            "DELETE FROM sessions WHERE digest=? OR expires<=?",
            (digest(req.cookies.get("sid", "")), now()),
        )
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            (digest(sid), u["id"], csrf, now() + 28800),
        )
        audit(db, u["id"], "login", u["id"])
        res.set_cookie(
            "sid", sid, httponly=True, secure=True, samesite="strict", max_age=28800
        )
    return {"csrf": csrf}


@app.get("/api/me")
def me(req: Request):
    with transaction(False) as db:
        return dict(current(db, req))


@app.post("/api/logout")
@app.post("/api/revoke-sessions")
def logout(req: Request, res: Response):
    with transaction() as db:
        u = current(db, req)
        if req.url.path.endswith("logout"):
            db.execute(
                "DELETE FROM sessions WHERE digest=?", (digest(req.cookies["sid"]),)
            )
        else:
            db.execute("DELETE FROM sessions WHERE user=?", (u["id"],))
        res.delete_cookie("sid", secure=True, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/api/password")
def password(f: Change, req: Request):
    with transaction() as db:
        u = current(db, req)
        if not matches(
            db.execute("SELECT hash FROM users WHERE id=?", (u["id"],)).fetchone()[0],
            f.old,
        ):
            raise HTTPException(403, "原密码无效")
        set_password(db, u["id"], f.password)


def set_password(db, user, value):
    db.execute("UPDATE users SET hash=? WHERE id=?", (password_hash(value), user))
    db.execute("DELETE FROM sessions WHERE user=?", (user,))
    db.execute("DELETE FROM tokens WHERE user=? AND purpose='reset'", (user,))
    audit(db, user, "password.changed", user)


@app.post("/api/forgot")
def forgot(f: Mail, req: Request):
    limit("mail:" + client_address(req), 10)
    if not os.getenv("SMTP_HOST"):
        raise HTTPException(503, "邮件未启用，请联系本地管理员重置密码")
    with transaction() as db:
        u = db.execute(
            "SELECT id,email FROM users WHERE email=? AND verified=1", (str(f.email),)
        ).fetchone()
        if u:
            email_code(u["email"], "密码重置", token(db, "reset", u["id"]))
    return {"message": "如有已验证账号，重置码将发送到该邮箱"}


@app.post("/api/reset")
def reset(f: Reset):
    with transaction() as db:
        set_password(db, consume(db, f.code, "reset")["user"], f.password)


@app.post("/api/verification")
def verification(req: Request):
    with transaction() as db:
        u = current(db, req)
        email_code(u["email"], "邮箱验证", token(db, "verify", u["id"]))


@app.post("/api/verify")
def verify(f: Code, req: Request):
    with transaction() as db:
        u = current(db, req)
        if consume(db, f.code, "verify")["user"] != u["id"]:
            raise HTTPException(403, "凭证归属无效")
        db.execute("UPDATE users SET verified=1 WHERE id=?", (u["id"],))


def get_server(db, server):
    row = db.execute("SELECT * FROM vpn_servers WHERE id=?", (server,)).fetchone()
    if not row:
        raise HTTPException(404, "VPS 不存在")
    return row


@app.get("/api/servers")
def servers(req: Request):
    with transaction(False) as db:
        u = current(db, req)
        return rows(
            db,
            "SELECT * FROM vpn_servers"
            if u["role"] == "super_admin"
            else "SELECT id,name,checked,health FROM vpn_servers",
        )


@app.post("/api/admin/servers")
def server(f: Server, req: Request):
    if not any(
        f.address in ipaddress.ip_network(n)
        for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ):
        raise HTTPException(422, "请输入管理隧道的内网地址")
    with transaction() as db:
        u = current(db, req, SUPER)
        db.execute(
            "INSERT INTO vpn_servers(name,address) VALUES(?,?)",
            (f.name, str(f.address)),
        )
        audit(db, u["id"], "server.add", f.name)


@app.get("/api/admin/servers/{server}/peers")
def inventory(server: int, req: Request):
    with transaction(False) as db:
        current(db, req, ADMIN)
        return checked_remote(get_server(db, server), "peers")


def add_device(db, owner, f, action, **params):
    u = db.execute("SELECT * FROM users WHERE id=?", (owner,)).fetchone()
    if not u or u["status"] != "active":
        raise HTTPException(409, "账号未激活")
    if (
        db.execute(
            "SELECT count(*) FROM devices WHERE user=? AND status!='retired'", (owner,)
        ).fetchone()[0]
        >= u["quota"]
    ):
        raise HTTPException(409, "设备配额已用完")
    server = get_server(db, f.server)
    snap = checked_remote(server, "peers")
    if snap.get("version") != 1:
        raise HTTPException(409, "Agent 版本不兼容")
    if not snap["live"] or (action == "create" and not snap["free"]):
        raise HTTPException(409, "VPS 接口未就绪或地址不足")
    device = uid()
    db.execute(
        "INSERT INTO devices(id,user,server,label,status) VALUES(?,?,?,?,'pending')",
        (device, owner, f.server, f.label),
    )
    if action == "create":
        params["label"] = "portal-" + device
    return {"device": device, "job": enqueue(db, device, action, **params)}


@app.post("/api/devices")
def create(f: Device, req: Request):
    with transaction() as db:
        u = current(db, req)
        raw = req.headers.get("idempotency-key")
        job_id = None
        if raw is not None:
            if not re.fullmatch(r"[0-9a-f]{32}", raw):
                raise HTTPException(422, "申请编号无效")
            job_id = digest(str(u["id"]) + ":" + raw)[:32]
            existing = db.execute(
                """SELECT j.device,d.label,d.server FROM provision_jobs j
                JOIN devices d ON j.device=d.id WHERE j.id=? AND d.user=?""",
                (job_id, u["id"]),
            ).fetchone()
            if existing:
                if (existing["label"], existing["server"]) != (f.label, f.server):
                    raise HTTPException(409, "相同申请编号已用于另一设备")
                return {"device": existing["device"], "job": job_id}
        result = add_device(db, u["id"], f, "create", job_id=job_id)
        audit(db, u["id"], "device.request", result["device"])
        return result


@app.post("/api/admin/adopt")
def adopt(f: Adopt, req: Request):
    with transaction() as db:
        u = current(db, req, SUPER)
        result = add_device(
            db, f.user, f, "adopt", peer=f.peer, fingerprint=f.fingerprint
        )
        audit(db, u["id"], "peer.adopt", result["device"])
        return result


DEVICE_SELECT = """SELECT d.*,s.name AS server_name,p.peer,p.address,p.fingerprint,
 (SELECT max(time) FROM download_events e WHERE e.device=d.id) AS last_download
 FROM devices d JOIN vpn_servers s ON s.id=d.server LEFT JOIN wireguard_peers p ON p.device=d.id"""


@app.get("/api/devices")
def devices(req: Request):
    with transaction(False) as db:
        return rows(
            db,
            DEVICE_SELECT + " WHERE d.user=? ORDER BY d.rowid DESC",
            (current(db, req)["id"],),
        )


@app.get("/api/admin/devices")
def all_devices(req: Request):
    with transaction(False) as db:
        current(db, req, ADMIN)
        return rows(db, DEVICE_SELECT + " ORDER BY d.rowid DESC")


@app.post("/api/admin/devices/{device}/{action}")
def manage(
    device: str, action: Literal["enable", "disable", "rotate", "delete"], req: Request
):
    with transaction() as db:
        u = current(db, req, ADMIN)
        p = db.execute(DEVICE_SELECT + " WHERE d.id=?", (device,)).fetchone()
        if p and action == "delete" and p["status"] in ("missing", "error"):
            inventory = checked_remote(get_server(db, p["server"]), "peers")
            if inventory.get("version") != 1 or any(
                row["device"] == device for row in inventory["rows"]
            ):
                raise HTTPException(409, "远端仍有绑定，请先同步并停用")
            if db.execute(
                "SELECT 1 FROM provision_jobs WHERE device=? AND status IN ('held','pending')",
                (device,),
            ).fetchone():
                raise HTTPException(409, "请先核对未完成任务")
            db.execute("DELETE FROM wireguard_peers WHERE device=?", (device,))
            db.execute("UPDATE devices SET status='retired' WHERE id=?", (device,))
            audit(db, u["id"], "release.missing", device)
            return {"status": "retired"}
        if (
            not p
            or not p["peer"]
            or p["status"] == "pending"
            or (action == "delete" and p["status"] != "disabled")
        ):
            raise HTTPException(409, "设备状态不允许本次操作")
        if (
            action == "enable"
            and db.execute(
                "SELECT status FROM users WHERE id=?", (p["user"],)
            ).fetchone()[0]
            != "active"
        ):
            raise HTTPException(409, "账号未启用")
        audit(db, u["id"], action, device)
        return {
            "job": enqueue(
                db, device, action, peer=p["peer"], fingerprint=p["fingerprint"]
            )
        }


@app.post("/api/devices/{device}/{mode}/{kind}")
def download(
    device: str,
    mode: Literal["global", "proxy"],
    kind: Literal["conf", "qr"],
    f: Code,
    req: Request,
):
    with transaction() as db:
        u = current(db, req)
        p = db.execute(
            DEVICE_SELECT + " WHERE d.id=? AND d.user=?", (device, u["id"])
        ).fetchone()
        if not p:
            raise HTTPException(404, "设备不存在")
        if p["status"] != "enabled" or f.code != p["fingerprint"]:
            raise HTTPException(409, "设备状态或密钥已变更，请刷新")
        conf = checked_remote(
            get_server(db, p["server"]),
            "operations",
            dict(
                action="export",
                device=device,
                peer=p["peer"],
                fingerprint=f.code,
                mode=mode,
            ),
        )["config"]
        db.execute(
            "INSERT INTO download_events(user,device,mode,format,time) VALUES(?,?,?,?,?)",
            (u["id"], device, mode, kind, now()),
        )
        if kind == "qr":
            buf = io.BytesIO()
            qrcode.make(conf).save(buf, format="PNG")
            return Response(buf.getvalue(), media_type="image/png")
        return Response(
            conf,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{p["peer"]}-{mode}.conf"'
            },
        )


@app.get("/api/admin/users")
def users(req: Request):
    with transaction(False) as db:
        current(db, req, ADMIN)
        return rows(
            db,
            "SELECT u.id,username,email,status,verified,quota,role FROM users u JOIN user_roles r ON u.id=r.user",
        )


@app.post("/api/admin/users/{user}")
def update_user(user: int, f: Account, req: Request):
    with transaction() as db:
        actor = current(db, req, ADMIN)
        role = db.execute(
            "SELECT role FROM user_roles WHERE user=?", (user,)
        ).fetchone()
        if not role or role[0] != "user":
            raise HTTPException(403, "仅可管理普通账号")
        db.execute(
            "UPDATE users SET status=?,quota=? WHERE id=?", (f.status, f.quota, user)
        )
        if f.status != "active":
            db.execute("DELETE FROM sessions WHERE user=?", (user,))
            for p in rows(
                db, DEVICE_SELECT + " WHERE d.user=? AND d.status='enabled'", (user,)
            ):
                enqueue(
                    db, p["id"], "disable", peer=p["peer"], fingerprint=p["fingerprint"]
                )
        audit(db, actor["id"], "account." + f.status, user)


@app.get("/api/admin/logs")
def logs(req: Request):
    with transaction(False) as db:
        current(db, req, ADMIN)
        return dict(
            audit=rows(db, "SELECT * FROM audit_logs ORDER BY id DESC LIMIT 500"),
            downloads=rows(
                db, "SELECT * FROM download_events ORDER BY id DESC LIMIT 500"
            ),
            jobs=rows(
                db,
                "SELECT id,device,status,tries,error FROM provision_jobs ORDER BY rowid DESC LIMIT 500",
            ),
        )


@app.get("/api/admin/settings")
def settings(req: Request):
    with transaction(False) as db:
        current(db, req, SUPER)
        return dict(db.execute("SELECT name,value FROM app_settings"))


@app.post("/api/admin/settings")
def configure(f: Settings, req: Request):
    with transaction() as db:
        u = current(db, req, SUPER)
        for key, value in f.model_dump().items():
            db.execute(
                "UPDATE app_settings SET value=? WHERE name=?", (str(value), key)
            )
        audit(db, u["id"], "settings.update", "platform")


@app.post("/api/admin/invite")
def invite(req: Request):
    with transaction() as db:
        actor = current(db, req, ADMIN)
        audit(db, actor["id"], "invite.create", "registration")
        return {"code": token(db, "invite")}


@app.post("/api/admin/sync")
def sync(req: Request):
    from .jobs import reconcile

    with transaction() as db:
        u = current(db, req, ADMIN)
        audit(db, u["id"], "sync", "servers")
    reconcile()
    return {"message": "已执行对账，可在设备管理查看状态"}


@app.post("/api/admin/backup")
def backup_database(req: Request):
    from .maintenance import backup

    with transaction() as db:
        u = current(db, req, SUPER)
        audit(db, u["id"], "backup", "platform")
    return Response(
        backup(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="portal-backup.enc"'},
    )


@app.post("/api/admin/jobs/{key}/retry")
def retry_job(key: str, req: Request):
    with transaction() as db:
        u = current(db, req, ADMIN)
        job = db.execute("SELECT * FROM provision_jobs WHERE id=?", (key,)).fetchone()
        latest = (
            db.execute(
                "SELECT j.id,d.status FROM provision_jobs j JOIN devices d ON j.device=d.id WHERE device=? ORDER BY j.rowid DESC LIMIT 1",
                (job["device"],),
            ).fetchone()
            if job
            else None
        )
        if (
            not job
            or not latest
            or latest["id"] != key
            or latest["status"] == "retired"
            or job["status"] == "done"
        ):
            raise HTTPException(409, "任务不可重试")
        db.execute(
            "UPDATE provision_jobs SET status='pending',due=0 WHERE id=?", (key,)
        )
        db.execute("UPDATE devices SET status='pending' WHERE id=?", (job["device"],))
        audit(db, u["id"], "job.retry", key)


@app.post("/api/admin/restore")
async def restore_database(req: Request):
    from .maintenance import restore_online

    with transaction(False) as db:
        current(db, req, SUPER)
    buf = bytearray()
    async for chunk in req.stream():
        if len(buf) + len(chunk) > 32 * 1024 * 1024:
            raise HTTPException(413, "备份超过 32 MiB，请使用控制台恢复")
        buf.extend(chunk)
    from cryptography.fernet import InvalidToken
    from zipfile import BadZipFile

    with transaction() as db:
        u = current(db, req, SUPER)
        if req.headers.get("x-confirm-restore") != "RESTORE":
            raise HTTPException(400, "请确认恢复操作")
        if not pyotp.TOTP(otp_path(u["id"]).read_text().strip()).verify(
            req.headers.get("x-admin-otp", "")
        ):
            raise HTTPException(403, "动态验证码无效")
        try:
            restore_online(db, bytes(buf))
        except (InvalidToken, BadZipFile, KeyError, ValueError, sqlite3.DatabaseError):
            raise HTTPException(409, "备份无效、版本不一致或 MFA 不匹配")
    return {"message": "已恢复，全部会话已撤销，请重新登录"}


@app.post("/api/profile")
def profile(f: Mail, req: Request):
    with transaction() as db:
        u = current(db, req)
        db.execute(
            "UPDATE users SET email=?,verified=0 WHERE id=?",
            (str(f.email).casefold(), u["id"]),
        )
        db.execute("DELETE FROM tokens WHERE user=?", (u["id"],))
        audit(db, u["id"], "email.change", u["id"])
