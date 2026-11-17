"""Validated adapter for the manyuser server.py per-port speed omission."""
import ast
import hashlib
import os
from pathlib import Path

MARKER = '# ssr-admin per-port limits v2'
NEEDLE = 'a_config = config.copy()'
UDP = 'udp_servers.append(udprelay.UDPRelay(a_config, dns_resolver, False, stat_counter=stat_counter_dict))'


def patch_server(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('server.py 不能为符号链接')
    source = path.read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode()).hexdigest()
    if MARKER in source:
        if source.count(MARKER) != 2:
            raise ValueError('SSR 适配补丁不完整，请先恢复原文件')
        return {'patched': False, 'sha256': digest}
    if (source.count(NEEDLE) != 2 or source.count(UDP) != 2 or
            source.count('    def run_server():') != 1 or
            "password_obfs.get('protocol_param', protocol_param)" not in source):
        raise ValueError('未知 SSR server.py 结构，拒绝自动修改')
    result = []
    for line in source.splitlines(keepends=True):
        if line.strip() == UDP:
            indent = line[:len(line) - len(line.lstrip())]
            result.append(indent + "if not a_config.get('ssr_admin_devices') and not a_config.get('speed_limit_per_user', 0):\n")
            result.append('    ' + line)
            continue
        if line == '    def run_server():\n':
            # A port gets one limiter/client-id registry across its two TCP listeners.
            result.extend(s + '\n' for s in [
                '    ssr_admin_relays = {}',
                '    for relay in tcp_servers:',
                '        port_key = relay._listen_port',
                '        if port_key in ssr_admin_relays:',
                '            first = ssr_admin_relays[port_key]',
                '            relay.protocol_data = first.protocol_data',
                '            relay._speed_tester_u = first._speed_tester_u',
                '            relay._speed_tester_d = first._speed_tester_d',
                '        else:',
                '            ssr_admin_relays[port_key] = relay'])
        result.append(line)
        if line.strip() == NEEDLE:
            indent = line[:len(line) - len(line.lstrip())]
            result.extend(indent + s + '\n' for s in [MARKER,
                'if isinstance(password_obfs, dict):',
                "    for limit_key in ('speed_limit_per_user', 'speed_limit_per_con', 'ssr_admin_devices'):",
                '        if limit_key in password_obfs:',
                '            a_config[limit_key] = int(password_obfs[limit_key])'])
    patched = ''.join(result)
    ast.parse(patched)
    backup = path.with_name('server.py.before-ssr-admin')
    with backup.open('x', encoding='utf-8') as f:
        f.write(source)
    mode = path.stat().st_mode & 0o777
    tmp = path.with_name('server.py.ssr-admin-tmp')
    try:
        with tmp.open('x', encoding='utf-8', newline='') as f:
            f.write(patched)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {'patched': True, 'backup': str(backup), 'original_sha256': digest}


def check_speed_backend(path=Path('/opt/ssr/shadowsocks/server.py')):
    if path.read_text(encoding='utf-8').count(MARKER) != 2:
        raise ValueError('先执行 sudo bash manage.sh admin backend-patch，再设置限速或设备限制')
