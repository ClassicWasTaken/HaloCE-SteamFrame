import threading
from unittest.mock import Mock

import paramiko
import pytest

from halo_frame_installer.ssh import Settings, SSHConnection, SSHError, _VerifyHost, fingerprint, validate_host


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
