"""Password-only SSH with explicit host-key verification and redacted errors."""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
import shlex
import socket
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import paramiko


class SSHError(RuntimeError):
    pass


class RemoteTimeoutError(SSHError):
    """A started remote operation exceeded its bounded host wait."""


class CancelledError(RuntimeError):
    """The user stopped setup; failed cleanup can still require attention."""

    requires_attention = False


def validate_host(host: str) -> str:
    """Accept an IP address or a simple DNS name, never shell/URL syntax."""
    host = host.strip()
    if not host or len(host) > 253 or any(c.isspace() for c in host):
        raise ValueError("Enter the Frame's IP address or hostname, without a URL.")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
        raise ValueError("Enter a valid IP address or hostname.")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
           for label in host.split(".")):
        raise ValueError("Enter a valid hostname.")
    return host


def fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


@dataclass
class Settings:
    host: str
    password: str = field(repr=False)
    username: str = "steamos"
    port: int = 22
    known_host_fingerprint: str | None = None
    accept_host_key: Callable[[str, str, str], bool] | None = field(default=None, repr=False)
    close_steam_for_shortcut: bool = False
    reinstall_existing: bool = True
    adopt_existing_native: bool = False
    transport: str = "network"
    adb_path: str | None = None
    usb_serial: str | None = None
    known_host_fingerprints: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.transport not in ("network", "usb"):
            raise ValueError("Choose Wi-Fi / Ethernet or USB-C transfer.")
        self.host = validate_host(self.host) if self.transport == "network" else "frame"
        if self.username != "steamos":
            raise ValueError("This installer supports the Steam Frame's steamos account.")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535.")
        if not self.password:
            raise ValueError("Enter the Frame's SSH password.")

    @property
    def host_identity(self) -> str:
        return "usb:" + (self.usb_serial or "auto") if self.transport == "usb" else f"{self.host}:{self.port}"


class _VerifyHost(paramiko.MissingHostKeyPolicy):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.accepted_fingerprint: str | None = None

    def missing_host_key(self, client, hostname, key):
        value = fingerprint(key)
        expected = (self.settings.known_host_fingerprint
                    or self.settings.known_host_fingerprints.get(self.settings.host_identity))
        if expected is not None and value != expected:
            raise SSHError("The Frame's SSH host key has changed. Connection refused. Verify the device before updating its saved fingerprint.")
        if expected is None:
            confirm = self.settings.accept_host_key
            display = self.settings.host_identity if self.settings.transport == "usb" else self.settings.host
            if confirm is None or not confirm(display, key.get_name(), value):
                raise SSHError("SSH host fingerprint was not approved.")
        self.accepted_fingerprint = value
        # Store only in this connection's memory. The GUI may persist the public fingerprint.
        client.get_host_keys().add(hostname, key.get_name(), key)


