import threading
from unittest.mock import Mock

import paramiko
import pytest

from halo_frame_installer.ssh import CancelledError, Settings, SSHConnection, SSHError, _VerifyHost, fingerprint, validate_host


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
    monkeypatch.setattr(ssh.time, 'monotonic', Mock(side_effect=[0, 601]))
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
    monkeypatch.setattr(ssh.time, 'monotonic', Mock(side_effect=[0, 601]))
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
    monkeypatch.setattr(ssh.time, 'monotonic', Mock(side_effect=[0, 601]))
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
