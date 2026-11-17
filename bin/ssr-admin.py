#!/usr/bin/env python3
"""SSR account manager; one account per listening port."""
import argparse
import base64
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode
from ssr_backend import check_speed_backend, patch_server

CONFIG = Path('/etc/ssr/config.json')
PROTOCOLS = {'auth_sha1_v4'}  # audited client-id counter; compatible variants bypass it
FIELDS = ('password', 'method', 'protocol', 'protocol_param', 'obfs', 'obfs_param',
          'speed_limit_per_user', 'speed_limit_per_con', 'ssr_admin_devices')


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=30)


def b64(value):
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')


def integer(value, minimum=0, maximum=2147483647):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError('必须填写整数')
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f'范围必须为 {minimum}–{maximum}')
    return value


def accounts(c):
    raw = c.get('port_password') or {str(c['server_port']): c['password']}
    result = {}
    for p, value in raw.items():
        p = str(integer(p, 1, 65535))
        account = {k: c[k] for k in FIELDS if k in c}
        if isinstance(value, str):
            account['password'] = value
        elif isinstance(value, dict):
            account.update(value)
        elif isinstance(value, list) and 2 <= len(value) <= 3:
            account.update(password=value[0], obfs=value[1])
            if len(value) == 3:
                account['protocol'] = value[2]
        else:
            raise ValueError('不支持的 port_password 格式')
        if not isinstance(account.get('password'), str) or not account['password']:
            raise ValueError('账号密码不能为空')
        result[p] = account
    return result


@contextmanager
def config_lock(path):
    require_config(path)
    import fcntl
    fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def require_config(path):
    if not path.is_file():
        raise ValueError(
            f'未找到 SSR 配置：{path}。SSR 尚未安装或安装未完成。'
            '请先在项目目录执行 sudo bash bin/ssr-install.sh；'
            '安装成功后再执行 sudo bash manage.sh admin-install。'
            '若此前安装失败，请检查安装日志和现有文件；不要手动创建空配置或锁文件。')


def atomic_write(path, text, mode=0o600, owner=None):
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        if owner is not None:
            os.chown(tmp, *owner)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(path, c):
    if path.is_symlink():
        raise ValueError('配置文件不能为符号链接')
    original = path.stat()
    atomic_write(path.with_suffix('.json.backup'), path.read_text(encoding='utf-8'))
    atomic_write(path, json.dumps(c, indent=2), original.st_mode & 0o777,
                 (original.st_uid, original.st_gid))


def endpoint(value):
    host, port = value.rsplit(':', 1)
    host = host.strip('[]')
    address = ipaddress.ip_address(host.split('%')[0])
    if getattr(address, 'ipv4_mapped', None):
        address = address.ipv4_mapped
    return str(address), int(port)


def connections(users):
    results = {p: set() for p in users}
    for line in run('ss', '-Hnt', 'state', 'established').splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            _, port = endpoint(parts[-2])
            peer, _ = endpoint(parts[-1])
        except ValueError:
            continue
        if str(port) in results:
            results[str(port)].add(peer)
    return [{'port': p, 'ips': sorted(ips), 'ip_count': len(ips)} for p, ips in results.items()]


def share(users, host, qr=False):
    host = str(host).strip()
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
            raise ValueError('服务器地址必须为 IP 或域名')
    address = '[' + host + ']' if ':' in host else host
    result = []
    for port, a in users.items():
        protocol = a.get('protocol', 'origin')
        # Server-side max-client count is not a client protocol parameter.
        protocol_param = '' if protocol in PROTOCOLS else a.get('protocol_param', '')
        raw = f"{address}:{port}:{protocol}:{a['method']}:{a.get('obfs', 'plain')}:{b64(a['password'])}"
        params = urlencode({'obfsparam': b64(a.get('obfs_param', '')), 'protoparam': b64(protocol_param)})
        item = {'port': port, 'ssr': 'ssr://' + b64(raw + '/?' + params)}
        if protocol == 'origin' and a.get('obfs', 'plain') == 'plain':
            item['ss'] = 'ss://' + b64(a['method'] + ':' + a['password']) + '@' + address + ':' + port
        if qr:
            for kind in ('ssr', 'ss'):
                if kind in item:
                    image = subprocess.check_output(['qrencode', '-t', 'PNG', '-o', '-'],
                        input=item[kind].encode(), timeout=10)
                    item[kind + '_qr'] = 'data:image/png;base64,' + base64.b64encode(image).decode()
        result.append(item)
    return result