class SSHConnection:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = paramiko.SSHClient()
        self.policy = _VerifyHost(settings)
        self.client.set_missing_host_key_policy(self.policy)
        self._command_channels = set()
        self._sftp_clients = set()
        self._closed = False
        self._usb_forward = None

    @property
    def host_fingerprint(self) -> str | None:
        return self.policy.accepted_fingerprint

    def connect(self, *, timeout: float = 15) -> None:
        from .usb import USBError, USBForward
        try:
            host, port = self.settings.host, self.settings.port
            if self.settings.transport == "usb":
                self._usb_forward = USBForward(self.settings.adb_path, self.settings.usb_serial)
                self.settings.usb_serial, port = self._usb_forward.open()
                host = "127.0.0.1"
            self.client.connect(host, port=port,
                                username="steamos", password=self.settings.password,
                                allow_agent=False, look_for_keys=False,
                                timeout=timeout, auth_timeout=min(20, timeout + 5),
                                banner_timeout=min(20, timeout + 5))
            transport = self.client.get_transport()
            if transport is not None:
                transport.set_keepalive(15)
        except (paramiko.AuthenticationException, paramiko.PasswordRequiredException) as exc:
            self._close_after_failure()
            raise SSHError("SSH authentication failed. Check the Frame's steamos password.") from None
        except USBError as exc:
            self._close_after_failure()
            raise SSHError(str(exc)) from None
        except SSHError:
            self._close_after_failure()
            raise
        except (paramiko.SSHException, OSError, EOFError) as exc:
            self._close_after_failure()
            # Avoid displaying a library error that might include submitted credentials.
            message = ("Could not connect to the Frame over USB SSH. Check Developer Mode, the USB cable and the Frame's SSH service."
                       if self.settings.transport == "usb" else
                       "Could not connect to the Frame over SSH. Check its address, Wi-Fi / Ethernet connection, and SSH service.")
            raise SSHError(message) from None

    def is_active(self) -> bool:
        transport = self.client.get_transport()
        return bool(not self._closed and transport is not None and transport.is_active())

    def _close_after_failure(self) -> None:
        try:
            self.close()
        except Exception:
            pass  # Preserve the authentication/connection diagnostic.

    def close(self) -> None:
        """Release setup's channels and TCP transport before declaring it done."""
        if self._closed:
            self._close_usb_forward()
            return
        # A channel failure must not prevent the underlying socket and keepalive
        # thread from being closed. These are only resources opened by this client.
        for resource in (*self._sftp_clients, *self._command_channels):
            try:
                resource.close()
            except Exception:
                pass
        self._sftp_clients.clear()
        self._command_channels.clear()
        failures = []
        try:
            transport = self.client.get_transport()
        except Exception:
            transport = None
            failures.append("The SSH transport could not be checked during disconnection.")
        try:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    failures.append("The SSH transport could not finish closing.")
                finally:
                    # Transport.close() may return early after a failed or
                    # already inactive session. Release its socket as well.
                    sock = getattr(transport, "sock", None)
                    if sock is not None:
                        try:
                            sock.close()
                        except Exception:
                            failures.append("The setup connection's socket could not finish closing.")
        finally:
            try:
                self.client.close()
            except Exception:
                failures.append("The SSH client could not finish closing.")
            finally:
                self._closed = True
                try:
                    self._close_usb_forward()
                except SSHError as exc:
                    failures.append(str(exc))
        if failures:
            message = "\n".join(failures)
            if self.settings.password:
                message = message.replace(self.settings.password, "[redacted]")
            raise SSHError(message) from None

    def _close_usb_forward(self) -> None:
        if self._usb_forward is not None:
            from .usb import USBError
            try:
                self._usb_forward.close()
            except USBError as exc:
                raise SSHError(str(exc)) from None
            self._usb_forward = None

    handshake_grace = 5.0
    """Extra seconds a handshake may take past its step timeout before the
    transport is force-closed; paramiko's internal waits are otherwise
    unbounded on a live-but-silent session."""
    sftp_timeout = 20.0

    @contextmanager
    def _handshake_watchdog(self, timeout: float, cancel_event: threading.Event | None):
        """Interrupt only this handshake, then retire before any recovery work."""
        transport = self.client.get_transport()
        finished = threading.Event()
        deadline = time.monotonic() + timeout

        def watch():
            while not finished.is_set():
                remaining = deadline - time.monotonic()
                if (cancel_event is not None and cancel_event.is_set()) or remaining <= 0:
                    # Closing the captured session releases Paramiko's exec,
                    # subsystem and SFTP-version waits, which ignore the channel
                    # timeout. Never look up a potentially replacement session.
                    try:
                        if transport is not None:
                            transport.close()
                    except Exception:
                        pass
                    return
                if finished.wait(min(0.05, remaining)):
                    return

        watchdog = threading.Thread(target=watch, name="ssh-handshake-watchdog", daemon=True)
        watchdog.start()
        try:
            yield
        finally:
            finished.set()
            # cancel() alone cannot stop a timer callback that has already
            # started. Wait for retirement before a transfer or on_cancel can
            # start another operation on this connection.
            watchdog.join()

    def run(self, argv: list[str], *, progress: Callable[[str], None] | None = None,
            cancel_event: threading.Event | None = None, timeout: float = 3600,
            on_cancel: Callable[[], None] | None = None,
            timeout_message: str | None = None) -> str:
        """Run an argument vector; no secrets are put into a remote command."""
        def notify_cancelled():
            if on_cancel is not None:
                try:
                    on_cancel()
                except Exception:
                    pass  # The primary cancellation/timeout must always survive.

        if cancel_event is not None and cancel_event.is_set():
            notify_cancelled()
            raise CancelledError("Installation cancelled. Existing games and saves were kept.")
        command = shlex.join([str(arg) for arg in argv])
        started = time.monotonic()
        try:
            with self._handshake_watchdog(min(30, timeout) + self.handshake_grace, cancel_event):
                _, stdout, _ = self.client.exec_command(command, timeout=min(30, timeout))
        except (paramiko.SSHException, OSError, EOFError):
            if cancel_event is not None and cancel_event.is_set():
                notify_cancelled()
                raise CancelledError("Installation cancelled. Existing games and saves were kept.") from None
            raise SSHError("The remote command could not be started. Check the Frame's connection and retry.") from None
        channel = stdout.channel
        self._command_channels.add(channel)
        # Build output is delivered live to the activity callback. Keep only a
        # bounded response tail for the final result/error, rather than storing
        # the entire compilation a second time in memory.
        chunks: deque[bytes] = deque()
        retained_bytes = 0
        pending = bytearray()
        try:
            channel.set_combine_stderr(True)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    notify_cancelled()
                    raise CancelledError("Installation cancelled. Existing games and saves were kept.")
                if time.monotonic() - started > timeout:
                    notify_cancelled()
                    raise RemoteTimeoutError(timeout_message or "The remote step timed out. You can reconnect and retry; existing games and saves were kept.")
                while channel.recv_ready():
                    # These checks live inside the receive loop on purpose: a
                    # device that keeps the channel readable must not make the
                    # cancel button or the step timeout unreachable.
                    if cancel_event is not None and cancel_event.is_set():
                        notify_cancelled()
                        raise CancelledError("Installation cancelled. Existing games and saves were kept.")
                    if time.monotonic() - started > timeout:
                        notify_cancelled()
                        raise RemoteTimeoutError(timeout_message or "The remote step timed out. You can reconnect and retry; existing games and saves were kept.")
                    data = channel.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
                    retained_bytes += len(data)
                    while retained_bytes > 256 * 1024 and chunks:
                        overflow = retained_bytes - 256 * 1024
                        first = chunks.popleft()
                        if len(first) > overflow:
                            chunks.appendleft(first[overflow:])
                            retained_bytes -= overflow
                        else:
                            retained_bytes -= len(first)
                    pending.extend(data)
                    if len(pending) > 1024 * 1024:
                        # Endless newline-free output must not grow host memory
                        # without bound; keep only the most recent tail.
                        del pending[:len(pending) - 64 * 1024]
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending[:] = rest
                        if progress is not None:
                            progress(line.decode("utf-8", "replace"))
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
                time.sleep(0.08)
            if pending and progress is not None:
                progress(pending.decode("utf-8", "replace"))
            result = b"".join(chunks).decode("utf-8", "replace")
            status = channel.recv_exit_status()
            if status:
                # Remote helper emits bounded, user-readable diagnostics. Redact defensively.
                lines = [line for line in result.splitlines()
                         if not line.startswith(("HFI_PROGRESS ", "HFI_LOG ", "HFI_RESULT "))]
                safe = "\n".join(lines)
                marker = safe.find("HFI_ERROR ")
                if marker >= 0:
                    safe = safe[marker + len("HFI_ERROR "):]
                if self.settings.password:
                    safe = safe.replace(self.settings.password, "[redacted]")
                safe = safe.strip()
                if len(safe) > 12000:
                    # Keep the helper's summary as well as the final compiler
                    # diagnostics. A tail-only slice hid "Native build failed"
                    # and made the popup begin in an unrelated object filename.
                    summary = safe.splitlines()[0][:500]
                    separator = "\n... [earlier details omitted]\n"
                    remaining = 12000 - len(summary) - len(separator)
                    safe = summary + separator + safe[-remaining:]
                raise SSHError(safe or f"Remote step failed (exit {status}).")
            return result
        except (paramiko.SSHException, OSError, EOFError):
            if cancel_event is not None and cancel_event.is_set():
                notify_cancelled()
                raise CancelledError("Installation cancelled. Existing games and saves were kept.") from None
            raise SSHError("The remote connection stopped before this step could be verified. Check the Frame's connection and retry.") from None
        finally:
            try:
                channel.close()
            except Exception:
                # Final connection teardown will retry this resource and close
                # its transport. A channel-close error cannot erase the result.
                pass
            else:
                self._command_channels.discard(channel)

    def put(self, local: Path, remote: str, *, callback=None,
            cancel_event: threading.Event | None = None) -> None:
        def update(done: int, total: int):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.")
            if callback:
                callback(done, total)
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Installation cancelled. Existing games and saves were kept.")
        sftp = None
        try:
            with self._handshake_watchdog(self.sftp_timeout + self.handshake_grace, cancel_event):
                sftp = self.client.open_sftp()
            self._sftp_clients.add(sftp)
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.")
            sftp.get_channel().settimeout(self.sftp_timeout)
            sftp.put(str(local), remote, callback=update, confirm=True)
        except (OSError, EOFError, paramiko.SSHException):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.") from None
            raise SSHError("The encrypted file transfer stopped. Check the Frame's connection and retry.") from None
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass  # Connection teardown still owns and retries it.
                else:
                    self._sftp_clients.discard(sftp)
