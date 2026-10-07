import threading
from unittest.mock import Mock

import paramiko
import pytest

from halo_frame_installer.ssh import CancelledError, RemoteTimeoutError, Settings, SSHConnection, SSHError, _VerifyHost, fingerprint, validate_host


@pytest.mark.parametrize("host", ["192.168.1.12", "frame.local", "frame", "::1"])
def test_host_accepts_network_addresses(host):
    assert validate_host(host) == host


@pytest.mark.parametrize("host", ["", "ssh://frame", "frame;rm -rf /", "frame\nother", "-host", "user@frame", "a..b"])
def test_host_rejects_command_or_url_input(host):
    with pytest.raises(ValueError):
        validate_host(host)


def test_settings_does_not_display_password():
    value = Settings("frame", "my-private-password")
    assert "my-private-password" not in repr(value)
    with pytest.raises(ValueError):
        Settings("frame", "password", username="root")


def test_new_host_requires_approval_before_trust():
    key = Mock()
    key.asbytes.return_value = b"public key"
    key.get_name.return_value = "ssh-ed25519"
    client = Mock()
    policy = _VerifyHost(Settings("frame", "password", accept_host_key=lambda host, kind, fp: False))
    with pytest.raises(SSHError, match="not approved"):
        policy.missing_host_key(client, "frame", key)
    client.get_host_keys.assert_not_called()


def test_matching_saved_host_key_works_without_another_prompt():
    key = Mock()
    key.asbytes.return_value = b"public key"
    key.get_name.return_value = "ssh-ed25519"
    prompt = Mock(side_effect=AssertionError("must not prompt"))
    policy = _VerifyHost(Settings("frame", "password", known_host_fingerprint=fingerprint(key), accept_host_key=prompt))
    client = Mock()
    policy.missing_host_key(client, "frame", key)
    assert policy.accepted_fingerprint == fingerprint(key)
    prompt.assert_not_called()


def test_changed_host_key_cannot_be_approved_over_a_saved_key():
    key = Mock()
    key.asbytes.return_value = b"different public key"
    prompt = Mock(return_value=True)
    policy = _VerifyHost(Settings("frame", "password", known_host_fingerprint="SHA256:old", accept_host_key=prompt))
    with pytest.raises(SSHError, match="changed"):
        policy.missing_host_key(Mock(), "frame", key)
    prompt.assert_not_called()


def test_connect_uses_memory_password_no_agent_or_disk_keys(monkeypatch):
    client = Mock()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    connection = SSHConnection(Settings("frame", "private"))
    connection.connect()
    kwargs = client.connect.call_args.kwargs
    assert kwargs["password"] == "private"
    assert kwargs["allow_agent"] is False and kwargs["look_for_keys"] is False
    client.load_system_host_keys.assert_not_called()
    client.save_host_keys.assert_not_called()


def test_authentication_error_does_not_include_secret(monkeypatch):
    client = Mock()
    client.connect.side_effect = paramiko.AuthenticationException("private password text")
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    with pytest.raises(SSHError) as error:
        SSHConnection(Settings("frame", "private password text")).connect()
    assert "private password text" not in str(error.value)


def test_disconnect_releases_even_an_inactive_transport_socket():
    import socket
    left, right = socket.socketpair()
    try:
        connection = SSHConnection(Settings('frame', 'private'))
        transport = paramiko.Transport(left)
        connection.client._transport = transport
        assert not transport.is_active()
        connection.close()
        assert left.fileno() == -1
        assert right.recv(1) == b''
        assert connection.client.get_transport() is None
        connection.close()  # Closing an already completed setup is safe.
    finally:
        left.close()
        right.close()


def test_disconnect_still_closes_transport_when_a_channel_close_fails(monkeypatch):
    client = Mock()
    transport = client.get_transport.return_value
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    command = Mock()
    command.close.side_effect = OSError('Already closed')
    sftp = Mock()
    connection._command_channels.add(command)
    connection._sftp_clients.add(sftp)
    connection.close()
    command.close.assert_called_once()
    sftp.close.assert_called_once()
    transport.close.assert_called_once()
    transport.sock.close.assert_called_once()
    client.close.assert_called_once()
    assert not connection._command_channels and not connection._sftp_clients
    connection.close()
    client.close.assert_called_once()


