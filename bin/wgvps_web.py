"""WSGI application for private HTTPS distribution of WireGuard profiles."""
import base64
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import subprocess
import zipfile
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

MANAGER = "/usr/local/sbin/wgvps-users"
STYLE = """
*{box-sizing:border-box}
:root{color-scheme:light;--ink:#182b3d;--muted:#526777;--line:#d6e0e5;--accent:#006963}
body{margin:0;background:#f3f6f8;color:var(--ink);font:16px/1.55 "Inter","Segoe UI","Microsoft YaHei",sans-serif}
header{background:#143748;color:white}nav,main{max-width:1040px;margin:auto;padding:0 24px}
nav{display:flex;align-items:center;gap:20px;min-height:60px}nav strong{letter-spacing:.02em;margin-right:auto}
nav a{color:#dfebee;text-decoration:none;padding:18px 3px 14px;border-bottom:4px solid transparent}
nav a[aria-current=page]{color:white;border-color:#67ddbd}main{padding-top:24px;padding-bottom:48px}
h1{font-size:clamp(26px,4vw,36px);letter-spacing:-.03em;margin:0 0 18px}h2{font-size:20px}
section,form,.sheet{background:white;border:1px solid var(--line);padding:16px;border-radius:10px;margin:10px 0}
section form,details form{border:0;margin:0;padding:12px 0 0}
label{display:block;font-weight:600;font-size:.9rem}input,select,button,a.download{font:inherit;border-radius:6px;padding:8px 12px}
input,select{border:1px solid #a8bac2;background:white;color:var(--ink);max-width:100%}input{width:100%}
button,a.download{background:var(--accent);color:white;border:0;cursor:pointer;margin:4px 4px 4px 0}
button:hover,a.download:hover{background:#00544f}a.download{display:inline-block;text-decoration:none}
a,summary{color:var(--accent)}summary{cursor:pointer}img{display:block;max-width:100%;height:auto}
:focus-visible{outline:3px solid #007abc;outline-offset:2px}
.tools,.filters{display:flex;align-items:end;gap:12px;flex-wrap:wrap}.tools form{margin:0}.tools form:first-child{flex:1}
.tools form,.filters{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.tools label,.filters label:first-child{flex:1;min-width:140px}
.filters label input,.filters label select,.tools input{display:block;margin-top:4px}.filters button,.tools button{margin:0}
.stats{display:flex;gap:24px;flex-wrap:wrap;color:var(--muted);margin:20px 0 12px}.stats b{font:700 1.4rem/1.2 "Segoe UI",sans-serif;color:var(--ink);margin-left:6px}
.hint,small{color:var(--muted);font-size:.9rem}small{display:block}
.sheet{padding:0;overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}
th,td{padding:12px 16px;border-bottom:1px solid var(--line)}th{font-size:.85rem;background:#eaf0f3;color:#415565}
tbody tr:last-child td{border:0}tbody tr:hover{background:#f5faf9}.ip{font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;border-radius:20px;background:#edf1f4;color:#475866;padding:2px 9px;font-size:.85rem}
.online{background:#d8f3e7;color:#146048}.unknown{background:#fff0cf;color:#74540e}.disabled{background:#f1e9ee;color:#67465b}
.client summary{font-weight:600}.client .pill{margin-left:8px}.client form label{margin-top:10px}
@media(max-width:640px){nav,main{padding-left:12px;padding-right:12px}nav{gap:12px}.tools{align-items:stretch}
.tools form:first-child{flex-basis:100%}.stats{gap:14px}.sheet table{min-width:560px}.filters{gap:8px}
.filters label:first-child{flex-basis:100%}th,td{padding:10px}.client summary{overflow-wrap:anywhere}}
"""


def manager(*args, data=b""):
    return subprocess.run(["/usr/bin/sudo", "-n", MANAGER, *args], input=data,
                          capture_output=True, timeout=20, check=True).stdout


