from alembic import op

revision = "001"
down_revision = None


def upgrade():
    for statement in SCHEMA.strip().split(";"):
        if statement.strip():
            op.execute(statement)


SCHEMA = """
CREATE TABLE roles(name TEXT PRIMARY KEY);
INSERT INTO roles VALUES ('user'),('admin'),('super_admin');
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
email TEXT NOT NULL UNIQUE COLLATE NOCASE, hash TEXT NOT NULL, status TEXT NOT NULL,
verified INTEGER NOT NULL DEFAULT 0, quota INTEGER NOT NULL DEFAULT 1, otp_step INTEGER DEFAULT -1);
CREATE TABLE user_roles(user INTEGER PRIMARY KEY REFERENCES users(id), role TEXT NOT NULL REFERENCES roles(name));
CREATE TABLE sessions(digest TEXT PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE INDEX session_owner ON sessions(user);
CREATE TABLE tokens(digest TEXT PRIMARY KEY, purpose TEXT NOT NULL, user INTEGER REFERENCES users(id), expires INTEGER NOT NULL);
CREATE TABLE attempts(subject TEXT PRIMARY KEY, count INTEGER NOT NULL, until INTEGER NOT NULL);
CREATE TABLE vpn_servers(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, address TEXT UNIQUE NOT NULL);
CREATE TABLE devices(id TEXT PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), server INTEGER NOT NULL REFERENCES vpn_servers(id),
label TEXT NOT NULL, status TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}');
CREATE UNIQUE INDEX device_name ON devices(user,label) WHERE status != 'retired';
CREATE TABLE wireguard_peers(device TEXT PRIMARY KEY REFERENCES devices(id), server INTEGER NOT NULL REFERENCES vpn_servers(id),
peer TEXT NOT NULL, fingerprint TEXT NOT NULL, address TEXT NOT NULL, UNIQUE(server,peer));
CREATE TABLE provision_jobs(id TEXT PRIMARY KEY, device TEXT NOT NULL REFERENCES devices(id), request TEXT NOT NULL,
status TEXT NOT NULL, tries INTEGER NOT NULL DEFAULT 0, due INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX one_job ON provision_jobs(device) WHERE status='pending';
CREATE INDEX due_jobs ON provision_jobs(status,due);
CREATE TABLE download_events(id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), device TEXT NOT NULL REFERENCES devices(id),
mode TEXT NOT NULL, format TEXT NOT NULL, time INTEGER NOT NULL);
CREATE TABLE audit_logs(id INTEGER PRIMARY KEY, actor INTEGER REFERENCES users(id), action TEXT NOT NULL, target TEXT NOT NULL, time INTEGER NOT NULL);
CREATE TABLE app_settings(name TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT INTO app_settings VALUES ('registration','review'),('quota','1');
"""