@pytest.mark.parametrize('output,expected', [
    (b'HFI_PROGRESS {"stage":"build","message":"Working"}\nHFI_ERROR Native build failed.\nE: setgroups failed\nprivate\n',
     'Native build failed.\nE: setgroups failed\n[redacted]'),
    (b'HFI_PROGRESS {}\nHFI_RESULT {}\n', 'Remote step failed (exit 1).'),
    (b'HFI_LOG {"stage":"compile","message":"[22/100] task"}\nHFI_ERROR Native build failed.\ncompiler diagnostic private\n',
     'Native build failed.\ncompiler diagnostic [redacted]'),
    (b'connection helper failed\n', 'connection helper failed'),
])
def test_remote_failure_shows_diagnostic_without_progress_protocol(monkeypatch, output, expected):
    client = Mock()
    channel = Mock()
    states = iter([True, False, False])
    channel.recv_ready.side_effect = lambda: next(states)
    channel.recv.return_value = output
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = 1
    stdout = Mock(channel=channel)
    client.exec_command.return_value = (Mock(), stdout, Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    progress = Mock()
    with pytest.raises(SSHError) as error:
        connection.run(['python3', 'helper.py', 'build'], progress=progress)
    assert str(error.value) == expected
    assert all('HFI_PROGRESS' not in line for line in str(error.value).splitlines())
    assert progress.called
    channel.close.assert_called_once()


def test_long_remote_failure_keeps_summary_and_final_linker_diagnostic(monkeypatch):
    summary = 'Native build failed. The existing game was kept.'
    output = ('HFI_ERROR ' + summary + '\n'
              + '[1372/1613] LINUX ARM64 CC intermediate_radiosity.o\n' * 300
              + 'ld.lld: error: undefined symbol: halo_vr_active\n'
              + 'compiler diagnostic private\n').encode()
    client = Mock()
    channel = Mock()
    states = iter([True, False, False])
    channel.recv_ready.side_effect = lambda: next(states)
    channel.recv.return_value = output
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = 1
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    with pytest.raises(SSHError) as error:
        connection.run(['python3', 'helper.py', 'build'])
    message = str(error.value)
    assert message.startswith(summary + '\n')
    assert 'ld.lld: error: undefined symbol: halo_vr_active' in message
    assert '[earlier details omitted]' in message
    assert '[redacted]' in message and 'private' not in message
    assert len(message) <= 12000 and 'HFI_ERROR' not in message
    channel.close.assert_called_once()


def test_long_live_activity_is_forwarded_but_response_memory_is_bounded(monkeypatch):
    from collections import deque
    line = b'HFI_LOG {"stage":"compile","message":"' + b'x' * 1024 + b'"}\n'
    output = line * 800 + b'HFI_RESULT {"built":true}\n'
    packets = deque(output[index:index + 65536] for index in range(0, len(output), 65536))
    channel = Mock()
    channel.recv_ready.side_effect = lambda: bool(packets)
    channel.recv.side_effect = lambda count: packets.popleft()
    channel.exit_status_ready.side_effect = lambda: not packets
    channel.recv_exit_status.return_value = 0
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    progress = Mock()
    result = SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py', 'build'], progress=progress)
    assert progress.call_count == 801
    assert progress.call_args.args[0] == 'HFI_RESULT {"built":true}'
    assert len(result.encode()) <= 256 * 1024
    assert result.endswith('HFI_RESULT {"built":true}\n')
    channel.close.assert_called_once()


def test_utf8_activity_split_between_ssh_packets_is_preserved(monkeypatch):
    from collections import deque
    output = 'HFI_LOG {"stage":"compile","message":"Compiled café"}\nHFI_RESULT {}\n'.encode()
    split = output.index('é'.encode()) + 1
    packets = deque((output[:split], output[split:]))
    channel = Mock()
    channel.recv_ready.side_effect = lambda: bool(packets)
    channel.recv.side_effect = lambda count: packets.popleft()
    channel.exit_status_ready.side_effect = lambda: not packets
    channel.recv_exit_status.return_value = 0
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    progress = Mock()
    SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'], progress=progress)
    assert progress.call_args_list[0].args[0] == 'HFI_LOG {"stage":"compile","message":"Compiled café"}'


def test_uninstall_timeout_reports_uncertain_removal_and_closes_channel(monkeypatch):
    from halo_frame_installer import ssh
    channel = Mock()
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    clock = Mock(return_value=0)
    monkeypatch.setattr(ssh.time, 'monotonic', clock)
    channel.set_combine_stderr.side_effect = lambda value: setattr(clock, 'return_value', 601)
    connection = SSHConnection(Settings('frame', 'private'))
    with pytest.raises(SSHError, match='Removal may be incomplete') as error:
        connection.run(['python3', 'helper.py', 'uninstall'], timeout=600,
                       timeout_message='Removal may be incomplete; check the saved backup and activity log.')
    assert 'were kept' not in str(error.value)
    channel.close.assert_called_once()
    assert not connection._command_channels


@pytest.mark.parametrize('failure', [paramiko.SSHException('SSH session not active'), SSHError('cancel command failed'), EOFError('private'), ValueError('private')])
def test_failed_cancel_notice_does_not_mask_the_cancellation(monkeypatch, failure):
    channel = Mock()
    channel.recv_ready.return_value = False
    channel.exit_status_ready.return_value = False
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    cancel = threading.Event()
    cancel.set()
    on_cancel = Mock(side_effect=failure)
    with pytest.raises(CancelledError, match='cancelled'):
        SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'],
                                                        cancel_event=cancel, on_cancel=on_cancel)
    on_cancel.assert_called_once()


