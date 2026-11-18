#!/usr/bin/env python3
"""Manage wgvps peers on Ubuntu. All state and exports contain secrets."""
import argparse
import configparser
import fcntl
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path("/etc/wireguard")
CONF = ROOT / "wgvps.conf"
STATE = ROOT / "wgvps-users.json"
PENDING = ROOT / "wgvps-pending.json"
LEGACY = ROOT / "windows-vps.conf"
LIVE = Path("/sys/class/net/wgvps")
CAPACITY = 253


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        tmp = Path(file.name)
        try:
            file.write(data.encode())
            file.flush()
            os.fsync(file.fileno())
            file.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def run(*args, data=None):
    return subprocess.run(args, input=data, text=True, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def public(key):
    return run("wg", "pubkey", data=key + "\n")


def keys():
    private = run("wg", "genkey")
    return dict(private=private, public=public(private), psk=run("wg", "genpsk"))


def addresses(user, record=None):
    host = (record or {}).get("host", int(user[4:]) + 1)
    return f"10.66.77.{host}/32, fd42:66:77::{host:x}/128"


def section(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser


def initial(endpoint, count):
    if not 1 <= count <= CAPACITY:
        raise ValueError("初始客户数量须为 1 至 253")
    server = CONF.read_text()
    base, marker, peer = server.partition("[Peer]")
    if not marker or "[Peer]" in peer:
        raise ValueError("仅支持从原版单客户端配置迁移")
    # Interface hooks repeat in wg-quick format. Parse only its scalar settings.
    interface = section("\n".join(line for line in base.splitlines()
                                  if line.partition("=")[0].strip() not in
                                  {"PostUp", "PostDown", "PreUp", "PreDown"}))["Interface"]
    previous = section(marker + peer)["Peer"]
    client = section(LEGACY.read_text())
    first = dict(private=client["Interface"]["PrivateKey"],
                 public=previous["PublicKey"], psk=previous["PresharedKey"])
    server_pub = public(interface["PrivateKey"])
    if not (public(first["private"]) == first["public"]
            and client["Peer"]["PublicKey"] == server_pub
            and client["Peer"]["PresharedKey"] == first["psk"]
            and client["Peer"]["Endpoint"] == endpoint + ":51820"
            and client["Interface"]["Address"] == previous["AllowedIPs"] == addresses("user01")
            and interface["Address"] == "10.66.77.1/24, fd42:66:77::1/64"
            and interface["ListenPort"] == "51820"
            and not interface.getboolean("SaveConfig", fallback=False)):
        raise ValueError("现有配置与原版单客户端参数或指定 Endpoint 不匹配")
    users = {u: dict(first if u == "user01" else keys(), enabled=True, mode="global")
             for u in (f"user{i:02}" for i in range(1, count + 1))}
    return dict(base=base.rstrip(), server_public=server_pub, endpoint=endpoint, users=users)


def server_config(state):
    peers = [state["base"]]
    for name, user in state["users"].items():
        if user["enabled"]:
            peers.append(f"[Peer]\n# {name}\nPublicKey = {user['public']}\n"
                         f"PresharedKey = {user['psk']}\nAllowedIPs = {addresses(name, user)}")
    return "\n\n".join(peers) + "\n"


def profile(state, name, mode=None):
    user = state["users"][name]
    global_mode = (mode or user["mode"]) == "global"
    dns = "DNS = 1.1.1.1, 1.0.0.1\n" if global_mode else ""
    routes = "0.0.0.0/0, ::/0" if global_mode else "10.66.77.1/32"
    return (f"[Interface]\nPrivateKey = {user['private']}\nAddress = {addresses(name, user)}\n"
            f"{dns}MTU = 1380\n\n[Peer]\nPublicKey = {state['server_public']}\n"
            f"PresharedKey = {user['psk']}\nEndpoint = {state['endpoint']}:51820\n"
            f"AllowedIPs = {routes}\nPersistentKeepalive = 25\n")


def bundle(state, name):
    return {"name": name, "profiles": {mode: profile(state, name, mode)
                                       for mode in ("global", "proxy")}}


def reconcile(state):
    # Leave PENDING in place until both persistent and live state agree.
    config = server_config(state)
    if LIVE.exists():
        # Parse the candidate under its real interface basename before publishing it.
        with tempfile.TemporaryDirectory(dir=CONF.parent) as stage:
            candidate = Path(stage) / CONF.name
            atomic(candidate, config)
            stripped = run("wg-quick", "strip", str(candidate))
            run("wg", "syncconf", "wgvps", "/dev/stdin", data=stripped + "\n")
    atomic(CONF, config)
    if state["users"].get("user01", {}).get("enabled"):
        atomic(LEGACY, profile(state, "user01"))
    else:
        LEGACY.unlink(missing_ok=True)
    PENDING.replace(STATE)


def apply_state(state):
    previous = STATE.read_text() if STATE.exists() else None
    atomic(PENDING, json.dumps(state))
    try:
        reconcile(state)
    except (OSError, ValueError, subprocess.CalledProcessError):
        if previous is not None:
            # Keep the rollback intent durable even when the interface is unavailable.
            atomic(PENDING, previous)
            try:
                reconcile(json.loads(previous))
            except (OSError, ValueError, subprocess.CalledProcessError):
                raise CustomerError("同步失败，已保留回滚记录。请检查接口后重新查询") from None
            raise CustomerError("同步失败，已恢复上一次客户配置") from None
        raise


class CustomerError(ValueError):
    pass


def validate_label(label):
    label = label.strip()
    if not 1 <= len(label) <= 40 or not all(c.isalnum() or c in " _-" for c in label):
        raise CustomerError("名称须为 1 至 40 个字，可用中文、字母、数字、空格、下划线或短横线")
    return label


def customer_name(users, exclude=None, label=None):
    label = validate_label(sys.stdin.read(257) if label is None else label)
    if any(label.casefold() in (key.casefold(), u.get("label", key).casefold())
           for key, u in users.items() if key != exclude):
        raise CustomerError("客户名称已存在")
    return label


def customer_status(state, window=180, warnings=None):
    try:
        output = run("wg", "show", "wgvps", "latest-handshakes")
        handshakes = {key: int(stamp) for key, stamp in (row.split() for row in output.splitlines())}
    except (OSError, subprocess.CalledProcessError, ValueError):
        handshakes = {}
        if warnings is not None:
            warnings.append("握手读取失败")
    now = int(time.time())
    rows = []
    for name, user in state["users"].items():
        stamp = handshakes.get(user["public"])
        age = now - stamp if stamp and 0 < stamp <= now else None
        if not user["enabled"]:
            status = "disabled"
        elif stamp == 0:
            status = "never"
        elif age is None:
            status = "unknown"
        else:
            status = "online" if age <= window else "offline"
        rows.append(dict(name=name, label=user.get("label", name), status=status,
                         address=addresses(name, user).split("/")[0], age=age))
    return rows


def online_window():
    window_file = STATE.parent / "wgvps-online-window"
    window = int(window_file.read_text().strip()) if window_file.exists() else 180
    if not 1 <= window <= 86400:
        raise CustomerError("在线窗口须为 1 至 86400 秒")
    return window


def snapshot(state):
    window = online_window()
    warnings = []
    rows = customer_status(state, window, warnings)
    metrics = {}
    for field in ("endpoints", "transfer"):
        try:
            for line in run("wg", "show", "wgvps", field).splitlines():
                key, *values = line.split()
                peer = metrics.setdefault(key, {})
                if field == "endpoints":
                    endpoint, = values
                    peer["endpoint"] = None if endpoint == "(none)" else endpoint
                else:
                    rx, tx = map(int, values)
                    peer.update(rx=rx, tx=tx)
        except (OSError, ValueError, subprocess.CalledProcessError):
            warnings.append(field + " 读取失败")
    for row in rows:
        user = state["users"][row["name"]]
        row.update(metrics.get(user["public"], {}))
        row.update(enabled=user["enabled"], group=user.get("group",""), created=user.get("created"),
                   fingerprint=hashlib.sha256(user["public"].encode()).hexdigest()[:16])
    return dict(rows=rows, groups=state.get("groups",{}), window=window, time=int(time.time()),
                warning="；".join(warnings))


def edit(state, args, data):
    groups = state.setdefault("groups", {})
    users = state["users"]
    action = args.command
    group = data.get("group", "")
    if not isinstance(group, str) or (group and group not in groups):
        raise CustomerError("分组不存在，请刷新")
    if action.startswith("group-"):
        if action != "group-create" and not group:
            raise CustomerError("未分组不能修改")
        if action == "group-delete":
            if any(u.get("group")==group for u in users.values()):
                raise CustomerError("仅可删除空分组")
            args.targets, args.labels = [group], [groups[group]]
            del groups[group]
        else:
            label = validate_label(data.get("label",""))
            if label == "未分组" or any(label.casefold()==v.casefold() for k,v in groups.items()
                                      if action=="group-create" or k!=group):
                raise CustomerError("分组名称已存在")
            if action=="group-create":
                group=secrets.token_hex(8)
            groups[group]=label
            args.targets, args.labels = [group], [label]
        atomic(STATE,json.dumps(state))
        return
    ids = data.get("ids", [])
    if not isinstance(ids,list) or not 1 <= len(ids) <= CAPACITY or not all(
            isinstance(k,str) and re.fullmatch(r"user[0-9]{2,16}",k) for k in ids):
        raise CustomerError("客户选择无效")
    ids=list(dict.fromkeys(ids))
    args.targets=ids
    args.labels=[users.get(k,{}).get("label",k) for k in ids]
    missing=[k for k in ids if k not in users]
    valid=[k for k in ids if k in users]
    errors=[k+" 已不存在" for k in missing]
    if action=="batch-export":
        denied=[k for k in valid if not users[k]["enabled"]]
        if missing or denied:
            raise CustomerError("无法导出："+"，".join(errors+[k+" 已禁用" for k in denied]))
        print(json.dumps([bundle(state,k) for k in valid]))
        return
    changed = False
    for k in valid:
        if action=="batch-group":
            changed |= users[k].get("group","") != group
            users[k]["group"]=group
        else:
            changed |= users[k]["enabled"] != (action=="batch-enable")
            users[k]["enabled"]=action=="batch-enable"
            if not users[k]["enabled"]:
                users[k].pop("ticket",None)
    if changed:
        if action=="batch-group":
            atomic(STATE,json.dumps(state))
        else:
            apply_state(state)
    args.outcome="部分失败" if errors and valid else "失败" if errors else "成功"
    args.reason="客户已不存在" if errors else ""
    print(json.dumps(dict(count=len(valid), errors=errors)))


EDIT_COMMANDS=("group-create","group-rename","group-delete","batch-enable","batch-disable","batch-group","batch-export")


def manage(args):
    if PENDING.exists():
        reconcile(json.loads(PENDING.read_text()))
    if args.command == "init":
        if STATE.exists():
            state = json.loads(STATE.read_text())
            if state["endpoint"] != args.endpoint:
                raise ValueError("已安装的 Endpoint 与参数不一致")
        else:
            state = initial(args.endpoint, args.count)
    else:
        state = json.loads(STATE.read_text())
        if args.command == "snapshot":
            print(json.dumps(snapshot(state)))
            return
        if args.command == "audit":
            print(json.dumps(read_audit()))
            return
        if args.command in EDIT_COMMANDS:
            data=json.loads(sys.stdin.read(16385))
            if not isinstance(data,dict) or not all(isinstance(data.get(k,""),str) for k in ("group","label")):
                raise CustomerError("操作参数无效")
            edit(state,args,data)
            return
        if args.command == "status":
            print(json.dumps(customer_status(state,online_window())))
            return
        if args.command == "list":
            for name, user in state["users"].items():
                print(name, "enabled" if user["enabled"] else "disabled", user["mode"], user.get("label", name))
            return
        if args.command == "bundles":
            print(json.dumps([bundle(state, name) for name, user in state["users"].items()
                              if user["enabled"]]))
            return
        if args.command == "redeem":
            token = sys.stdin.readline(128).strip()
            digest = hashlib.sha256(token.encode()).hexdigest()
            for name, user in state["users"].items():
                ticket = user.get("ticket")
                if (user["enabled"] and ticket and ticket["expires"] > time.time()
                        and hmac.compare_digest(digest, ticket["digest"])):
                    del user["ticket"]
                    atomic(STATE, json.dumps(state))
                    print(json.dumps(bundle(state, name)))
                    return
            raise ValueError("领取码无效、已用或已过期")
        users = state["users"]
        if args.command in ("add","add-group"):
            group=""
            if args.command=="add-group":
                data=json.loads(sys.stdin.read(1025))
                if not isinstance(data,dict) or not all(isinstance(data.get(k),str) for k in ("group","label")):
                    raise CustomerError("新增参数无效")
                group=data["group"]
                if group and group not in state.get("groups",{}):
                    raise CustomerError("分组不存在")
                label=customer_name(users,label=data["label"])
            else:
                label = customer_name(users)
            used = {u.get("host", int(k[4:]) + 1) for k, u in users.items()}
            host = next((h for h in range(2, 255) if h not in used), None)
            if host is None:
                raise CustomerError("当前网段最多容纳 253 个客户")
            number = state.get("last_id", max((int(k[4:]) for k in users), default=0)) + 1
            reserved = {u.get("label", k).casefold() for k, u in users.items()}
            while f"user{number:02}" in reserved:
                number += 1
            name = f"user{number:02}"
            state["last_id"] = number
            users[name] = dict(keys(), enabled=True, mode="global", label=label, host=host,
                               group=group, created=int(time.time()))
            args.targets, args.labels=[name],[label]
            apply_state(state)
            print(name)
            return
        if args.user not in users:
            raise CustomerError("找不到该客户，请刷新管理页")
        user = users[args.user]
        args.targets, args.labels=[args.user],[user.get("label",args.user)]
        if args.command == "rename":
            user["label"] = customer_name(users, args.user)
            args.labels = [user["label"]]
            atomic(STATE, json.dumps(state))
            return
        if args.command in ("issue", "bundle", "export", "qr") and not user["enabled"]:
            raise ValueError("该用户已禁用")
        if args.command == "bundle":
            print(json.dumps(bundle(state, args.user)))
            return
        if args.command == "issue":
            token = secrets.token_urlsafe(24)
            user["ticket"] = {"digest": hashlib.sha256(token.encode()).hexdigest(),
                              "expires": int(time.time()) + 600}
            atomic(STATE, json.dumps(state))
            print(token)
            return
        if args.command in ("export", "qr"):
            config = profile(state, args.user, getattr(args, "profile_mode", None))
            if args.command == "export":
                sys.stdout.write(config)
            else:
                subprocess.run(["qrencode", "-t", "ANSIUTF8"], input=config, text=True, check=True)
            return
        if args.command in ("rotate", "disable"):
            user.pop("ticket", None)
        if args.command == "delete":
            if user["enabled"]:
                raise CustomerError("请先禁用客户，再确认删除")
            state.setdefault("last_id", max(int(k[4:]) for k in users))
            del users[args.user]
        elif args.command == "rotate":
            user.update(keys())
        elif args.command == "mode":
            user["mode"] = args.mode
        else:
            user["enabled"] = args.command == "enable"
    apply_state(state)


def read_audit():
    records=[]
    for filename in ("wgvps-audit.jsonl.1","wgvps-audit.jsonl"):
        path=STATE.parent / filename
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
    return list(reversed(records[-200:]))


def audited(args):
    if args.command not in (*EDIT_COMMANDS,"add","add-group","rename","enable","disable","delete","rotate","mode"):
        return manage(args)
    outcome,reason="成功",""
    try:
        manage(args)
        outcome=getattr(args,"outcome",outcome)
        reason=getattr(args,"reason","")
    except Exception as exc:
        outcome="失败"
        reason=str(exc) if isinstance(exc,CustomerError) else "操作未完成，请检查服务状态"
        raise
    finally:
        path=STATE.parent / "wgvps-audit.jsonl"
        if path.exists() and path.stat().st_size >= 1024*1024:
            path.replace(path.with_suffix(".jsonl.1"))
        record=dict(time=int(time.time()), action=args.command, targets=getattr(args,"targets",[]),
                    labels=getattr(args,"labels",[]), result=outcome, reason=reason,
                    source="Web admin" if os.environ.get("SUDO_USER")=="wgvps-web" else "CLI")
        with path.open("a",encoding="utf-8") as log:
            log.write(json.dumps(record,ensure_ascii=False)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="安装或恢复")
    init.add_argument("endpoint")
    init.add_argument("--count", type=int, default=1)
    commands.add_parser("add", help="新增客户，从标准输入读取名称")
    for command in (*EDIT_COMMANDS,"snapshot","audit","add-group"):
        commands.add_parser(command)
    commands.add_parser("status", help="查看客户的连接状态与最近握手")
    commands.add_parser("list", help="列出客户编号、状态、模式和名称")
    commands.add_parser("redeem", help="从标准输入读取一次性领取码")
    commands.add_parser("bundles", help="导出全部已启用用户的双模式配置")
    for name, desc in (("bundle", "生成用户的双模式配置"), ("issue", "签发十分钟一次性领取码"), ("enable", "启用"), ("disable", "禁用"), ("rotate", "轮换密钥"),
                       ("export", "输出配置到标准输出"), ("qr", "显示终端二维码"),
                       ("mode", "选择客户端路由模式"), ("rename", "从标准输入读取新名称"),
                       ("delete", "删除已禁用客户")):
        sub = commands.add_parser(name, help=desc)
        sub.add_argument("user", metavar="客户编号")
        if name in ("export", "qr"):
            sub.add_argument("--profile-mode", choices=("global", "proxy"))
        if name == "mode":
            sub.add_argument("mode", choices=("global", "proxy"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "请使用 sudo/root\n")
    os.umask(0o077)
    with (ROOT / ".wgvps-users.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        audited(args)


if __name__ == "__main__":
    try:
        main()
    except CustomerError as exc:
        print(exc, file=sys.stderr)
        sys.exit(3)
    except (ValueError, KeyError, OSError, configparser.Error, subprocess.CalledProcessError) as exc:
        # Parser errors may contain configuration lines with keys.
        if isinstance(exc, configparser.Error):
            sys.exit("配置文件格式不受支持")
        sys.exit(str(exc))
