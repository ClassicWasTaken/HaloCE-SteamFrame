"""Large bundled helpers must survive SSH shell limits without remote temp files."""
import io
import shlex
import sys
import threading
import types

import pytest

from halo_frame_installer.install import Installer, run_remote_source
from halo_frame_installer.ssh import Settings, SSHError
from test_storage_host import RESOURCES, SD_ID, StorageConnection, maps_fixture


class PayloadConnection(StorageConnection):
    def __init__(self, settings, **kwargs):
        super().__init__(settings, **kwargs)
        self.inline_calls = []

    def run(self, argv, **kwargs):
        if argv[1] == "-c":
            payload = kwargs["input_data"]
            assert isinstance(payload, bytes)
            # Check the actual SSH shell command as well as Python's -c argument.
            assert len(shlex.join(argv).encode("utf-8")) < 1024
            assert len(argv[2].encode("utf-8")) < 512
            assert self.settings.password not in shlex.join(argv)
            self.inline_calls.append((argv, payload, kwargs))
        else:
            assert "input_data" not in kwargs
        return super().run(argv, **kwargs)


@pytest.mark.parametrize("operation", ["install", "repair", "library", "uninstall", "storage"])
@pytest.mark.parametrize("storage_id", ["internal", SD_ID])
def test_every_helper_delivery_path_uses_bounded_commands_and_complete_payload(tmp_path, operation, storage_id):
    settings = Settings("frame", "private", storage_id=storage_id,
                        reinstall_existing=operation == "repair")
    connection = PayloadConnection(settings, existing=operation in ("repair", "library"))
    installer = Installer(lambda _: connection, RESOURCES)
    if operation in ("install", "repair"):
        installer.run(settings, maps_fixture(tmp_path) if operation == "install" else None)
    elif operation == "library":
        installer.add_to_steam(settings)
    elif operation == "uninstall":
        installer.uninstall(settings)
    else:
        installer.discover_storage(settings)
    assert connection.closed and connection.inline_calls
    assert all(isinstance(options["cancel_event"], threading.Event)
               and options["timeout"] == 90 for _, _, options in connection.inline_calls)
    if operation == "storage":
        assert connection.inline_calls[0][1] == (RESOURCES / "frame_storage.py").read_text(encoding="utf-8").encode()
        assert not connection.uploads
    else:
        source = installer.remote_source()
        # Reproduce the original per-string Linux failure with today's real resource.
        legacy_command = shlex.join(["python3", "-c", source, "preflight"])
        assert len(legacy_command.encode("utf-8")) >= 131072
        assert connection.inline_calls[0][1] == source.encode("utf-8")
        expected = "preflight-library" if operation == "library" else "preflight-uninstall" if operation == "uninstall" else "preflight"
        assert connection.inline_calls[0][0][3] == expected
        if operation == "repair":
            assert "--repair" in connection.inline_calls[0][0]
        if storage_id != "internal":
            assert len(connection.inline_calls) > 1
            assert all(argv[-2:] == ["--storage-id", SD_ID] for argv, _, _ in connection.inline_calls)
            assert all(b"resolve_storage" in payload for _, payload, _ in connection.inline_calls[1:])


def test_real_bundled_helper_executes_intact_from_stdin_and_keeps_arguments(monkeypatch):
    source = Installer(resource_dir=RESOURCES).remote_source()
    arguments = ["preflight", "--repair", "--adopt-existing", "--storage-id", SD_ID]
    namespace = {"__name__": "remote_source_fixture"}
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "frame_storage", types.ModuleType("prior_storage_fixture"))

    class ExecuteConnection:
        def run(self, argv, **kwargs):
            monkeypatch.setattr(sys, "argv", ["-c", *argv[3:]])
            monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(kwargs["input_data"])))
            exec(compile(argv[2], "<short SSH bootstrap>", "exec"), namespace)
            return "loaded"

    assert run_remote_source(ExecuteConnection(), source, arguments) == "loaded"
    assert sys.argv == ["-c", *arguments]
    assert namespace["SOURCE_COMMIT"] == "2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4"
    assert all(callable(namespace[name]) for name in ("preflight", "preflight_uninstall", "preflight_library", "main"))
    assert callable(namespace["storage_module"]().resolve_storage)
    assert namespace["_hfi_source"] == source.encode("utf-8")


@pytest.mark.parametrize("alteration", ["truncated-valid-python", "different-same-length", "extra-bytes"])
def test_helper_integrity_check_rejects_changed_or_truncated_source_before_execution(monkeypatch, alteration):
    source = "executed=True\n" + "# source padding\n" * 20000
    namespace = {"__name__": "integrity_fixture"}

    class TamperedConnection:
        def run(self, argv, **kwargs):
            payload = kwargs["input_data"]
            if alteration == "truncated-valid-python":
                payload = b"executed=True\n"
            elif alteration == "different-same-length":
                payload = payload.replace(b"executed=True", b"executed=None", 1)
            else:
                payload += b"# excess input\n"
            monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(payload)))
            exec(compile(argv[2], "<short SSH bootstrap>", "exec"), namespace)

    with pytest.raises(SystemExit, match="HFI_ERROR Setup helper transfer was incomplete"):
        run_remote_source(TamperedConnection(), source)
    assert "executed" not in namespace


@pytest.mark.parametrize("operation", ["install", "repair", "uninstall"])
def test_incomplete_preflight_transfer_stops_before_upload_or_mutation(tmp_path, operation):
    settings = Settings("frame", "private", reinstall_existing=operation == "repair")
    connection = PayloadConnection(settings, existing=operation == "repair")

    def broken_transfer(argv, **kwargs):
        assert argv[1] == "-c" and len(kwargs["input_data"]) > 131072
        raise SSHError("Setup helper transfer was incomplete. Reconnect and retry.")

    connection.run = broken_transfer
    installer = Installer(lambda _: connection, RESOURCES)
    with pytest.raises(SSHError, match="transfer was incomplete"):
        if operation == "uninstall":
            installer.uninstall(settings)
        else:
            installer.run(settings, maps_fixture(tmp_path) if operation == "install" else None)
    assert connection.closed and not connection.uploads