def test_failed_command_start_reports_a_connection_problem(monkeypatch):
    client = Mock()
    client.exec_command.side_effect = paramiko.SSHException('SSH session not active')
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    with pytest.raises(SSHError, match='could not be started'):
        SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'])


@pytest.mark.parametrize('cancelled', [False, True])
def test_failed_sftp_open_reports_connection_problem_or_cancellation(monkeypatch, cancelled):
    client = Mock()
    client.open_sftp.side_effect = paramiko.SSHException('SSH session not active')
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    cancel = threading.Event()
    if cancelled:
        cancel.set()
    with pytest.raises(CancelledError if cancelled else SSHError) as error:
        SSHConnection(Settings('frame', 'private')).put('local.txt', 'remote.txt', cancel_event=cancel)
    if not cancelled:
        assert 'transfer stopped' in str(error.value)


def test_failed_cancel_notice_does_not_mask_the_timeout_error(monkeypatch):
    from halo_frame_installer import ssh
    channel = Mock()
    channel.recv_ready.return_value = False
    channel.exit_status_ready.return_value = False
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    clock = Mock(return_value=0)
    monkeypatch.setattr(ssh.time, 'monotonic', clock)
    channel.set_combine_stderr.side_effect = lambda value: setattr(clock, 'return_value', 601)
    on_cancel = Mock(side_effect=paramiko.SSHException('SSH session not active'))
    with pytest.raises(SSHError, match='timed out'):
        SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'], timeout=600, on_cancel=on_cancel)
    on_cancel.assert_called_once()


@pytest.mark.parametrize('failure', [EOFError('private'), paramiko.SSHException('private'), OSError('private')])
def test_command_start_errors_are_redacted_without_exposing_a_cause(monkeypatch, failure):
    client = Mock()
    client.exec_command.side_effect = failure
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    with pytest.raises(SSHError, match='could not be started') as error:
        SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'])
    assert 'private' not in str(error.value)
    assert error.value.__suppress_context__ and error.value.__cause__ is None


