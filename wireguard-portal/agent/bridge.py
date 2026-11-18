#!/usr/bin/python3 -I
"""Single privileged entry point; stdin/stdout JSON. Installed root-owned."""

import fcntl
import hashlib
import json
import os
import re
import runpy
import sys
import time

UUID = r"[0-9a-f]{32}"
PEER = r"user[0-9]{2,16}"
HASH = r"[0-9a-f]{64}"
MUTATIONS = {"create", "adopt", "enable", "disable", "rotate", "delete"}


class Rejected(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise Rejected(reason)


def fingerprint(user):
    return hashlib.sha256(user["public"].encode()).hexdigest()


def dispatch(cli, state, q):
    require(
        isinstance(q, dict) and all(isinstance(v, str) for v in q.values()),
        "invalid request",
    )
    action = q.get("action")
    fields = {"action"}
    if action in MUTATIONS or action == "result":
        fields.add("key")
    if action in MUTATIONS or action == "export":
        fields.add("device")
        if action == "create":
            fields.add("label")
        else:
            fields.update(("peer", "fingerprint"))
            require(re.fullmatch(HASH, q.get("fingerprint", "")), "invalid fingerprint")
    if action == "export":
        fields.add("mode")
    require(set(q) == fields, "unexpected arguments")
    users = state["users"]
    ledger = state.setdefault("portal_operations", {})
    if action == "inventory":
        snap = cli["snapshot"](state)
        for row in snap["rows"]:
            u = users[row["name"]]
            row.update(device=u.get("portal_device"), fingerprint=fingerprint(u))
        used = {u.get("host", int(k[4:]) + 1) for k, u in users.items()}
        snap.update(
            version=1,
            live=cli["LIVE"].exists(),
            capacity=cli["CAPACITY"],
            free=len(set(range(4, 255)) - used),
        )
        return snap
    if action == "audit":
        return [{"key": k, **v} for k, v in list(ledger.items())[-200:]]
    key = q.get("key", "")
    if action == "result":
        require(re.fullmatch(UUID, key), "invalid key")
        return ledger.get(key)
    device = q.get("device", "")
    require(re.fullmatch(UUID, device), "invalid device")
    require(action in MUTATIONS | {"export"}, "invalid action")
    signature = hashlib.sha256(json.dumps(q, sort_keys=True).encode()).hexdigest()
    if action in MUTATIONS:
        require(re.fullmatch(UUID, key), "invalid key")
        if key in ledger:
            require(ledger[key]["signature"] == signature, "key conflict")
            return ledger[key]
    name = q.get("peer", "")
    if action == "create":
        require(cli["LIVE"].exists(), "interface down")
        require(
            all(u.get("portal_device") != device for u in users.values()),
            "already bound",
        )
        require(isinstance(q.get("label"), str), "invalid label")
        label = cli["customer_name"](users, label=q["label"])
        try:
            name = cli["allocate_peer"](state, label, reserved_hosts=(2, 3), first_id=3)
        except cli["CustomerError"]:
            raise Rejected("no available address") from None
        users[name]["portal_device"] = device
    else:
        require(re.fullmatch(PEER, name) and name in users, "peer missing")
        u = users[name]
        require(q.get("fingerprint") == fingerprint(u), "stale fingerprint")
        if action == "adopt":
            require(
                not u.get("portal_device")
                and name not in ("user01", "user02")
                and u.get("host", int(name[4:]) + 1) > 3
                and all(r.get("portal_device") != device for r in users.values()),
                "protected peer",
            )
            u["portal_device"] = device
        else:
            require(u.get("portal_device") == device, "foreign peer")
        if action == "export":
            require(
                u["enabled"] and q.get("mode") in ("global", "proxy"), "invalid export"
            )
            return {"config": cli["profile"](state, name, q["mode"])}
        if action == "rotate":
            u.update(cli["keys"]())
        if action in ("disable", "enable"):
            u["enabled"] = action == "enable"
        if action in ("disable", "rotate", "adopt"):
            u.pop("ticket", None)
        if action == "delete":
            require(not u["enabled"], "disable first")
            state.setdefault("last_id", max(int(k[4:]) for k in users))
            del users[name]
    result = dict(
        signature=signature,
        action=action,
        device=device,
        peer=name,
        time=int(time.time()),
    )
    if name in users:
        result.update(
            fingerprint=fingerprint(users[name]),
            address=cli["addresses"](name, users[name]),
            enabled=users[name]["enabled"],
        )
    ledger[key] = result
    cli["apply_state"](state)
    return result


def main():
    os.umask(0o077)
    require(len(sys.argv) == 1 and os.geteuid() == 0, "invalid invocation")
    cli = runpy.run_path("/usr/local/lib/wg-portal/manager.py")
    with (cli["ROOT"] / ".wgvps-users.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in (cli["STATE"], cli["PENDING"], cli["CONF"]):
            if path.exists():
                require(
                    not path.is_symlink()
                    and path.stat().st_uid == 0
                    and path.stat().st_mode & 0o077 == 0,
                    "unsafe permissions",
                )
        if cli["PENDING"].exists():
            cli["reconcile"](json.loads(cli["PENDING"].read_text()))
        request = json.loads(sys.stdin.read(2049))
        action = request.get("action")
        import syslog

        if action not in MUTATIONS | {"export", "result", "inventory", "audit"}:
            raise Rejected("invalid operation")
        try:
            result = dispatch(cli, json.loads(cli["STATE"].read_text()), request)
        except Exception:
            syslog.syslog(syslog.LOG_WARNING, "wg-portal denied or failed: " + action)
            raise
        if action in MUTATIONS | {"export"}:
            syslog.syslog(syslog.LOG_INFO, "wg-portal completed: " + action)
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Rejected as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(3)
    except Exception:
        sys.exit(1)
