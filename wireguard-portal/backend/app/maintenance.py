"""Console maintenance and authenticated encrypted SQLite snapshots."""

import argparse
import getpass
import io
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from cryptography.fernet import Fernet
import pyotp
from .auth import otp_path, password_hash
from .db import DATA, transaction, audit
from .main import set_password


def secret(path, value):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as out:
        out.write(value)


def cipher():
    return Fernet((DATA / "backup.key").read_bytes())


def backup():
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        snap = Path(tmp) / "portal.db"
        with (
            sqlite3.connect(DATA / "portal.db") as source,
            sqlite3.connect(snap) as dest,
        ):
            source.backup(dest)
            dest.execute("DELETE FROM sessions")
            dest.execute("DELETE FROM tokens")
            dest.execute("DELETE FROM attempts")
            dest.commit()
            dest.execute("VACUUM")
        dest.close()
        source.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snap, "portal.db")
            for key in DATA.glob("mfa-*.key"):
                archive.write(key, key.name)
        return cipher().encrypt(buf.getvalue())


def restore(path):
    import re

    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(
            io.BytesIO(cipher().decrypt(path.read_bytes()))
        ) as archive:
            for name in archive.namelist():
                if name != "portal.db" and not re.fullmatch(r"mfa-[0-9]+\.key", name):
                    raise ValueError("备份文件名无效")
                secret(stage / name, archive.read(name))
        with sqlite3.connect(stage / "portal.db") as source:
            if (
                source.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or source.execute("PRAGMA foreign_key_check").fetchone()
            ):
                raise ValueError("备份完整性检查失败")
            for (user,) in source.execute(
                "SELECT user FROM user_roles WHERE role!='user'"
            ):
                if not (stage / f"mfa-{user}.key").is_file():
                    raise ValueError("缺少管理员 MFA")
            with sqlite3.connect(DATA / "portal.db") as dest:
                source.backup(dest)
            dest.close()
        source.close()
        for key in stage.glob("mfa-*.key"):
            key.replace(DATA / key.name)


def enroll_mfa(user):
    if not os.isatty(1):
        raise SystemExit("请在私密交互终端设置 MFA")
    path = otp_path(user)
    seed = path.read_text().strip() if path.exists() else pyotp.random_base32()
    if not path.exists():
        print("请将以下密钥加入 TOTP 验证器，本次仅显示一次。\n" + seed)
    if not pyotp.TOTP(seed).verify(getpass.getpass("输入当前动态验证码: ")):
        raise SystemExit("动态验证码不匹配")
    if not path.exists():
        secret(path, seed.encode())


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "action",
        choices=[
            "bootstrap",
            "admin",
            "grant-admin",
            "revoke-admin",
            "password",
            "backup",
            "restore",
        ],
    )
    p.add_argument("arg", nargs="?")
    args = p.parse_args()
    os.umask(0o077)
    if args.action == "backup":
        secret(Path(args.arg), backup())
        return
    if args.action == "restore":
        restore(Path(args.arg))
        return
    with transaction() as db:
        if args.action == "bootstrap":
            if db.execute(
                "SELECT 1 FROM user_roles WHERE role='super_admin'"
            ).fetchone():
                cipher()
                return
            if not (DATA / "backup.key").exists():
                secret(DATA / "backup.key", Fernet.generate_key())
        name = (args.arg or input("用户名: ")).strip().casefold()
        if args.action in ("grant-admin", "revoke-admin"):
            target = db.execute(
                "SELECT u.id,r.role FROM users u JOIN user_roles r ON u.id=r.user WHERE u.username=?",
                (name,),
            ).fetchone()
            if not target or target["role"] == "super_admin":
                raise SystemExit("只能调整普通用户或业务管理员")
            role = "admin" if args.action == "grant-admin" else "user"
            if role == "admin":
                enroll_mfa(target["id"])
            db.execute(
                "UPDATE user_roles SET role=? WHERE user=?", (role, target["id"])
            )
            db.execute("DELETE FROM sessions WHERE user=?", (target["id"],))
            audit(db, None, "role." + role, target["id"])
            return
        if args.action == "password":
            u = db.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()
            if not u:
                raise SystemExit("用户不存在")
            set_password(db, u[0], getpass.getpass("新密码: "))
            return
        import re

        if not re.fullmatch(r"[\w-]{2,40}", name):
            raise SystemExit("用户名须为 2 至 40 个字母、数字、下划线或短横线")
        from email_validator import validate_email

        email = validate_email(input("邮箱: "), check_deliverability=False).normalized
        hashed = password_hash(getpass.getpass("密码（至少 12 个字符）: "))
        user = db.execute(
            "INSERT INTO users(username,email,hash,status) VALUES(?,?,?,'active')",
            (name, email, hashed),
        ).lastrowid
        role = "super_admin" if args.action == "bootstrap" else "admin"
        db.execute("INSERT INTO user_roles VALUES(?,?)", (user, role))
        enroll_mfa(user)
        audit(db, None, "admin.init", user)


def restore_online(db, encrypted):
    """Keep one writer transaction across validation, rollback snapshot and import."""
    tables = (
        "roles",
        "users",
        "user_roles",
        "vpn_servers",
        "devices",
        "wireguard_peers",
        "provision_jobs",
        "download_events",
        "audit_logs",
        "app_settings",
    )
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        stage = Path(tmp) / "restore.db"
        with zipfile.ZipFile(io.BytesIO(cipher().decrypt(encrypted))) as archive:
            secret(stage, archive.read("portal.db"))
            source = sqlite3.connect(stage)
            try:
                if (
                    source.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or source.execute("PRAGMA foreign_key_check").fetchone()
                    or source.execute(
                        "SELECT version_num FROM alembic_version"
                    ).fetchone()[0]
                    != db.execute("SELECT version_num FROM alembic_version").fetchone()[
                        0
                    ]
                ):
                    raise ValueError("备份版本或完整性无效")
                for (user,) in source.execute(
                    "SELECT user FROM user_roles WHERE role!='user'"
                ):
                    key = otp_path(user)
                    if not key.is_file() or key.read_bytes() != archive.read(key.name):
                        raise ValueError("管理员 MFA 不匹配，请使用停机恢复")
                if not source.execute(
                    "SELECT 1 FROM user_roles WHERE role='super_admin'"
                ).fetchone():
                    raise ValueError("备份缺少管理员")
                folder = Path(os.getenv("BACKUP_DIR", str(DATA / "backups")))
                folder.mkdir(exist_ok=True, mode=0o700)
                secret(
                    folder / ("before-restore-" + os.urandom(8).hex() + ".enc"),
                    backup(),
                )
                for table in ("sessions", "tokens", "attempts", *reversed(tables)):
                    db.execute("DELETE FROM " + table)
                for table in tables:
                    data = source.execute("SELECT * FROM " + table)
                    marks = ",".join("?" for _ in data.description)
                    db.executemany(f"INSERT INTO {table} VALUES({marks})", data)
                db.execute(
                    "UPDATE provision_jobs SET status='held',error='恢复后请核对远端再重试' WHERE status='pending'"
                )
                audit(db, None, "restore", "platform")
            finally:
                source.close()


if __name__ == "__main__":
    main()