def test_cancel_during_failed_command_start_remains_a_cancellation(monkeypatch):
    cancel = threading.Event()
    client = Mock()
    def fail(*args, **kwargs):
        cancel.set()
        raise EOFError('private')
    client.exec_command.side_effect = fail
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    on_cancel = Mock(side_effect=EOFError('private'))
    with pytest.raises(CancelledError, match='cancelled') as error:
        SSHConnection(Settings('frame', 'private')).run(['helper'], cancel_event=cancel, on_cancel=on_cancel)
    on_cancel.assert_called_once()
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('failing_method', ['set_combine_stderr', 'recv_ready', 'recv', 'recv_exit_status'])
def test_channel_setup_and_read_errors_are_redacted_and_closed(monkeypatch, failing_method):
    channel = Mock()
    channel.recv_ready.return_value = failing_method == 'recv'
    channel.exit_status_ready.return_value = True
    getattr(channel, failing_method).side_effect = EOFError('private')
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    with pytest.raises(SSHError, match='connection stopped') as error:
        SSHConnection(Settings('frame', 'private')).run(['helper'])
    assert 'private' not in str(error.value) and error.value.__suppress_context__
    channel.close.assert_called_once()


def test_channel_close_failure_cannot_replace_the_timeout(monkeypatch):
    from halo_frame_installer import ssh
    channel = Mock()
    channel.close.side_effect = paramiko.SSHException('private')
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    clock = Mock(return_value=0)
    monkeypatch.setattr(ssh.time, 'monotonic', clock)
    channel.set_combine_stderr.side_effect = lambda value: setattr(clock, 'return_value', 601)
    connection = SSHConnection(Settings('frame', 'private'))
    with pytest.raises(ssh.RemoteTimeoutError, match='timed out'):
        connection.run(['helper'], timeout=600)
    assert channel in connection._command_channels
    connection.close()
    assert not connection._command_channels
    client.close.assert_called_once()


@pytest.mark.parametrize('failure_step', ['timeout', 'put'])
def test_sftp_setup_and_transfer_failure_survive_a_failed_close(monkeypatch, failure_step):
    client, sftp = Mock(), Mock()
    client.open_sftp.return_value = sftp
    sftp.close.side_effect = EOFError('private')
    target = sftp.get_channel.return_value.settimeout if failure_step == 'timeout' else sftp.put
    target.side_effect = paramiko.SSHException('private')
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    with pytest.raises(SSHError, match='transfer stopped') as error:
        connection.put('local.txt', 'remote.txt')
    assert 'private' not in str(error.value)
    assert sftp in connection._sftp_clients
    connection.close()
    assert not connection._sftp_clients


def test_sftp_callback_cancellation_survives_a_failed_close(monkeypatch):
    client, sftp = Mock(), Mock()
    client.open_sftp.return_value = sftp
    sftp.close.side_effect = EOFError('private')
    cancel = threading.Event()
    def transfer(*args, **kwargs):
        cancel.set()
        kwargs['callback'](1, 2)
    sftp.put.side_effect = transfer
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    with pytest.raises(CancelledError, match='cancelled') as error:
        SSHConnection(Settings('frame', 'private')).put('local.txt', 'remote.txt', cancel_event=cancel)
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('failure_step', ['connect', 'keepalive'])
def test_eof_connect_or_keepalive_failure_is_redacted_and_tears_down(monkeypatch, failure_step):
    client = Mock()
    target = client.connect if failure_step == 'connect' else client.get_transport.return_value.set_keepalive
    target.side_effect = EOFError('private')
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    with pytest.raises(SSHError, match='Could not connect') as error:
        SSHConnection(Settings('frame', 'private')).connect()
    assert 'private' not in str(error.value)
    client.close.assert_called_once()


