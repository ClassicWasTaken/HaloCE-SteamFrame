import hashlib
import json
import socket
import subprocess
import sys
from unittest.mock import Mock

import paramiko
import pytest

from halo_frame_installer import usb
from halo_frame_installer.ssh import Settings, SSHConnection, SSHError, _VerifyHost, fingerprint


@pytest.fixture
def forward(monkeypatch, tmp_path):
    adb = tmp_path / 'adb.exe'
    adb.write_bytes(b'offline-test')
    return usb.USBForward(str(adb))


def test_physical_usb_detection_forward_and_own_cleanup(forward, monkeypatch):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    active = True
    calls = []
    def run(*args):
        nonlocal active
        calls.append(args)
        if args == ('-d', 'get-serialno'):
            return 'FRAME123'
        if args == ('-s', 'FRAME123', 'forward', '--no-rebind', 'tcp:0', 'tcp:22'):
            return str(port)
        if args == ('forward', '--list'):
            return f'FRAME123 tcp:{port} tcp:22\nOTHER tcp:5555 tcp:5555' if active else 'OTHER tcp:5555 tcp:5555'
        if args == ('-s', 'FRAME123', 'forward', '--remove', f'tcp:{port}'):
            active = False
            return ''
        raise AssertionError(args)
    monkeypatch.setattr(forward, '_run', run)
    try:
        assert forward.open() == ('FRAME123', port)
        forward.close()
        forward.close()
        assert forward.port is None
        assert sum('--remove' in call for call in calls) == 1
        assert not any(word in call for call in calls for word in ('kill-server', '--remove-all', 'disconnect', 'reconnect', 'tcpip'))
    finally:
        listener.close()


@pytest.mark.parametrize('address,allowed', [('127.0.0.1', True), ('0.0.0.0', False), ('127.0.0.2', False)])
def test_actual_listener_isolation(address, allowed):
    with socket.socket() as listener:
        listener.bind((address, 0))
        listener.listen()
        if allowed:
            usb.verify_loopback_listener(listener.getsockname()[1])
        else:
            with pytest.raises(usb.USBError, match='refused to send'):
                usb.verify_loopback_listener(listener.getsockname()[1])


@pytest.mark.parametrize('ipv6,allowed', [('::1', True), ('::', False)])
def test_dual_stack_listener_isolation(ipv6, allowed):
    with socket.socket() as ipv4, socket.socket(socket.AF_INET6) as ipv6_socket:
        ipv4.bind(('127.0.0.1', 0))
        ipv4.listen()
        port = ipv4.getsockname()[1]
        try:
            ipv6_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            ipv6_socket.bind((ipv6, port))
            ipv6_socket.listen()
        except OSError:
            pytest.skip('IPv6 loopback is unavailable on this host')
        if allowed:
            usb.verify_loopback_listener(port)
        else:
            with pytest.raises(usb.USBError, match='refused to send'):
                usb.verify_loopback_listener(port)


def test_exposed_listener_is_removed_before_password_can_be_used(forward, monkeypatch):
    calls = []
    rows = iter(['FRAME123 tcp:30001 tcp:22', 'FRAME123 tcp:30001 tcp:22', ''])
    def run(*args):
        calls.append(args)
        if args == ('-d', 'get-serialno'):
            return 'FRAME123'
        if '--no-rebind' in args:
            return '30001'
        if args == ('forward', '--list'):
            return next(rows)
        return ''
    monkeypatch.setattr(forward, '_run', run)
    monkeypatch.setattr(usb, 'verify_loopback_listener', Mock(side_effect=usb.USBError('Exposed listener')))
    with pytest.raises(usb.USBError, match='Exposed'):
        forward.open()
    assert ('-s', 'FRAME123', 'forward', '--remove', 'tcp:30001') in calls
    assert forward.port is None