def profiles(bundle, csrf=None):
    name = bundle["name"]
    cards = []
    for mode, title in (("global", "全局模式"), ("proxy", "代理模式")):
        config = bundle["profiles"][mode].encode()
        png = subprocess.run(["/usr/bin/qrencode", "-t", "PNG", "-o", "-"], input=config,
                             capture_output=True, timeout=5, check=True).stdout
        image = base64.b64encode(png).decode()
        filename = f"{name}-{mode}.conf"
        if csrf is None:
            content = base64.b64encode(config).decode()
            download = (f'<a class="download" download="{filename}" '
                        f'href="data:application/octet-stream;base64,{content}">下载 {filename}</a>')
        else:
            download = (f'<form method="post" action="/admin"><input type="hidden" name="csrf" value="{csrf}">'
                        f'<input type="hidden" name="user" value="{name}">'
                        f'<button name="action" value="download-{mode}">下载 {filename}</button></form>')
        cards.append(f'<section><h2>{title}</h2>{download}'
                     f'<details><summary>显示导入二维码</summary><img src="data:image/png;base64,{image}" '
                     f'alt="{title}配置二维码"></details></section>')
    return ("<p>请在离开页面前保存两份配置。导入同一台设备，先停用当前隧道，再启用另一份。"
            "代理模式下，在指定应用中设置 SOCKS5 地址 10.66.77.1，端口 1080。</p>" + "".join(cards))


CONNECTION = {"online": "在线", "offline": "离线", "never": "尚无握手",
              "unknown": "状态未知", "disabled": "已禁用"}


def customer_directory(rows, query, csrf, path):
    status_page = path == "/admin/status"
    filters = parse_qs(query, max_num_fields=8)
    term = filters.get("q", [""])[0].strip()
    selected = filters.get("status", [""])[0]
    focus = filters.get("customer", [""])[0]
    options = ['<option value="">全部状态</option>']
    for key, title in CONNECTION.items():
        mark = " selected" if key == selected else ""
        options.append(f'<option value="{key}"{mark}>{title}</option>')
    form = (f'<form class="filters" method="get" action="{path}"><label>查找客户'
            f'<input name="q" placeholder="名称、编号或 IPv4" value="{escape(term)}"></label>'
            f'<label>连接状态<select name="status">{"".join(options)}</select></label>'
            f'<button>查询 / 刷新</button><a href="{path}">重置</a></form>')
    cards = []
    hidden = f'<input type="hidden" name="csrf" value="{csrf}">'
    for row in rows:
        name, label, address = (row[k] for k in ("name", "label", "address"))
        status = row["status"]
        if selected and selected != status:
            continue
        if not any(term.casefold() in value.casefold() for value in (name, label, address)):
            continue
        name = escape(name)
        caption = name if label == name else f"{escape(label)}（{name}）"
        age = row["age"]
        handshake = "—" if age is None else (f"{age} 秒前" if age < 60 else f"{age // 60} 分钟前")
        pill = f'<span class="pill {status}">{CONNECTION[status]}</span>'
        if status_page:
            cards.append(f'<tr><td><strong>{escape(label)}</strong><small>{name}</small></td>'
                         f'<td>{pill}</td><td class="ip">{escape(address)}</td><td>{handshake}</td>'
                         f'<td><a href="/admin?customer={name}#{name}">管理</a></td></tr>')
            continue
        opened = " open" if name == focus else ""
        if status == "disabled":
            buttons = '<button name="action" value="enable">启用用户</button><button name="action" value="confirm-delete">删除已禁用客户…</button>'
        else:
            buttons = ('<button name="action" value="bundle">生成配置并分发</button>'
                       '<button name="action" value="issue">签发内网领取链接</button>'
                       '<button name="action" value="disable">禁用用户</button>')
        cards.append(f'<section class="client" id="{name}"><details{opened}><summary>{caption} {pill}</summary>'
                     f'<small>{escape(address)} · 最近握手：{handshake}</small>'
                     f'<form method="post" action="/admin">{hidden}<input type="hidden" name="user" value="{name}">'
                     f'{buttons}<button name="action" value="confirm-rotate">轮换密钥…</button>'
                     '<label>新名称<input name="label" maxlength="40"></label>'
                     '<button name="action" value="rename">保存名称</button></form></details></section>')
    total_online = sum(row["status"] == "online" for row in rows)
    stats = (f'<div class="stats"><span>客户总数<b>{len(rows)}</b></span><span>在线<b>{total_online}</b></span>'
             f'<span>匹配<b>{len(cards)}</b></span></div>')
    if status_page:
        headers = "".join(f'<th scope="col">{col}</th>' for col in ("客户 / 编号", "状态", "隧道 IPv4", "最近握手", "操作"))
        body = "".join(cards) or '<tr><td colspan="5">没有匹配的客户。</td></tr>'
        return (stats + form + '<p class="hint">最近 3 分钟内有握手记为在线。点击“查询 / 刷新”获取最新状态。</p>'
                f'<div class="sheet" role="region" aria-label="客户连接状态" tabindex="0">'
                f'<table aria-label="客户连接状态"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>')
    return stats + form + ("".join(cards) or "<p>没有匹配的客户。</p>")