def test_silent_exec_handshake_is_bounded_by_a_watchdog(monkeypatch):
    import time as time_module
    release = threading.Event()
    transport = Mock()
    transport.close.side_effect = release.set
    client = Mock()
    client.get_transport.return_value = transport

    def blocked_exec(command, timeout=None):
        release.wait(60)
        raise paramiko.SSHException('SSH session not active')

    client.exec_command.side_effect = blocked_exec
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    connection.handshake_grace = 0.05
    started = time_module.monotonic()
    with pytest.raises(RemoteTimeoutError, match='handshake timed out'):
        connection.run(['python3', 'helper.py'], timeout=0.5)
    assert time_module.monotonic() - started < 5  # unbounded waits defeat this without the watchdog


def test_newline_free_flood_keeps_only_the_recent_tail(monkeypatch):
    from collections import deque
    payload = b'A' * (2 * 1024 * 1024) + b'B\n'
    packets = deque(payload[index:index + 65536] for index in range(0, len(payload), 65536))
    channel = Mock()
    channel.recv_ready.side_effect = lambda: bool(packets)
    channel.recv.side_effect = lambda count: packets.popleft()
    channel.exit_status_ready.side_effect = lambda: not packets
    channel.recv_exit_status.return_value = 0
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    lines = []
    SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'], progress=lines.append)
    assert lines and len(lines[-1]) < 200 * 1024


def test_cancel_is_honored_inside_a_readable_channel(monkeypatch):
    cancel = threading.Event()
    calls = [0]
    channel = Mock()
    channel.recv_ready.return_value = True
    channel.exit_status_ready.return_value = False

    def recv(count):
        calls[0] += 1
        if calls[0] == 3:
            cancel.set()
        return b'y' * 65536

    channel.recv.side_effect = recv
    client = Mock()
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    with pytest.raises(CancelledError):
        SSHConnection(Settings('frame', 'private')).run(['python3', 'helper.py'], cancel_event=cancel)


def assert_no_handshake_watchdog():
    assert not any(thread.name == 'ssh-handshake-watchdog' for thread in threading.enumerate())


def test_healthy_upload_can_outlast_the_handshake_budget(monkeypatch):
    import time
    client, sftp, transport = Mock(), Mock(), Mock()
    client.get_transport.return_value = transport
    client.open_sftp.return_value = sftp
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    connection.sftp_timeout = 0.02
    connection.handshake_grace = 0.03
    progress = Mock()

    def transfer(local, remote, *, callback, confirm):
        # Scale the handshake budget down while the healthy upload lasts four
        # times longer. The upload must never inherit the handshake deadline.
        assert_no_handshake_watchdog()
        for count in range(4):
            time.sleep(0.05)
            callback(count + 1, 4)
            transport.close.assert_not_called()

    sftp.put.side_effect = transfer
    connection.put('local.map', 'remote.map', callback=progress)
    assert progress.call_count == 4
    sftp.close.assert_called_once()
    assert not connection._sftp_clients
    assert_no_handshake_watchdog()


@pytest.mark.parametrize('operation', ['exec', 'sftp'])
@pytest.mark.parametrize('fail', [False, True])
def test_handshake_watchdog_retires_after_success_or_error(monkeypatch, operation, fail):
    import time
    client, channel, sftp = Mock(), Mock(), Mock()
    channel.recv_ready.return_value = False
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = 0
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    client.open_sftp.return_value = sftp
    target = client.exec_command if operation == 'exec' else client.open_sftp
    if fail:
        target.side_effect = EOFError('private')
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    connection.sftp_timeout = 0.02
    connection.handshake_grace = 0.03
    cancel = threading.Event()
    invoke = (lambda: connection.run(['helper'], timeout=0.2, cancel_event=cancel)) if operation == 'exec' else (
        lambda: connection.put('local', 'remote', cancel_event=cancel))
    if fail:
        with pytest.raises(SSHError):
            invoke()
    else:
        invoke()
    assert_no_handshake_watchdog()
    # A late cancel/deadline must not affect a following operation's transport.
    cancel.set()
    time.sleep(0.3)
    client.get_transport.return_value.close.assert_not_called()


