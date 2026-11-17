"""Portable unit tests: host effects are mocked; no privileged commands run."""
import base64
from contextlib import nullcontext
import importlib.util
import json
import os
import http.client
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# Keep all test files inside the checkout, including on restricted Windows hosts.
TEST_TMP = ROOT / '.test-tmp'
TEST_TMP.mkdir(exist_ok=True)
tempfile.tempdir = str(TEST_TMP)
sys.path.insert(0, str(ROOT / 'bin'))
spec = importlib.util.spec_from_file_location('admin', ROOT / 'bin/ssr-admin.py')
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)
import ssr_backend as backend
import ssr_system as system


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.json'
        self.original = {'server_port': 8388, 'password': 'secret', 'method': 'aes-256-cfb',
                         'protocol': 'auth_sha1_v4', 'obfs': 'plain', 'speed_limit_per_user': 0}
        self.path.write_text(json.dumps(self.original))
        self.lock = patch.object(admin, 'config_lock', lambda p: nullcontext())
        self.lock.start()
        self.addCleanup(self.lock.stop)
        self.owner = patch.object(admin.os, 'chown', create=True)
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.backend = patch.object(admin, 'check_speed_backend')
        self.backend.start()
        self.addCleanup(self.backend.stop)
        self.paths = patch.object(admin, 'server_for', return_value=Path('/test/server.py'))
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def execute(self, op, **data):
        return admin.execute(self.path, op, data)

    def config(self):
        return json.loads(self.path.read_text())

    def test_missing_config_reports_installation_before_lock(self):
        missing = self.path.parent / 'absent' / 'config.json'
        with patch.object(admin, 'config_lock') as lock:
            with self.assertRaisesRegex(ValueError, 'ssr-install.sh'):
                admin.execute(missing, 'add', {'port': 5552})
            lock.assert_not_called()
        self.assertFalse(missing.parent.exists())

    def test_missing_config_blocks_menu(self):
        with patch.object(sys, 'argv', ['ssr-admin.py', '--config', str(self.path.parent / 'missing.json'), 'menu']), patch.object(admin.os, 'geteuid', return_value=0, create=True), patch.object(admin, 'terminal_menu') as menu, patch('sys.stderr'):
            self.assertEqual(admin.main(), 1)
            menu.assert_not_called()

    def test_independent_speed_and_backup(self):
        self.execute('add', port=8390, password='new')
        before = self.path.read_text()
        with patch.object(admin, 'check_speed_backend'):
            self.execute('speed', port=8390, value=512)
        users = self.config()['port_password']
        self.assertEqual(users['8390']['speed_limit_per_user'], 512)
        self.assertEqual(users['8388']['speed_limit_per_user'], 0)
        self.assertEqual(self.path.with_suffix('.json.backup').read_text(), before)

    def test_unpatched_speed_rejected_without_write(self):
        before = self.path.read_text()
        with patch.object(admin, 'check_speed_backend', side_effect=ValueError('unpatched')):
            with self.assertRaises(ValueError):
                self.execute('speed', port=8388, value=10)
        self.assertEqual(before, self.path.read_text())

    def test_single_speed(self):
        with patch.object(admin, 'check_speed_backend'):
            self.execute('speed', port=8388, value=99)
        self.assertEqual(self.config()['speed_limit_per_user'], 99)
        self.assertNotIn('port_password', self.config())

    def test_modes_preserve_settings(self):
        self.execute('devices', port=8388, value=3)
        self.execute('mode', value='multi')
        self.execute('mode', value='single')
        self.assertEqual(self.config()['protocol_param'], '3')
        self.assertEqual(self.config()['password'], 'secret')

    def test_no_destructive_single_conversion(self):
        self.execute('add', port=8390)
        with self.assertRaises(ValueError):
            self.execute('mode', value='single')
        self.assertEqual(len(admin.accounts(self.config())), 2)

    def test_device_limit_rejects_bypass_protocol(self):
        for protocol in ('origin', 'auth_sha1_v4_compatible', 'auth_chain_a'):
            config = dict(self.original, protocol=protocol)
            self.path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                self.execute('devices', port=8388, value=2)

    def test_device_limit_rejects_multiworker(self):
        self.path.write_text(json.dumps(dict(self.original, workers=2)))
        with self.assertRaises(ValueError):
            self.execute('devices', port=8388, value=2)

    def test_device_limit_is_independent(self):
        self.execute('add', port=8390)
        self.execute('devices', port=8390, value=5)
        self.assertEqual(self.config()['port_password']['8390']['protocol_param'], '5')
        self.assertNotIn('protocol_param', self.config()['port_password']['8388'])

    def test_device_limit_reset_preserves_speed_and_password(self):
        self.execute('devices', port=8388, value=3)
        self.execute('speed', port=8388, value=100)
        self.execute('devices', port=8388, value=0)
        c = self.config()
        self.assertEqual(c['protocol_param'], '')
        self.assertEqual(c['ssr_admin_devices'], 0)
        self.assertEqual(c['speed_limit_per_user'], 100)
        self.assertEqual(c['password'], 'secret')
        self.assertTrue(self.execute('list')['accounts'][0]['tcp_only'])

    def test_speed_rejects_multiworker(self):
        self.path.write_text(json.dumps(dict(self.original, workers=2)))
        with self.assertRaises(ValueError):
            self.execute('speed', port=8388, value=100)

    def test_atomic_replace_failure_preserves_configuration(self):
        original_replace = admin.os.replace
        def replace(source, destination):
            if destination == self.path:
                raise OSError('simulated failure')
            return original_replace(source, destination)
        with patch.object(admin.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.execute('add', port=8390)
        self.assertEqual(self.config(), self.original)
        self.assertEqual(json.loads(self.path.with_suffix('.json.backup').read_text()), self.original)

    def test_invalid_parameters_do_not_write(self):
        for port in (0, 65536, -1, True, '8388;id', '1.5'):
            with self.assertRaises(ValueError):
                self.execute('add', port=port)
        with patch.object(admin, 'check_speed_backend'):
            for value in (-1, '1.5', True):
                with self.assertRaises(ValueError):
                    self.execute('speed', port=8388, value=value)
        self.assertEqual(self.config(), self.original)

    def test_last_account_and_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            self.execute('delete', port=8388)
        with self.assertRaises(ValueError):
            self.execute('add', port=8388)

    def test_list_never_returns_password(self):
        self.assertNotIn('secret', json.dumps(self.execute('list')))

    def test_delete_preserves_remaining_account(self):
        self.execute('add', port=8390)
        self.execute('delete', port=8390)
        self.assertEqual(list(admin.accounts(self.config())), ['8388'])

    def test_legacy_accounts_normalized(self):
        config = dict(self.original, port_password={'8388': ['foo', 'http_simple', 'origin'],
                      '8390': {'password': 'bar', 'method': 'aes-128-ctr'}})
        users = admin.accounts(config)
        self.assertEqual(users['8388']['protocol'], 'origin')
        self.assertEqual(users['8390']['method'], 'aes-128-ctr')

    def test_share_uses_effective_settings_and_ipv6(self):
        self.execute('add', port=8390, password='päss')
        self.execute('devices', port=8390, value=3)
        result = self.execute('share', host='2001:db8::1')
        decoded = base64.urlsafe_b64decode(result[1]['ssr'][6:] + '===').decode()
        self.assertTrue(decoded.startswith('[2001:db8::1]:8390:auth_sha1_v4:'))
        self.assertIn(admin.b64('päss'), decoded)
        self.assertIn('protoparam=', decoded)
        self.assertNotIn('ss', result[1])

    def test_plain_ss_link_and_qr_input_stays_off_command_line(self):
        config = dict(self.original, protocol='origin')
        self.path.write_text(json.dumps(config))
        with patch.object(admin.subprocess, 'check_output', return_value=b'PNG') as mocked:
            result = self.execute('share', host='example.com', qr=True)
        self.assertIn('ss', result[0])
        self.assertTrue(result[0]['ssr_qr'].startswith('data:image/png;base64,'))
        self.assertEqual(mocked.call_count, 2)
        self.assertNotIn('ss://', repr(mocked.call_args.args))
        self.assertEqual(mocked.call_args.kwargs['input'], result[0]['ss'].encode())

    def test_host_rejects_injection(self):
        for host in ('', 'foo/bar', 'foo@bar', 'foo\nbar', '<script>', 'example.com:99'):
            with self.assertRaises(ValueError):
                self.execute('share', host=host)

    def test_ipv4_ipv6_connections_and_deduplication(self):
        listing = ('0 0 192.0.2.1:8388 192.0.2.2:50000\n'
                   '0 0 192.0.2.1:8388 192.0.2.2:50001\n'
                   '0 0 [::]:8388 [::ffff:192.0.2.3]:50002\n'
                   '0 0 [2001:db8::1]:8388 [2001:db8::2]:50000\n'
                   '0 0 192.0.2.1:22 192.0.2.4:50000\n')
        with patch.object(admin, 'run', return_value=listing):
            result = self.execute('ips')
        self.assertEqual(result[0]['ip_count'], 3)
        self.assertEqual(result[0]['ips'], ['192.0.2.2', '192.0.2.3', '2001:db8::2'])


class BackendTests(unittest.TestCase):
    def test_patch_both_ip_families_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'server.py'
            source = """def make(config, password_obfs):
    protocol_param = password_obfs.get('protocol_param', protocol_param)
    tcp_servers = config.get('relays', [])
    udp_servers = []
    dns_resolver = None
    stat_counter_dict = None
    a_config = config.copy()
    udp_servers.append(udprelay.UDPRelay(a_config, dns_resolver, False, stat_counter=stat_counter_dict))
    ipv6 = a_config
    a_config = config.copy()
    udp_servers.append(udprelay.UDPRelay(a_config, dns_resolver, False, stat_counter=stat_counter_dict))
    def run_server():
        pass
    return ipv6, a_config, udp_servers
"""
            path.write_text(source)
            self.assertTrue(backend.patch_server(path)['patched'])
            self.assertFalse(backend.patch_server(path)['patched'])
            patched = path.read_text()
            self.assertEqual(patched.count(backend.MARKER), 2)
            # Evaluate both independently with fixture excluding the unrelated getter.
            namespace = {'udprelay': types.SimpleNamespace(UDPRelay=lambda *a, **k: a[0])}
            exec(patched.replace("    protocol_param = password_obfs.get('protocol_param', protocol_param)\n", ''), namespace)
            configs = namespace['make']({'speed_limit_per_user': 0}, {'speed_limit_per_user': 9})
            self.assertEqual([c['speed_limit_per_user'] for c in configs[:2]], [9, 9])
            self.assertEqual(configs[2], [])
            # UDP remains available with neither limit enabled.
            self.assertEqual(len(namespace['make']({}, {})[2]), 2)
            self.assertEqual(namespace['make']({}, {'ssr_admin_devices': 3})[2], [])
            def relay(port):
                return types.SimpleNamespace(_listen_port=port, protocol_data=object(),
                    _speed_tester_u={}, _speed_tester_d={})
            v4, v6, other = relay(8388), relay(8388), relay(8390)
            namespace['make']({'relays': [v4, v6, other]}, {})
            self.assertIs(v4.protocol_data, v6.protocol_data)
            self.assertIs(v4._speed_tester_u, v6._speed_tester_u)
            self.assertIsNot(v4.protocol_data, other.protocol_data)
            self.assertEqual(path.with_name('server.py.before-ssr-admin').read_text(), source)

    def test_unknown_backend_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'server.py'
            path.write_text('print("unknown")')
            with self.assertRaises(ValueError):
                backend.patch_server(path)
            self.assertEqual(path.read_text(), 'print("unknown")')


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.state = patch.object(system, 'STATE', self.directory)
        self.state.start()
        self.addCleanup(self.state.stop)
        self.file = self.directory / 'bbr.conf'
        self.file_patch = patch.object(system, 'BBR_FILE', self.file)
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)

    def test_bbr_enable_disable_restores_prior_file_and_values(self):
        self.file.write_text('# previous contents\n')
        values = {system.BBR_KEYS[0]: 'fq_codel', system.BBR_KEYS[1]: 'cubic'}
        def command(*args, **kwargs):
            if args[:2] == ('sysctl', '-n'):
                if args[2] == 'net.ipv4.tcp_available_congestion_control':
                    return 'reno cubic bbr'
                return values[args[2]]
            if args[:2] == ('sysctl', '-w'):
                key, value = args[2].split('=')
                values[key] = value
            return ''
        with patch.object(system, 'command', side_effect=command):
            self.assertEqual(system.bbr('enable')[system.BBR_KEYS[1]], 'bbr')
            system.bbr('enable')  # repeat must preserve initial snapshot
            self.assertEqual(system.bbr('disable')[system.BBR_KEYS[1]], 'cubic')
        self.assertEqual(self.file.read_text(), '# previous contents\n')
        self.assertEqual(values[system.BBR_KEYS[0]], 'fq_codel')

    def test_bbr_failure_restores_values(self):
        values = {system.BBR_KEYS[0]: 'fq_codel', system.BBR_KEYS[1]: 'cubic'}
        def command(*args, **kwargs):
            if args[:2] == ('sysctl', '-n'):
                return 'cubic bbr' if args[2].endswith('available_congestion_control') else values[args[2]]
            if args[:2] == ('sysctl', '-w'):
                key, value = args[2].split('=')
                if value == 'bbr':
                    raise subprocess.CalledProcessError(1, args)
                values[key] = value
            return ''
        with patch.object(system, 'command', side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError):
                system.bbr('enable')
        self.assertEqual(values[system.BBR_KEYS[0]], 'fq_codel')
        self.assertFalse(self.file.exists())

    def test_firewall_both_families_and_scoped_rules(self):
        calls = []
        def command(*args, **kwargs):
            calls.append((args, kwargs))
            return '-P OUTPUT ACCEPT\n' if '-S' in args else ''
        fake_pwd = types.SimpleNamespace(getpwnam=lambda n: types.SimpleNamespace(pw_uid=123))
        with patch.dict(sys.modules, {'pwd': fake_pwd}), patch.object(system, 'command', side_effect=command), patch.object(system.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)):
            result = system.firewall('enable', {'feature': 'all'})
        self.assertEqual(result['configured'], {'smtp': True, 'bt': True})
        for tool in ('iptables-restore', 'ip6tables-restore'):
            restores = [(a, kw) for a, kw in calls if a[0] == tool]
            self.assertEqual(len(restores), 2)
            self.assertIn('--test', restores[0][0])
            rules = restores[1][1]['input']
            self.assertIn('--uid-owner 123', rules)
            self.assertIn('--dports 25,465,587', rules)
            self.assertNotIn('-F OUTPUT', rules)
            self.assertNotIn(':OUTPUT', rules)
            self.assertIn('BitTorrent protocol', rules)

    def test_firewall_ipv6_failure_rolls_back_and_does_not_persist(self):
        calls = []
        def command(*args, **kwargs):
            calls.append((args, kwargs))
            if '-S' in args:
                return '-N SSR_ADMIN_EGRESS\n-A SSR_ADMIN_EGRESS -j RETURN\n'
            if args[0] == 'ip6tables-restore' and '--test' in args:
                raise subprocess.CalledProcessError(1, args)
            return ''
        fake_pwd = types.SimpleNamespace(getpwnam=lambda n: types.SimpleNamespace(pw_uid=123))
        with patch.dict(sys.modules, {'pwd': fake_pwd}), patch.object(system, 'command', side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError):
                system.firewall('enable', {'feature': 'all'})
        self.assertFalse((self.directory / 'firewall.json').exists())
        self.assertTrue(any('-A SSR_ADMIN_EGRESS -j RETURN' in kw.get('input', '') for _, kw in calls))

    def test_firewall_disable_empty_rules(self):
        self.assertEqual(system.firewall_rules(123, {'smtp': False, 'bt': False}), [])

    def test_ruisu_missing_package_refuses_install(self):
        self.assertFalse(system.ruisu('status')['available'])
        with self.assertRaises(ValueError):
            system.ruisu('install')

    def test_ruisu_mismatched_kernel_and_hash_refused(self):
        manifest = self.directory / 'serverspeeder.json'
        package = self.directory / 'install.sh'
        package.write_text('exit 0')
        with patch.object(system, 'trusted_file', side_effect=Path):
            manifest.write_text(json.dumps({'kernel': 'wrong', 'architecture': 'wrong'}))
            with self.assertRaisesRegex(ValueError, '不匹配'):
                system.ruisu('install')
            manifest.write_text(json.dumps({'kernel': system.platform.release(),
                'architecture': system.platform.machine(), 'installer': str(package), 'sha256': 'wrong'}))
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                system.ruisu('install')


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = 'a' * 64
        ready = queue.Queue()
        original = admin.HTTPServer
        def create(address, handler):
            server = original(address, handler)
            ready.put(server)
            return server
        cls.factory = patch.object(admin, 'HTTPServer', side_effect=create)
        cls.factory.start()
        cls.thread = threading.Thread(target=admin.serve,
            args=(Path('/unused/config.json'), 0, cls.token), daemon=True)
        cls.thread.start()
        cls.server = ready.get(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.factory.stop()

    def request(self, op='list', token=None, origin=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if origin:
            headers['Origin'] = origin
        connection.request('POST', '/api', json.dumps({'op': op, 'data': {}}), headers)
        response = connection.getresponse()
        status, body = response.status, json.loads(response.read())
        connection.close()
        return status, body

    def test_unauthorized_does_not_execute(self):
        with patch.object(admin, 'execute') as execute:
            self.assertEqual(self.request()[0], 401)
            self.assertEqual(self.request(token='wrong')[0], 401)
            execute.assert_not_called()

    def test_authenticated_api(self):
        with patch.object(admin, 'execute', return_value={'accounts': []}) as execute:
            self.assertEqual(self.request(token=self.token), (200, {'accounts': []}))
            execute.assert_called_once()

    def test_external_origin_rejected(self):
        with patch.object(admin, 'execute') as execute:
            self.assertEqual(self.request(token=self.token, origin='https://evil.example')[0], 400)
            execute.assert_not_called()

    def test_web_cannot_run_local_installer_or_patch(self):
        with patch.object(admin, 'execute') as execute:
            for op in ('ruisu', 'backend-patch', 'shell'):
                self.assertEqual(self.request(op=op, token=self.token)[0], 400)
            execute.assert_not_called()

    def test_page_headers_and_local_binding(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        connection.request('GET', '/')
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        self.assertEqual(response.getheader('X-Frame-Options'), 'DENY')
        self.assertIn(b'qr', response.read())
        connection.close()


if __name__ == '__main__':
    unittest.main()
