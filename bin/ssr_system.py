"""Fixed operations for Ubuntu host tuning and SSR-only egress policy."""
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess

STATE = Path('/etc/ssr-admin')
BBR_FILE = Path('/etc/sysctl.d/90-ssr-admin-bbr.conf')
BBR_KEYS = ('net.core.default_qdisc', 'net.ipv4.tcp_congestion_control')
CHAIN = 'SSR_ADMIN_EGRESS'


def command(*args, input=None):
    return subprocess.check_output(args, input=input, text=True,
                                   stderr=subprocess.STDOUT, timeout=60)


def write_json(path, data):
    from ssr_admin_compat import write_private
    write_private(path, json.dumps(data, indent=2))


def read_state(path, default=None):
    if path.is_symlink():
        raise ValueError('状态文件不能为符号链接')
    return json.loads(path.read_text()) if path.exists() else default


def bbr(action):
    snapshot = STATE / 'bbr-backup.json'
    if action == 'status':
        return {k: command('sysctl', '-n', k).strip() for k in BBR_KEYS}
    if action not in ('enable', 'disable'):
        raise ValueError('BBR action 为 status/enable/disable')
    if action == 'disable':
        old = read_state(snapshot)
        if old is None:
            raise ValueError('没有本工具创建的 BBR 备份')
        current = bbr('status')
        if BBR_FILE.is_symlink():
            raise ValueError('BBR 配置不能为符号链接')
        current_file = BBR_FILE.read_text() if BBR_FILE.exists() else None
        from ssr_admin_compat import write_private
        try:
            for k, v in old['values'].items():
                command('sysctl', '-w', k + '=' + v)
            if old['file'] is None:
                BBR_FILE.unlink(missing_ok=True)
            else:
                write_private(BBR_FILE, old['file'], mode=0o644)
        except Exception:
            for k, v in current.items():
                command('sysctl', '-w', k + '=' + v)
            if current_file is None:
                BBR_FILE.unlink(missing_ok=True)
            else:
                write_private(BBR_FILE, current_file, mode=0o644)
            raise
        snapshot.unlink()
        return bbr('status')
    before = bbr('status')
    modules = Path('/proc/modules')
    if modules.exists() and any(line.split()[0] == 'appex' for line in modules.read_text().splitlines() if line.split()):
        raise ValueError('检测到锐速 appex 模块，请先停止锐速再启用 BBR')
    available = command('sysctl', '-n', 'net.ipv4.tcp_available_congestion_control').split()
    if 'bbr' not in available:
        command('modprobe', 'tcp_bbr')
        available = command('sysctl', '-n', 'net.ipv4.tcp_available_congestion_control').split()
    if 'bbr' not in available:
        raise ValueError('当前内核不支持 BBR；未替换内核')
    command('modprobe', 'sch_fq')
    if BBR_FILE.is_symlink():
        raise ValueError('BBR 配置不能为符号链接')
    previous_file = BBR_FILE.read_text() if BBR_FILE.exists() else None
    created_snapshot = not snapshot.exists()
    if created_snapshot:
        write_json(snapshot, {'values': before, 'file': previous_file})
    from ssr_admin_compat import write_private
    try:
        command('sysctl', '-w', BBR_KEYS[0] + '=fq')
        command('sysctl', '-w', BBR_KEYS[1] + '=bbr')
        write_private(BBR_FILE, 'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\n', mode=0o644)
        after = bbr('status')
        if after[BBR_KEYS[1]] != 'bbr':
            raise ValueError('BBR 生效检查失败')
        return after
    except Exception:
        for k, v in before.items():
            command('sysctl', '-w', k + '=' + v)
        if previous_file is None:
            BBR_FILE.unlink(missing_ok=True)
        else:
            write_private(BBR_FILE, previous_file, mode=0o644)
        if created_snapshot:
            snapshot.unlink(missing_ok=True)
        raise


def firewall_rules(uid, policy):
    prefix = f'-A {CHAIN} -m owner --uid-owner {uid} '
    rules = []
    if policy['smtp']:
        rules.append(prefix + '-p tcp -m multiport --dports 25,465,587 -j REJECT')
    if policy['bt']:
        for protocol in ('tcp', 'udp'):
            rules.append(prefix + f'-p {protocol} -m multiport --dports 6881:6999,51413 -j REJECT')
            for signature in ('BitTorrent protocol', 'announce_peer', 'get_peers', 'info_hash'):
                rules.append(prefix + f'-p {protocol} -m string --algo kmp --string "{signature}" -j REJECT')
    return rules


def restore_script(rules):
    return '*filter\n-F ' + CHAIN + '\n' + '\n'.join(rules) + '\nCOMMIT\n'