def execute(path, op, data):
    if not isinstance(data, dict):
        raise ValueError('参数必须为 JSON 对象')
    if op == 'backend-patch':
        return patch_server('/opt/ssr/shadowsocks/server.py')
    if op in ('bbr', 'firewall', 'ruisu'):
        from ssr_system import system_action
        return system_action(op, data)
    if op == 'restart':
        require_config(path)
        run('systemctl', 'restart', 'ssr')
        run('systemctl', 'is-active', '--quiet', 'ssr')
        return {'active': True}
    require_config(path)
    with config_lock(path):
        c = json.loads(path.read_text(encoding='utf-8-sig'))
        users = accounts(c)
        if op == 'list':
            return {'mode': 'multi' if c.get('port_password') else 'single',
                'accounts': [{'port': p, 'speed_kbps': a.get('speed_limit_per_user', 0),
                    'protocol': a.get('protocol', 'origin'),
                    'tcp_only': bool(a.get('ssr_admin_devices') or a.get('speed_limit_per_user')),
                    'devices': a.get('protocol_param') if a.get('protocol') in PROTOCOLS else None}
                    for p, a in users.items()]}
        if op == 'ips':
            return connections(users)
        if op == 'share':
            selected = users
            if data.get('port'):
                p = str(integer(data['port'], 1, 65535))
                selected = {p: users[p]}
            return share(selected, data['host'], bool(data.get('qr', False)))
        if op in ('add', 'delete', 'speed', 'devices'):
            port = str(integer(data['port'], 1, 65535))
            if op == 'add':
                if port in users:
                    raise ValueError('端口已存在')
                password = data.get('password') or secrets.token_urlsafe(24)
                if not isinstance(password, str) or len(password) > 1024:
                    raise ValueError('密码必须为不超过 1024 字符的字符串')
                account = {k: c[k] for k in FIELDS if k in c}
                account['password'] = password
                users[port] = account
            else:
                if port not in users:
                    raise ValueError('端口不存在')
                if op == 'delete':
                    if len(users) == 1:
                        raise ValueError('不能删除最后一个账号')
                    del users[port]
                elif op == 'speed':
                    check_speed_backend()
                    if integer(c.get('workers', 1), 1) != 1:
                        raise ValueError('独立限速要求 workers=1，多个 worker 的计数不共享')
                    users[port]['speed_limit_per_user'] = integer(data['value'])
                else:
                    a = users[port]
                    if a.get('protocol') not in PROTOCOLS:
                        raise ValueError('设备限制仅支持 auth_sha1_v4（不含 compatible）；请先使用该协议')
                    if integer(c.get('workers', 1), 1) != 1:
                        raise ValueError('设备限制要求 workers=1，多个 worker 的计数不共享')
                    check_speed_backend()
                    limit = integer(data['value'], 0, 4096)
                    users[port]['protocol_param'] = str(limit) if limit else ''
                    users[port]['ssr_admin_devices'] = limit
            if c.get('port_password') or len(users) > 1:
                c['port_password'] = users
            else:
                c.update(next(iter(users.values())))
        elif op == 'mode':
            if data['value'] == 'single':
                if len(users) != 1:
                    raise ValueError('请先删除多余账号，再切换单端口')
                port, account = next(iter(users.items()))
                c.update(account)
                c['server_port'] = int(port)
                c.pop('port_password', None)
            elif data['value'] == 'multi':
                c['port_password'] = users
            else:
                raise ValueError('模式为 single 或 multi')
        else:
            raise ValueError('未知操作')
        save(path, c)
        return {'saved': True, 'message': '已保存；重启 SSR 后生效',
                'backup': str(path.with_suffix('.json.backup'))}


PAGE = (Path(__file__).resolve().parent.parent / 'templates' / 'admin.html')
WEB_OPS = {'list', 'add', 'delete', 'speed', 'devices', 'mode', 'ips', 'share',
           'restart', 'bbr', 'firewall'}