def test_cancel_recovery_waits_for_watchdog_and_uses_captured_transport(monkeypatch):
    import time
    client, original, replacement = Mock(), Mock(), Mock()
    closing = threading.Event()
    closed = threading.Event()
    cancel = threading.Event()
    client.get_transport.return_value = original

    def close():
        closing.set()
        time.sleep(0.05)
        closed.set()

    def blocked_exec(*args, **kwargs):
        cancel.set()
        assert closing.wait(2)
        client.get_transport.return_value = replacement
        raise EOFError('private')

    def recover():
        assert closed.is_set()
        assert_no_handshake_watchdog()
        replacement.close.assert_not_called()

    original.close.side_effect = close
    client.exec_command.side_effect = blocked_exec
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    recovery = Mock(side_effect=recover)
    with pytest.raises(CancelledError):
        SSHConnection(Settings('frame', 'private')).run(['helper'], cancel_event=cancel, on_cancel=recovery)
    recovery.assert_called_once()
    original.close.assert_called_once()
    replacement.close.assert_not_called()


def test_cancel_at_sftp_handshake_completion_never_starts_upload(monkeypatch):
    client, sftp = Mock(), Mock()
    cancel = threading.Event()

    def open_sftp():
        cancel.set()
        return sftp

    client.open_sftp.side_effect = open_sftp
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    with pytest.raises(CancelledError):
        connection.put('never-opened', 'never-written', cancel_event=cancel)
    sftp.put.assert_not_called()
    sftp.close.assert_called_once()
    assert not connection._sftp_clients
    assert_no_handshake_watchdog()


def test_continuous_output_still_honors_the_step_deadline(monkeypatch):
    from halo_frame_installer import ssh
    client, channel = Mock(), Mock()
    clock = Mock(return_value=0)
    channel.recv_ready.return_value = True
    channel.exit_status_ready.return_value = False

    def recv(count):
        clock.return_value = 2
        return b'still streaming without newlines'

    channel.recv.side_effect = recv
    client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    monkeypatch.setattr(ssh.time, 'monotonic', clock)
    recovery = Mock()
    with pytest.raises(ssh.RemoteTimeoutError, match='custom step deadline'):
        SSHConnection(Settings('frame', 'private')).run(
            ['helper'], timeout=1, timeout_message='custom step deadline', on_cancel=recovery)
    recovery.assert_called_once()
    channel.recv.assert_called_once()
    channel.close.assert_called_once()
    assert_no_handshake_watchdog()


