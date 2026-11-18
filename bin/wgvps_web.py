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
*{box-sizing:border-box}body{margin:0;background:#f3f6f7;color:#182a31;font:16px/1.55 system-ui,sans-serif}
main{max-width:760px;margin:auto;padding:5vh 20px}h1{font-size:clamp(26px,5vw,38px);line-height:1.15}
section,form{background:white;border:1px solid #cfdbdf;padding:18px;border-radius:10px;margin:16px 0}
label{display:block;margin-bottom:8px}input,select,button,a.download{font:inherit;padding:8px 12px;border-radius:5px}
input,select{border:1px solid #8c9da4;max-width:100%}input{width:100%}button,a.download{border:0;background:#145a64;color:white;cursor:pointer;margin:6px 4px 0 0}a.download{display:inline-block;text-decoration:none}
img{display:block;max-width:100%;height:auto}summary{cursor:pointer;margin-top:12px}a{color:#145a64}
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


def application(env, start_response):
    nonce = secrets.token_urlsafe(20)

    def page(title, body="", status="200 OK", extra=()):
        html = (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>{title}</title>'
                f'<style nonce="{nonce}">{STYLE}</style><main><h1>{title}</h1>{body}</main></html>').encode()
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
    if path not in ("/", "/admin"):
        return page("页面不存在", status="404 Not Found")
    admin = path == "/admin"
    if admin:
        password = (Path(os.environ["CREDENTIALS_DIRECTORY"]) / "password").read_bytes().strip()
        auth = b"Basic " + base64.b64encode(b"admin:" + password)
        if not hmac.compare_digest(env.get("HTTP_AUTHORIZATION", "").encode(), auth):
            return page("需要管理员登录", status="401 Unauthorized",
                        extra=[("WWW-Authenticate", 'Basic realm="WireGuard Admin"')])
        csrf = hmac.digest(password, b"wgvps-admin-form", "sha256").hex()
    try:
        if method == "GET" and not admin:
            return page("领取 WireGuard 配置", '<form method="post"><label for="code">一次性领取码</label>'
                        '<input required id="code" name="code" autocomplete="off" maxlength="32">'
                        '<button>领取两份配置</button></form>'
                        f'<script nonce="{nonce}">if(location.hash){{document.querySelector("#code").value='
                        'location.hash.slice(1);history.replaceState(null,"","/")}</script>')
        if method == "GET":
            options = []
            for row in manager("list").decode().splitlines():
                name, enabled, _ = row.split()
                options.append(f'<option value="{escape(name)}">{escape(name)} · '
                               f'{"已启用" if enabled == "enabled" else "已禁用"}</option>')
            return page("WireGuard 配置管理", '<form method="post"><label for="user">选择用户</label>'
                        f'<select id="user" name="user">{"".join(options)}</select>'
                        f'<input type="hidden" name="csrf" value="{csrf}"><p>生成全局和代理两份配置，'
                        '可分别下载发给用户，或让手机直接扫描二维码。</p>'
                        '<button name="action" value="bundle">生成配置并分发</button>'
                        '<button name="action" value="issue">签发内网领取链接</button>'
                        '<button name="action" value="enable">启用用户</button>'
                        '<button name="action" value="disable">禁用用户</button>'
                        '<button name="action" value="confirm-rotate">轮换密钥…</button></form>'
                        f'<form method="post"><input type="hidden" name="csrf" value="{csrf}">'
                        '<p>批量生成全部已启用用户的配置。压缩包按用户分目录，请只向每人发送其自己的文件。</p>'
                        '<button name="action" value="archive">下载全部配置 ZIP</button></form>')
        if method != "POST":
            return page("请求方式错误", status="405 Method Not Allowed")
        size = int(env.get("CONTENT_LENGTH") or 0)
        if not 0 < size <= 512 or env.get("CONTENT_TYPE", "").split(";")[0] != "application/x-www-form-urlencoded":
            return page("表单无效", status="400 Bad Request")
        fields = parse_qs(env["wsgi.input"].read(size).decode("ascii"), max_num_fields=4)
        if admin:
            if (not hmac.compare_digest(fields.get("csrf", [""])[0].encode(), csrf.encode())
                    or env.get("HTTP_ORIGIN", origin) != origin):
                return page("请重新打开管理页", status="403 Forbidden")
            user, action = fields.get("user", [""])[0], fields.get("action", [""])[0]
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
            if not re.fullmatch(r"user(0[1-9]|1[0-9]|2[0-5])", user) or action not in (
                    "issue", "enable", "disable", "bundle", "confirm-rotate", "rotate",
                    "download-global", "download-proxy"):
                return page("用户或操作无效", status="400 Bad Request")
            if action.startswith("download-"):
                mode = action.removeprefix("download-")
                payload = json.loads(manager("bundle", user))["profiles"][mode].encode()
                return attachment(payload, f"{user}-{mode}.conf", "application/octet-stream")
            back = '<p><a href="/admin">返回用户管理</a></p>'
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
    except subprocess.CalledProcessError:
        return page("操作未完成", "<p>请检查用户是否启用。若领取码已失效，请重新签发。</p>", "409 Conflict")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return page("请求未完成", "<p>请返回后重试。</p>", "400 Bad Request")