def terminal_menu(path):
    import getpass
    choices = {'1': 'list', '2': 'add', '3': 'delete', '4': 'speed',
        '5': 'devices', '6': 'ips', '7': 'share', '8': 'mode',
        '9': 'restart', '10': 'bbr', '11': 'ruisu', '12': 'firewall'}
    while True:
        print('\nSSR 管理\n1 账号列表  2 添加账号  3 删除账号  4 独立限速\n'
              '5 设备限制  6 连接 IP  7 链接/二维码  8 单/多端口\n'
              '9 重启 SSR  10 BBR  11 锐速  12 垃圾邮件/BT/PT 封禁  0 退出')
        choice = input('请选择: ').strip()
        if choice == '0':
            return
        op = choices.get(choice)
        if not op:
            continue
        data = {}
        try:
            if op in ('add', 'delete', 'speed', 'devices'):
                data['port'] = input('端口: ').strip()
            if op == 'add':
                data['password'] = getpass.getpass('密码（留空自动生成）: ')
            if op in ('speed', 'devices'):
                data['value'] = input('KB/s（0 不限）: ' if op == 'speed' else '客户端标识上限（1–4096；0 恢复协议默认）: ').strip()
            if op == 'mode':
                data['value'] = input('single / multi: ').strip()
            if op in ('bbr', 'ruisu', 'firewall'):
                data['action'] = input('status / install: ' if op == 'ruisu' else 'status / enable / disable: ').strip()
            if op == 'firewall':
                data['feature'] = input('smtp / bt / all: ').strip()
            if op == 'share':
                data['host'] = input('服务器 IP / 域名: ').strip()
                for item in execute(path, op, data):
                    for kind in ('ssr', 'ss'):
                        if kind in item:
                            print(f"端口 {item['port']} {kind}: {item[kind]}", flush=True)
                            subprocess.run(['qrencode', '-t', 'ANSIUTF8'], input=item[kind].encode(), check=True)
                continue
            print(json.dumps(execute(path, op, data), ensure_ascii=False, indent=2))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
            print(f'错误：{e}')


def serve(path, port, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def reply(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != '/':
                return self.reply(404, b'Not found', 'text/plain')
            self.reply(200, PAGE.read_bytes(), 'text/html; charset=utf-8')

        def do_POST(self):
            try:
                if self.path != '/api' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                    return self.reply(401, b'{"error":"unauthorized"}', 'application/json')
                if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                    raise ValueError('请求来源无效')
                length = integer(self.headers.get('Content-Length', '0'), 1, 16384)
                request = json.loads(self.rfile.read(length))
                if request['op'] not in WEB_OPS:
                    raise ValueError('Web 不支持此操作')
                result = execute(path, request['op'], request.get('data', {}))
                self.reply(200, json.dumps(result, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            except Exception as e:
                self.reply(400, json.dumps({'error': str(e)}, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
    print(f'管理地址 http://127.0.0.1:{port}', flush=True)
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=CONFIG)
    p.add_argument('operation', nargs='?', default='menu', choices=sorted(WEB_OPS | {'web', 'backend-patch', 'ruisu', 'menu'}))
    p.add_argument('--port', type=int, default=9080, help='Web 监听端口')
    p.add_argument('--data', default='{}', help='JSON 参数；--data - 从标准输入读取')
    a = p.parse_args()
    if os.geteuid() != 0:
        p.error('请使用 sudo/root')
    try:
        if a.operation == 'menu':
            require_config(a.config)
            terminal_menu(a.config)
        elif a.operation == 'web':
            require_config(a.config)
            token = os.environ.get('SSR_ADMIN_TOKEN', '')
            if len(token) < 32:
                p.error('设置 SSR_ADMIN_TOKEN，至少 32 字符')
            serve(a.config, a.port, token)
        else:
            data = json.loads(sys.stdin.read() if a.data == '-' else a.data)
            if a.operation == 'share' and data.pop('terminal_qr', False):
                for item in execute(a.config, 'share', data):
                    for kind in ('ssr', 'ss'):
                        if kind in item:
                            print(f"端口 {item['port']} {kind}: {item[kind]}", flush=True)
                            subprocess.run(['qrencode', '-t', 'ANSIUTF8'], input=item[kind].encode(), check=True)
            else:
                print(json.dumps(execute(a.config, a.operation, data), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
        print(f'错误：{e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
