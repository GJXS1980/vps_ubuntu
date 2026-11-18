#!/usr/bin/env python3
"""Manage the 25 wgvps peers on Ubuntu. All state and exports contain secrets."""
import argparse
import configparser
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path("/etc/wireguard")
CONF = ROOT / "wgvps.conf"
STATE = ROOT / "wgvps-users.json"
PENDING = ROOT / "wgvps-pending.json"
LEGACY = ROOT / "windows-vps.conf"
LIVE = Path("/sys/class/net/wgvps")
USERS = tuple(f"user{i:02}" for i in range(1, 26))


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
                          stdout=subprocess.PIPE).stdout.strip()


def public(key):
    return run("wg", "pubkey", data=key + "\n")


def keys():
    private = run("wg", "genkey")
    return dict(private=private, public=public(private), psk=run("wg", "genpsk"))


def addresses(user):
    host = int(user[4:]) + 1
    return f"10.66.77.{host}/32, fd42:66:77::{host:x}/128"


def section(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser


def initial(endpoint):
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
             for u in USERS}
    return dict(base=base.rstrip(), server_public=server_pub, endpoint=endpoint, users=users)


def server_config(state):
    peers = [state["base"]]
    for name, user in state["users"].items():
        if user["enabled"]:
            peers.append(f"[Peer]\n# {name}\nPublicKey = {user['public']}\n"
                         f"PresharedKey = {user['psk']}\nAllowedIPs = {addresses(name)}")
    return "\n\n".join(peers) + "\n"


def profile(state, name):
    user = state["users"][name]
    global_mode = user["mode"] == "global"
    dns = "DNS = 1.1.1.1, 1.0.0.1\n" if global_mode else ""
    routes = "0.0.0.0/0, ::/0" if global_mode else "10.66.77.1/32"
    return (f"[Interface]\nPrivateKey = {user['private']}\nAddress = {addresses(name)}\n"
            f"{dns}MTU = 1380\n\n[Peer]\nPublicKey = {state['server_public']}\n"
            f"PresharedKey = {user['psk']}\nEndpoint = {state['endpoint']}:51820\n"
            f"AllowedIPs = {routes}\nPersistentKeepalive = 25\n")


def reconcile(state):
    # Leave PENDING in place until both persistent and live state agree.
    atomic(CONF, server_config(state))
    if LIVE.exists():
        stripped = run("wg-quick", "strip", str(CONF))
        run("wg", "syncconf", "wgvps", "/dev/stdin", data=stripped + "\n")
    if state["users"]["user01"]["enabled"]:
        atomic(LEGACY, profile(state, "user01"))
    else:
        LEGACY.unlink(missing_ok=True)
    PENDING.replace(STATE)


def manage(args):
    if PENDING.exists():
        reconcile(json.loads(PENDING.read_text()))
    if args.command == "init":
        if STATE.exists():
            state = json.loads(STATE.read_text())
            if state["endpoint"] != args.endpoint:
                raise ValueError("已安装的 Endpoint 与参数不一致")
        else:
            state = initial(args.endpoint)
    else:
        state = json.loads(STATE.read_text())
        if args.command == "list":
            for name, user in state["users"].items():
                print(name, "enabled" if user["enabled"] else "disabled", user["mode"])
            return
        user = state["users"][args.user]
        if args.command in ("export", "qr"):
            if not user["enabled"]:
                raise ValueError("该用户已禁用")
            config = profile(state, args.user)
            if args.command == "export":
                sys.stdout.write(config)
            else:
                subprocess.run(["qrencode", "-t", "ANSIUTF8"], input=config, text=True, check=True)
            return
        if args.command == "rotate":
            user.update(keys())
        elif args.command == "mode":
            user["mode"] = args.mode
        else:
            user["enabled"] = args.command == "enable"
    atomic(PENDING, json.dumps(state))
    reconcile(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="安装或恢复").add_argument("endpoint")
    commands.add_parser("list", help="查看 25 个用户的状态与模式")
    for name, desc in (("enable", "启用"), ("disable", "禁用"), ("rotate", "轮换密钥"),
                       ("export", "输出配置到标准输出"), ("qr", "显示终端二维码"),
                       ("mode", "选择客户端路由模式")):
        sub = commands.add_parser(name, help=desc)
        sub.add_argument("user", choices=USERS, metavar="user01..user25")
        if name == "mode":
            sub.add_argument("mode", choices=("global", "proxy"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "请使用 sudo/root\n")
    os.umask(0o077)
    with (ROOT / ".wgvps-users.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manage(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, configparser.Error, subprocess.CalledProcessError) as exc:
        # Parser errors may contain configuration lines with keys.
        if isinstance(exc, configparser.Error):
            sys.exit("配置文件格式不受支持")
        sys.exit(str(exc))