def application(env, start_response):
    nonce = secrets.token_urlsafe(20)

    def page(title, body="", status="200 OK", extra=(), navigation=""):
        html = (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>{title}</title>'
                f'<style nonce="{nonce}">{STYLE}</style>{navigation}<main><h1>{title}</h1>{body}</main></html>').encode()
        start_response(status, [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                                ("Referrer-Policy", "same-origin"), ("X-Content-Type-Options", "nosniff"),
                                ("Content-Security-Policy", "default-src 'none'; img-src data:; "
                                 f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
                                 "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
                                ("Content-Length", str(len(html))), *extra])
        return [html]

    def attachment(payload, filename, content_type):
        start_response("200 OK", [("Content-Type", content_type),
                       ("Content-Disposition", f'attachment; filename="{filename}"'),
                       ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                       ("Content-Length", str(len(payload)))])
        return [payload]

    origin = "https://" + os.environ["WEB_ADDRESS"] + ":8443"
    if (ipaddress.ip_address(env["REMOTE_ADDR"]) not in ipaddress.ip_network(os.environ["WEB_NETWORK"])
            or env.get("HTTP_HOST") != origin[8:]):
        return page("仅供指定内网访问", status="403 Forbidden")
    path, method = env["PATH_INFO"], env["REQUEST_METHOD"]
    if path not in ("/", "/admin", "/admin/status"):
        return page("页面不存在", status="404 Not Found")
    admin = path != "/"
    if admin:
        password = (Path(os.environ["CREDENTIALS_DIRECTORY"]) / "password").read_bytes().strip()
        auth = b"Basic " + base64.b64encode(b"admin:" + password)
        if not hmac.compare_digest(env.get("HTTP_AUTHORIZATION", "").encode(), auth):
            return page("需要管理员登录", status="401 Unauthorized",
                        extra=[("WWW-Authenticate", 'Basic realm="WireGuard Admin"')])
        if path == "/admin/status" and method != "GET":
            return page("请通过客户管理页操作", status="405 Method Not Allowed", extra=[("Allow", "GET")])
        csrf = hmac.digest(password, b"wgvps-admin-form", "sha256").hex()
    try:
        if method == "GET" and not admin:
            return page("领取 WireGuard 配置", '<form method="post"><label for="code">一次性领取码</label>'
                        '<input required id="code" name="code" autocomplete="off" maxlength="32">'
                        '<button>领取两份配置</button></form>'
                        f'<script nonce="{nonce}">if(location.hash){{document.querySelector("#code").value='
                        'location.hash.slice(1);history.replaceState(null,"","/")}</script>')
        if method == "GET":
            directory = customer_directory(json.loads(manager("status")), env.get("QUERY_STRING", ""), csrf, path)
            links = []
            for url, title in (("/admin", "客户管理"), ("/admin/status", "连接状态")):
                current = ' aria-current="page"' if path == url else ""
                links.append(f'<a href="{url}"{current}>{title}</a>')
            nav = '<header><nav aria-label="主导航"><strong>WireGuard</strong>' + "".join(links) + '</nav></header>'
            if path == "/admin/status":
                return page("连接状态", directory, navigation=nav)
            hidden = f'<input type="hidden" name="csrf" value="{csrf}">'
            return page("客户管理", f'<div class="tools"><form method="post">{hidden}'
                        '<label>新增客户名称<input name="label" required maxlength="40"></label>'
                        '<button name="action" value="add">新增客户</button></form>'
                        f'<form method="post">{hidden}<button name="action" value="archive">下载全部配置 ZIP</button>'
                        '</form></div>' + directory, navigation=nav)
        if method != "POST":
            return page("请求方式错误", status="405 Method Not Allowed")
        size = int(env.get("CONTENT_LENGTH") or 0)
        if not 0 < size <= 1024 or env.get("CONTENT_TYPE", "").split(";")[0] != "application/x-www-form-urlencoded":
            return page("表单无效", status="400 Bad Request")
        fields = parse_qs(env["wsgi.input"].read(size).decode("ascii"), max_num_fields=4)
        if admin:
            if (not hmac.compare_digest(fields.get("csrf", [""])[0].encode(), csrf.encode())
                    or env.get("HTTP_ORIGIN", origin) != origin):
                return page("请重新打开管理页", status="403 Forbidden")
            user, action = fields.get("user", [""])[0], fields.get("action", [""])[0]
            back = '<p><a href="/admin">返回客户管理</a></p>'
            if action == "add":
                label = fields.get("label", [""])[0]
                created = manager("add", data=label.encode()).decode().strip()
                return page(f"已新增 {escape(label)}（{escape(created)}）", back)
            if action == "archive":
                bundles = json.loads(manager("bundles"))
                if not bundles:
                    return page("没有已启用的用户", '<a href="/admin">返回用户管理</a>')
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                    for item in bundles:
                        name = item["name"]
                        for mode, config in item["profiles"].items():
                            archive.writestr(f"{name}/{name}-{mode}.conf", config)
                payload = stream.getvalue()
                return attachment(payload, "wireguard-users.zip", "application/zip")
            if not re.fullmatch(r"user[0-9]{2,}", user) or action not in (
                    "issue", "enable", "disable", "bundle", "confirm-rotate", "rotate",
                    "download-global", "download-proxy", "rename", "confirm-delete", "delete"):
                return page("用户或操作无效", status="400 Bad Request")
            if action.startswith("download-"):
                mode = action.removeprefix("download-")
                payload = json.loads(manager("bundle", user))["profiles"][mode].encode()
                return attachment(payload, f"{user}-{mode}.conf", "application/octet-stream")
            if action == "rename":
                label = fields.get("label", [""])[0]
                manager("rename", user, data=label.encode())
                return page(f"{user} 已更名为 {escape(label)}", back)
            if action == "confirm-delete":
                return page(f"删除 {user}？", '<p>此操作将删除该客户的记录与密钥。</p>'
                            f'<form method="post"><input type="hidden" name="csrf" value="{csrf}">'
                            f'<input type="hidden" name="user" value="{user}">'
                            '<button name="action" value="delete">确认删除</button></form>' + back)
            if action == "delete":
                manager("delete", user)
                return page(f"已删除 {user}", back)
            if action == "confirm-rotate":
                return page(f"轮换 {user} 的密钥？", '<p>旧配置会立即失效，轮换后请重新生成并分发两份配置。</p>'
                            f'<form method="post"><input type="hidden" name="csrf" value="{csrf}">'
                            f'<input type="hidden" name="user" value="{user}">'
                            '<button name="action" value="rotate">确认轮换密钥</button></form>' + back)
            result = manager(action, user).decode().strip()
            if action == "bundle":
                return page(f"分发 {user} 的配置", profiles(json.loads(result), csrf) + back)
            if action == "rotate":
                return page(f"{user} 密钥已轮换", back)
            if action == "issue":
                link = escape(origin + "/#" + result, quote=True)
                return page(f"{user} 的领取链接", f'<p>请单独发给该用户。链接仅可领取一次。</p>'
                            f'<input readonly aria-label="领取链接" value="{link}">' + back)
            return page(user + (" 已启用" if action == "enable" else " 已禁用"), back)
        code = fields.get("code", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{32}", code):
            return page("领取码格式无效", status="400 Bad Request")
        return page("导入配置", profiles(json.loads(manager("redeem", data=code.encode()))))
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 3 and exc.stderr:
            return page("操作未完成", f'<p>{escape(exc.stderr.decode(errors="replace"))}</p>'
                        '<a href="/admin">返回客户管理</a>', "409 Conflict")
        return page("操作未完成", "<p>请检查用户是否启用。若领取码已失效，请重新签发。</p>", "409 Conflict")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return page("请求未完成", "<p>请返回后重试。</p>", "400 Bad Request")
