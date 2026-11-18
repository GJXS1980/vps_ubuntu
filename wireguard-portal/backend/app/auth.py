import hashlib
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from .db import DATA, now

hasher = PasswordHasher()
DUMMY = hasher.hash(secrets.token_urlsafe(32))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(value):
    if not 12 <= len(value) <= 128 or len(set(value)) < 6:
        raise HTTPException(422, "密码须为 12 至 128 个字符，至少含 6 种不同字符")
    return hasher.hash(value)


def matches(encoded, value):
    try:
        return hasher.verify(encoded, value)
    except VerifyMismatchError:
        return False


def current(db, request, roles=None):
    row = db.execute(
        """SELECT u.id,u.username,u.email,u.quota,u.status,u.verified,r.role,s.csrf
        FROM sessions s JOIN users u ON u.id=s.user JOIN user_roles r ON r.user=u.id
        WHERE s.digest=? AND s.expires>?""",
        (digest(request.cookies.get("sid", "")), now()),
    ).fetchone()
    if not row or row["status"] != "active":
        raise HTTPException(401, "请登录有效账号")
    if request.method != "GET" and not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), row["csrf"]
    ):
        raise HTTPException(403, "请刷新页面后重试")
    if roles and row["role"] not in roles:
        raise HTTPException(403, "权限不足")
    return row


def token(db, purpose, user=None):
    raw = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO tokens VALUES(?,?,?,?)", (digest(raw), purpose, user, now() + 1800)
    )
    return raw


def consume(db, raw, purpose):
    row = db.execute(
        "SELECT * FROM tokens WHERE digest=? AND purpose=? AND expires>?",
        (digest(raw), purpose, now()),
    ).fetchone()
    if not row:
        raise HTTPException(400, "凭证过期或无效")
    db.execute("DELETE FROM tokens WHERE digest=?", (row["digest"],))
    return row


def email_code(address, purpose, raw):
    if not os.getenv("SMTP_HOST"):
        raise HTTPException(503, "未启用邮件，请联系管理员")
    message = EmailMessage()
    message["From"], message["To"] = os.environ["SMTP_FROM"], address
    message["Subject"] = "WireGuard " + purpose
    message.set_content("请在平台输入一次性验证码，30 分钟内有效。\n" + raw)
    try:
        with smtplib.SMTP_SSL(
            os.environ["SMTP_HOST"],
            int(os.getenv("SMTP_PORT", "465")),
            timeout=8,
            context=ssl.create_default_context(),
        ) as smtp:
            if os.getenv("SMTP_USER"):
                smtp.login(
                    os.environ["SMTP_USER"],
                    Path(os.environ["SMTP_PASSWORD_FILE"]).read_text().strip(),
                )
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(503, "邮件服务暂不可用")


def otp_path(user):
    return DATA / ("mfa-" + str(int(user)) + ".key")
