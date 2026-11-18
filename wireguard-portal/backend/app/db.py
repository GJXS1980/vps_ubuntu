import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL

DATA = Path(os.environ.get("PORTAL_DATA", "./data")).resolve()
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
engine = create_engine(
    URL.create("sqlite", database=str(DATA / "portal.db")), connect_args={"timeout": 45}
)


@event.listens_for(engine, "connect")
def setup(conn, record):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")


@contextmanager
def transaction(write=True):
    conn = engine.raw_connection()
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def now():
    return int(time.time())


def uid():
    return uuid.uuid4().hex


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def audit(db, actor, action, target):
    db.execute(
        "INSERT INTO audit_logs(actor,action,target,time) VALUES(?,?,?,?)",
        (actor, action, str(target), now()),
    )