def test_rebound_forward_belonging_to_other_app_is_never_removed(forward, monkeypatch):
    forward.serial, forward.port = 'FRAME123', 31001
    run = Mock(return_value='OTHER tcp:31001 tcp:22')
    monkeypatch.setattr(forward, '_run', run)
    with pytest.raises(usb.USBError, match='ownership'):
        forward.close()
    run.assert_called_once_with('forward', '--list')


def test_absent_forward_needs_no_removal(forward, monkeypatch):
    forward.serial, forward.port = 'FRAME123', 31001
    run = Mock(return_value='OTHER tcp:5555 tcp:5555')
    monkeypatch.setattr(forward, '_run', run)
    forward.close()
    assert forward.port is None
    run.assert_called_once_with('forward', '--list')


@pytest.mark.parametrize('path', ['tcp:frame:5555', '', 'unknown'])
def test_explicit_serial_cannot_select_network_or_unverified_device(forward, monkeypatch, path):
    forward.serial = 'FRAME123'
    run = Mock(return_value=path)
    monkeypatch.setattr(forward, '_run', run)
    with pytest.raises(usb.USBError, match='physical USB'):
        forward.open()
    run.assert_called_once_with('-s', 'FRAME123', 'get-devpath')


@pytest.mark.parametrize('response', ['', '0', '65536', '31\n99', 'unknown'])
def test_invalid_forward_response_refused(forward, monkeypatch, response):
    monkeypatch.setattr(forward, '_run', Mock(side_effect=['FRAME123', response]))
    with pytest.raises(usb.USBError, match='valid transfer port'):
        forward.open()


@pytest.mark.parametrize('diagnostic,expected', [
    ('device unauthorized', 'Approve the USB'), ('more than one device', 'More than one'),
    ('device offline', 'offline'), ('private arbitrary diagnostic', 'data-capable cable')])
def test_device_failures_are_actionable_and_subprocess_text_redacted(forward, monkeypatch, diagnostic, expected):
    monkeypatch.setattr(subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 1, '', diagnostic)))
    with pytest.raises(usb.USBError, match=expected) as error:
        forward._execute('-d', 'get-serialno')
    assert 'private arbitrary' not in str(error.value)


def test_process_timeout_is_bounded_without_exposing_arbitrary_output(forward, monkeypatch):
    run = Mock(side_effect=subprocess.TimeoutExpired('private command', 20, output='secret'))
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(usb.USBError, match='timed out'):
        forward._execute('-d', 'get-serialno')


def test_client_uses_local_server_and_sanitizes_inherited_overrides(forward, monkeypatch):
    for name in ('ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT', 'ADB_SERVER_PORT', 'ANDROID_SERIAL'):
        monkeypatch.setenv(name, 'malicious-remote')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, 'FRAME123', ''))
    monkeypatch.setattr(subprocess, 'run', run)
    assert forward._execute('-d', 'get-serialno') == 'FRAME123'
    assert run.call_args.args[0][1:] == ['-H', 'localhost', '-P', '5037', '-d', 'get-serialno']
    options = run.call_args.kwargs
    assert options['shell'] is False and options['timeout'] == 20
    assert all(name not in options['env'] for name in ('ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT', 'ADB_SERVER_PORT', 'ANDROID_SERIAL'))


def _server_reply(monkeypatch, protocol):
    server = Mock()
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)
    response = list(b'OKAY0004' + f'{protocol:04x}'.encode())
    server.recv.side_effect = lambda count: bytes([response.pop(0)])
    monkeypatch.setattr(socket, 'create_connection', Mock(return_value=server))
    return server


def test_existing_shared_server_version_is_verified_including_partial_packets(forward, monkeypatch):
    execute = Mock(side_effect=['Android Debug Bridge version 1.0.41', 'FRAME123'])
    monkeypatch.setattr(forward, '_execute', execute)
    server = _server_reply(monkeypatch, 41)
    assert forward._run('-d', 'get-serialno') == 'FRAME123'
    server.sendall.assert_called_once_with(b'000chost:version')