def firewall(action, data):
    import pwd
    path = STATE / 'firewall.json'
    policy = read_state(path, {'smtp': False, 'bt': False})
    if action == 'status':
        runtime = {}
        for tool in ('iptables', 'ip6tables'):
            try:
                rules = command(tool, '-w', '-S').splitlines()
                runtime[tool] = {'chain_rules': [r for r in rules if r.startswith('-A ' + CHAIN + ' ')],
                    'output_jump': any(r.startswith('-A OUTPUT ') and '--comment ssr-admin ' in r and r.endswith('-j ' + CHAIN) for r in rules)}
            except (OSError, subprocess.SubprocessError) as e:
                runtime[tool] = {'error': str(e)}
        return {'configured': policy, 'runtime': runtime, 'scope': 'ssr UID only; IPv4 + IPv6',
                'note': 'BT/PT 为常用端口及单包明文特征拦截，不能识别所有加密/分片流量'}
    if action == 'apply':
        desired = policy
    elif action in ('enable', 'disable'):
        desired = dict(policy)
        feature = data.get('feature', 'all')
        if feature not in ('smtp', 'bt', 'all'):
            raise ValueError('feature 为 smtp/bt/all')
        for name in ('smtp', 'bt'):
            if feature in (name, 'all'):
                desired[name] = action == 'enable'
    else:
        raise ValueError('firewall action 为 status/enable/disable/apply')
    user = pwd.getpwnam('ssr')
    if user.pw_uid == 0:
        raise ValueError('SSR 必须使用独立的非 root 用户')
    # No global flush: only our chain is replaced. Verify both families before commit.
    old_rules = {}
    created_jumps = []
    try:
        for tool in ('iptables', 'ip6tables'):
            listing = command(tool, '-w', '-S')
            if f'-N {CHAIN}' not in listing.splitlines():
                command(tool, '-w', '-N', CHAIN)
            old_rules[tool] = [line for line in listing.splitlines() if line.startswith('-A ' + CHAIN + ' ')]
            script = restore_script(firewall_rules(user.pw_uid, desired))
            command(tool + '-restore', '--wait', '10', '--noflush', '--test', input=script)
        for tool in old_rules:
            command(tool + '-restore', '--wait', '10', '--noflush',
                    input=restore_script(firewall_rules(user.pw_uid, desired)))
        for tool in old_rules:
            jump = ['OUTPUT', '-m', 'comment', '--comment', 'ssr-admin', '-j', CHAIN]
            result = subprocess.run([tool, '-w', '-C'] + jump, capture_output=True, timeout=15)
            if result.returncode == 1:
                command(tool, '-w', '-I', 'OUTPUT', '1', *jump[1:])
                created_jumps.append((tool, jump))
            elif result.returncode:
                raise ValueError('无法检查防火墙跳转规则')
        write_json(path, desired)
    except Exception:
        for tool, jump in reversed(created_jumps):
            command(tool, '-w', '-D', *jump)
        for tool, rules in old_rules.items():
            command(tool + '-restore', '--wait', '10', '--noflush', input=restore_script(rules))
        raise
    return firewall('status', {})


def trusted_file(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('必须是绝对路径且不能为符号链接')
    s = path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
        raise ValueError('文件须由 root 拥有，且组和其他用户不可写')
    for parent in path.parents:
        s = parent.stat()
        if s.st_uid != 0 or s.st_mode & 0o022:
            raise ValueError('文件父目录必须由 root 管理且不可被其他用户写入')
    return path


def ruisu(action):
    manifest_path = STATE / 'serverspeeder.json'
    if not manifest_path.exists():
        if action == 'status':
            return {'available': False, 'kernel': platform.release(),
                    'message': '未配置经审查且匹配当前内核的锐速安装包；可使用 BBR'}
        raise ValueError('无可信锐速安装源：先按 docs/ADMIN.md 配置内核匹配的本地安装包；不会降级内核或下载未知脚本')
    manifest = json.loads(trusted_file(manifest_path).read_text())
    if manifest['kernel'] != platform.release() or manifest['architecture'] != platform.machine():
        raise ValueError('锐速安装包与当前内核/架构不匹配')
    package = trusted_file(manifest['installer'])
    if hashlib.sha256(package.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('锐速安装包 SHA256 不匹配')
    if action == 'status':
        return {'available': True, 'kernel': platform.release(), 'installer': str(package)}
    if action != 'install':
        raise ValueError('ruisu action 为 status/install')
    if command('sysctl', '-n', 'net.ipv4.tcp_congestion_control').strip() == 'bbr':
        raise ValueError('请先关闭 BBR，再安装锐速')
    # Only terminal can run this explicitly provisioned root-owned installer.
    subprocess.run(['/bin/bash', str(package)], check=True, timeout=1800)
    return {'installer_completed': True, 'message': '请按供应商方式验证模块和授权状态'}


def system_action(op, data):
    import fcntl
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(STATE / 'system.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        action = data.get('action', 'status')
        if op == 'bbr':
            return bbr(action)
        if op == 'firewall':
            return firewall(action, data)
        if op == 'ruisu':
            return ruisu(action)
        raise ValueError('未知系统操作')
    finally:
        os.close(fd)