@pytest.fixture
def silent_paramiko_session():
    """A local socketpair server that never runs commands or accesses files."""
    import socket
    sessions = []

    def create(stage):
        requested, release = threading.Event(), threading.Event()

        class Server(paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                return paramiko.AUTH_SUCCESSFUL

            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED

            def check_channel_exec_request(self, channel, command):
                requested.set()
                release.wait(3)
                return False

            def check_channel_subsystem_request(self, channel, name):
                requested.set()
                if stage == 'subsystem':
                    release.wait(3)
                    return False
                # Accept SFTP but send no version packet. This reproduces the
                # additional read inside SFTPClient construction, after the
                # subsystem request itself has already succeeded.
                return True

        left, right = socket.socketpair()
        server_transport = paramiko.Transport(left)
        client_transport = paramiko.Transport(right)
        sessions.append((client_transport, server_transport, release))
        server_transport.add_server_key(paramiko.RSAKey.generate(1024))
        server_transport.start_server(event=threading.Event(), server=Server())
        client_transport.start_client(timeout=2)
        client_transport.auth_password('steamos', 'test-only')
        connection = SSHConnection(Settings('frame', 'private'))
        connection.client._transport = client_transport
        return connection, requested

    yield create
    for client, server, release in sessions:
        release.set()
        client.close()
        server.close()
        client.join(timeout=2)
        server.join(timeout=2)


@pytest.mark.parametrize('stage', ['exec', 'subsystem', 'sftp-version'])
@pytest.mark.parametrize('cancelled', [False, True])
def test_real_silent_handshake_stops_on_deadline_or_cancel(silent_paramiko_session, stage, cancelled):
    import time
    connection, requested = silent_paramiko_session(stage)
    cancel = threading.Event()
    connection.handshake_grace = 0
    connection.sftp_timeout = 20 if cancelled else 0.1
    notifier = None
    if cancelled:
        def press_cancel():
            if requested.wait(2):
                cancel.set()
        notifier = threading.Thread(target=press_cancel, daemon=True)
        notifier.start()
    recovery = Mock(side_effect=assert_no_handshake_watchdog)
    started = time.monotonic()
    try:
        expected = CancelledError if cancelled else RemoteTimeoutError if stage == 'exec' else SSHError
        with pytest.raises(expected) as error:
            if stage == 'exec':
                connection.run(['never-executed'], cancel_event=cancel,
                               timeout=30 if cancelled else 0.1, on_cancel=recovery)
            else:
                connection.put('never-opened', 'never-written', cancel_event=cancel)
        assert time.monotonic() - started < 1.5
        assert requested.is_set()
        assert not connection.is_active()
        assert 'private' not in str(error.value)
        if stage == 'exec':
            recovery.assert_called_once()
        else:
            recovery.assert_not_called()
        assert_no_handshake_watchdog()
    finally:
        if notifier is not None:
            notifier.join(timeout=2)
        connection.close()


@pytest.mark.parametrize('acknowledged', [False, True])
@pytest.mark.parametrize('recovery_fails', [False, True])
def test_exec_watchdog_timeout_preserves_uncertain_removal_after_retirement(monkeypatch, acknowledged, recovery_fails):
    import time
    original, replacement, client, channel = Mock(), Mock(), Mock(), Mock()
    closing, closed = threading.Event(), threading.Event()
    client.get_transport.return_value = original

    def close():
        closing.set()
        time.sleep(0.025)
        closed.set()

    def stalled_exec(*args, **kwargs):
        assert closing.wait(2)
        client.get_transport.return_value = replacement
        if acknowledged:
            # An acknowledgement racing the deadline must not begin streaming
            # from the closed transport or lose its timeout classification.
            return Mock(), Mock(channel=channel), Mock()
        raise EOFError('private')

    def recover():
        assert closed.is_set()
        assert_no_handshake_watchdog()
        replacement.close.assert_not_called()
        if recovery_fails:
            raise paramiko.SSHException('private recovery failure')

    original.close.side_effect = close
    client.exec_command.side_effect = stalled_exec
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    connection.handshake_grace = 0
    recovery = Mock(side_effect=recover)
    message = 'Removal may be incomplete; check the saved backup and activity log before retrying.'
    with pytest.raises(RemoteTimeoutError) as error:
        connection.run(['python3', 'helper.py', 'uninstall'], timeout=0.05,
                       timeout_message=message, on_cancel=recovery)
    assert str(error.value) == message and 'private' not in str(error.value)
    assert error.value.__suppress_context__ and error.value.__cause__ is None
    recovery.assert_called_once()
    original.close.assert_called_once()
    replacement.close.assert_not_called()
    channel.recv.assert_not_called()
    assert not connection._command_channels
    assert_no_handshake_watchdog()


def test_cancel_at_watchdog_deadline_remains_cancellation_after_retirement(monkeypatch):
    client, transport = Mock(), Mock()
    release = threading.Event()
    cancel = threading.Event()
    client.get_transport.return_value = transport
    def close():
        cancel.set()
        release.set()
    def stalled_exec(*args, **kwargs):
        assert release.wait(2)
        raise EOFError('private')
    transport.close.side_effect = close
    client.exec_command.side_effect = stalled_exec
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    connection = SSHConnection(Settings('frame', 'private'))
    connection.handshake_grace = 0
    recovery = Mock(side_effect=assert_no_handshake_watchdog)
    with pytest.raises(CancelledError) as error:
        connection.run(['helper'], timeout=0.05, cancel_event=cancel, on_cancel=recovery,
                       timeout_message='An expired deadline must not replace this cancellation.')
    assert error.value.requires_attention is False
    recovery.assert_called_once()
    assert_no_handshake_watchdog()