def test_incompatible_server_is_not_killed_or_queried_by_adb(forward, monkeypatch):
    execute = Mock(return_value='Android Debug Bridge version 1.0.41')
    monkeypatch.setattr(forward, '_execute', execute)
    _server_reply(monkeypatch, 40)
    with pytest.raises(usb.USBError, match='different ADB server version'):
        forward._run('-d', 'get-serialno')
    execute.assert_called_once_with('version')


def test_no_existing_server_allows_normal_local_start(forward, monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', Mock(side_effect=ConnectionRefusedError))
    execute = Mock(side_effect=['Android Debug Bridge version 1.0.41', 'FRAME123'])
    monkeypatch.setattr(forward, '_execute', execute)
    assert forward._run('-d', 'get-serialno') == 'FRAME123'


def test_usb_ssh_uses_private_endpoint_and_resolved_durable_identity(monkeypatch):
    client = Mock()
    forward = Mock()
    forward.open.return_value = ('FRAME123', 31001)
    monkeypatch.setattr(paramiko, 'SSHClient', Mock(return_value=client))
    monkeypatch.setattr(usb, 'USBForward', Mock(return_value=forward))
    settings = Settings('', 'secret', transport='usb')
    connection = SSHConnection(settings)
    connection.connect()
    assert client.connect.call_args.args == ('127.0.0.1',)
    assert client.connect.call_args.kwargs['port'] == 31001
    assert settings.host_identity == 'usb:FRAME123'
    sequence = []
    client.close.side_effect = lambda: sequence.append('ssh')
    forward.close.side_effect = lambda: sequence.append('usb')
    connection.close()
    assert sequence == ['ssh', 'usb']


def test_usb_authentication_failure_closes_owned_forward(monkeypatch):
    client, forward = Mock(), Mock()
    forward.open.return_value = ('FRAME123', 31001)
    client.connect.side_effect = paramiko.AuthenticationException('private-secret')
    monkeypatch.setattr(paramiko, 'SSHClient', Mock(return_value=client))
    monkeypatch.setattr(usb, 'USBForward', Mock(return_value=forward))
    connection = SSHConnection(Settings('', 'private-secret', transport='usb'))
    with pytest.raises(SSHError, match='authentication') as error:
        connection.connect()
    assert 'private-secret' not in str(error.value)
    client.close.assert_called_once()
    forward.close.assert_called_once()


def test_usb_cleanup_failure_is_reported_after_ssh_is_closed(monkeypatch):
    client, forward = Mock(), Mock()
    forward.open.return_value = ('FRAME123', 31001)
    forward.close.side_effect = usb.USBError('Cleanup failed')
    monkeypatch.setattr(paramiko, 'SSHClient', Mock(return_value=client))
    monkeypatch.setattr(usb, 'USBForward', Mock(return_value=forward))
    connection = SSHConnection(Settings('', 'secret', transport='usb'))
    connection.connect()
    with pytest.raises(SSHError, match='Cleanup failed'):
        connection.close()
    client.close.assert_called_once()
    assert connection._closed


def test_saved_usb_host_key_is_looked_up_by_serial_not_random_port():
    key = Mock()
    key.asbytes.return_value = b'frame-public-key'
    settings = Settings('', 'secret', transport='usb', usb_serial='FRAME123',
                        known_host_fingerprints={'usb:FRAME123': fingerprint(key)},
                        accept_host_key=Mock(side_effect=AssertionError('must not prompt')))
    policy = _VerifyHost(settings)
    policy.missing_host_key(Mock(), '[127.0.0.1]:31001', key)
    assert policy.accepted_fingerprint == fingerprint(key)


def test_new_usb_host_prompt_uses_durable_serial():
    key = Mock()
    key.asbytes.return_value = b'frame-public-key'
    key.get_name.return_value = 'ssh-ed25519'
    accept = Mock(return_value=True)
    settings = Settings('', 'secret', transport='usb', usb_serial='FRAME123', accept_host_key=accept)
    _VerifyHost(settings).missing_host_key(Mock(), '[127.0.0.1]:31001', key)
    accept.assert_called_once_with('usb:FRAME123', 'ssh-ed25519', fingerprint(key))


def test_bundled_helper_and_notices_are_verified_then_cached(tmp_path, monkeypatch):
    root = tmp_path / 'bundle' / 'resources' / 'usb'
    root.mkdir(parents=True)
    files = {name: hashlib.sha256(name.encode()).hexdigest() for name in usb.ADB_FILES}
    for name in (*usb.ADB_FILES, 'NOTICE.txt'):
        (root / name).write_bytes(name.encode())
    manifest = {'version': '37.0.1', 'files': files, 'noticeSha256': hashlib.sha256(b'NOTICE.txt').hexdigest()}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(usb.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(usb.sys, '_MEIPASS', str(root.parent.parent), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    selected = usb.bundled_adb()
    assert selected == tmp_path / 'local/HaloFrameInstaller/usb-tools/37.0.1/adb.exe'
    assert (selected.parent / 'NOTICE.txt').read_bytes() == b'NOTICE.txt'
    selected.write_bytes(b'damaged-cache')
    assert usb.bundled_adb().read_bytes() == b'adb.exe'
    (root / 'AdbWinApi.dll').write_bytes(b'damaged-bundle')
    with pytest.raises(usb.USBError, match='missing or damaged'):
        usb.bundled_adb()


def test_unknown_transport_rejected():
    with pytest.raises(ValueError, match='Choose'):
        Settings('frame', 'secret', transport='other')


def _install_fake_bundle(tmp_path, monkeypatch):
    root = tmp_path / 'bundle' / 'resources' / 'usb'
    root.mkdir(parents=True)
    files = {name: hashlib.sha256(name.encode()).hexdigest() for name in usb.ADB_FILES}
    for name in (*usb.ADB_FILES, 'NOTICE.txt'):
        (root / name).write_bytes(name.encode())
    manifest = {'version': '37.0.1', 'files': files, 'noticeSha256': hashlib.sha256(b'NOTICE.txt').hexdigest()}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(usb.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(usb.sys, '_MEIPASS', str(root.parent.parent), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    return tmp_path / 'local' / 'HaloFrameInstaller' / 'usb-tools' / '37.0.1' / 'adb.exe'


def _expose_adb_on_search_path(tmp_path, monkeypatch):
    folder = tmp_path / 'search-path'
    folder.mkdir()
    # shutil.which("adb") needs an executable file named exactly "adb" on
    # POSIX and finds "adb.exe" via the Windows suffix rules, so provide both.
    for name in ('adb', 'adb.exe'):
        shadow = folder / name
        shadow.write_bytes(b'shadowing adb')
        shadow.chmod(0o755)
    # shutil.which on Windows searches the working directory before PATH.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PATH', str(folder))
    return (folder / ('adb.exe' if sys.platform == 'win32' else 'adb')).resolve()


def test_hash_verified_bundle_is_preferred_over_search_path_adb(tmp_path, monkeypatch):
    bundled = _install_fake_bundle(tmp_path, monkeypatch)
    _expose_adb_on_search_path(tmp_path, monkeypatch)
    assert usb.resolve_adb() == bundled


def test_search_path_adb_is_used_when_no_bundle_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(usb.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(usb.sys, '_MEIPASS', str(tmp_path / 'no-bundle'), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    shadow = _expose_adb_on_search_path(tmp_path, monkeypatch)
    assert usb.resolve_adb() == shadow


def test_explicitly_selected_adb_wins_over_bundle_and_search_path(tmp_path, monkeypatch):
    _install_fake_bundle(tmp_path, monkeypatch)
    _expose_adb_on_search_path(tmp_path, monkeypatch)
    chosen = tmp_path / 'chosen' / 'adb.exe'
    chosen.parent.mkdir()
    chosen.write_bytes(b'user selected adb')
    assert usb.resolve_adb(str(chosen)) == chosen.resolve()
