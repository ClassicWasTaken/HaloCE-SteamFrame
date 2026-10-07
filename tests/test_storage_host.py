"""Storage selection must bind every remote step to one verified destination."""
import json
import threading
import contextlib
import io
from pathlib import Path

import pytest

from halo_frame_installer.install import (
    EXPECTED_MAPS, Installer, validate_storage_destination,
)
from halo_frame_installer.ssh import CancelledError, Settings, SSHError

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
SD_ID = "sd:" + "a" * 32
MOUNT = "/run/media/steamos/Halo SD"


def destination(identifier=SD_ID):
    internal = identifier == "internal"
    root = "/home/steamos" if internal else MOUNT
    return {"id": identifier, "kind": "internal" if internal else "sd",
            "label": "Internal storage" if internal else "SD card — Halo SD",
            "mountPath": root, "gamePath": root + "/Games/HaloCENativeVR",
            "cachePath": root + ("/.cache/halo-frame-installer" if internal else "/.halo-frame-installer"),
            "freeBytes": 32 * 1024 ** 3, "installed": False,
            "identity": {"kind": "internal", "root": root} if internal else {
                "kind": "sd", "mountPath": root, "mountId": 42, "device": "179:1",
                "filesystem": "ext4", "rootDevice": 45825, "rootInode": 2,
                "cardIdentity": "b" * 64, "filesystemUuid": "filesystem-123",
                "blockDevice": "/dev/mmcblk0p1"}}


class StorageConnection:
    def __init__(self, settings, *, existing=False):
        self.settings, self.existing = settings, existing
        self.host_fingerprint = "SHA256:public"
        self.commands, self.uploads = [], []
        self.closed = False
        self.failure = None
        self.bad_history = False
        self.live_changes = {}

    def connect(self):
        pass

    def close(self):
        self.closed = True

    def put(self, local, remote, **kwargs):
        self.uploads.append((Path(local).name, remote))

    def run(self, argv, **kwargs):
        self.commands.append(argv)
        selected = destination(self.settings.storage_id)
        if argv[1] == "-c" and len(argv) == 3:
            response = {"home": "/home/steamos", "destinations": [destination("internal"), destination()]}
        elif argv[1] == "-c":
            if argv[3] == "--storage-id":
                selected.update(self.live_changes)
                response = selected
            else:
                response = {"home": "/home/steamos", "storage": selected,
                        "cachePath": selected["cachePath"], "gamePath": selected["gamePath"],
                        "existing": {"gamePath": selected["gamePath"], "reused": True,
                                     "mapsVerified": True} if self.existing else None,
                        "uninstallSupported": True}
        elif argv[2] == "prepare":
            run = argv[argv.index("--run-id") + 1]
            response = {"uploadPath": selected["cachePath"] + "/runs/" + run + "/upload"}
        elif argv[2] == "build":
            if self.failure:
                raise self.failure
            response = {"built": True}
        elif argv[2] == "finalize":
            response = {"gamePath": selected["gamePath"], "repaired": self.existing}
        elif argv[2] == "shortcut":
            response = {"status": "added", "appid": 3000000042}
        elif argv[2] == "cancel":
            response = {"cancelled": True}
        elif argv[2] == "uninstall":
            run = argv[argv.index("--run-id") + 1]
            parent = selected["gamePath"].rsplit("/", 1)[0]
            response = {"gamePath": selected["gamePath"], "uninstalled": True,
                        "steam": {"status": "removed"},
                        "savedBackupPath": parent + "/HaloCENativeVR-saves-" + run,
                        "recoveredSaveBackupPaths": [
                            ("/home/steamos/Games" if self.bad_history else parent)
                            + "/HaloCENativeVR-saves-" + "b" * 32]}
        else:
            raise AssertionError(argv)
        return "HFI_RESULT " + json.dumps(response)


def maps_fixture(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    for name in EXPECTED_MAPS:
        (maps / name).write_bytes(b"synthetic Xbox map")
    return maps


@pytest.mark.parametrize("extra", [
    {"id": "sd:../../other"}, {"kind": "internal"},
    {"mountPath": "/home/steamos"}, {"mountPath": "/run/media/steamos"},
    {"mountPath": "/run/media/steamos/../other"}, {"mountPath": '/run/media/steamos/evil"'},
    {"mountPath": "/run/media/steamos/evil$(command)"},
    {"gamePath": MOUNT + "/Games/other"}, {"cachePath": "/home/steamos/.cache/halo-frame-installer"},
    {"freeBytes": True}, {"installed": "yes"}, {"label": "bad\nlabel"},
])
def test_remote_storage_paths_and_details_fail_closed(extra):
    with pytest.raises(SSHError):
        validate_storage_destination(dict(destination(), **extra), SD_ID)


def test_sd_card_path_accepts_spaces_and_unicode_without_shell_syntax():
    item = destination()
    root = "/run/media/steamos/Halo 卡"
    item.update(mountPath=root, gamePath=root + "/Games/HaloCENativeVR", cachePath=root + "/.halo-frame-installer")
    item["identity"]["mountPath"] = root
    assert validate_storage_destination(item, SD_ID)["mountPath"] == root


def test_discovery_closes_connection_before_returning_verified_choices():
    settings = Settings("frame", "private")
    connection = StorageConnection(settings)
    result = Installer(lambda _: connection, RESOURCES).discover_storage(settings)
    assert connection.closed and not connection.uploads
    assert [item["id"] for item in result.destinations] == ["internal", SD_ID]
    assert result.host_fingerprint == "SHA256:public" and result.cleanup_warning is None


def test_discovery_cleanup_warning_is_redacted_and_not_ignored():
    settings = Settings("frame", "private", transport="usb")
    connection = StorageConnection(settings)
    def close():
        raise SSHError("private USB forward remains")
    connection.close = close
    result = Installer(lambda _: connection, RESOURCES).discover_storage(settings)
    assert result.cleanup_warning and "private" not in result.cleanup_warning
    assert "Unplug the USB cable" in result.cleanup_warning


def test_discovery_preserves_bounded_unavailable_card_diagnostics():
    settings = Settings("frame", "private")
    connection = StorageConnection(settings)
    original = connection.run
    detail = {"mountPath": MOUNT, "reason": "Card is mounted read-only."}
    def run(argv, **kwargs):
        response = json.loads(original(argv, **kwargs).split(" ", 1)[1])
        response["unavailable"] = [detail]
        return "HFI_RESULT " + json.dumps(response)
    connection.run = run
    result = Installer(lambda _: connection, RESOURCES).discover_storage(settings)
    assert result.unavailable == (detail,) and connection.closed


@pytest.mark.parametrize("existing", [False, True])
def test_sd_install_and_repair_bind_all_steps_uploads_and_library_to_card(tmp_path, existing):
    settings = Settings("frame", "private", storage_id=SD_ID, reinstall_existing=existing)
    connection = StorageConnection(settings, existing=existing)
    result = Installer(lambda _: connection, RESOURCES).run(settings, None if existing else maps_fixture(tmp_path))
    assert result.game_path == destination()["gamePath"] and result.storage_id == SD_ID
    assert connection.closed and result.repaired == existing
    assert all(command[-2:] == ["--storage-id", SD_ID] for command in connection.commands)
    assert all(path.startswith(destination()["cachePath"] + "/resources/") or
               path.startswith(destination()["cachePath"] + "/runs/") for _, path in connection.uploads)
    assert sum(path.endswith(".map") for _, path in connection.uploads) == (0 if existing else 24)
    assert any(name == "frame_storage.py" for name, _ in connection.uploads)
    assert any(command[2] == "shortcut" for command in connection.commands if command[1] != "-c")


def test_sd_library_retry_does_not_rebuild_or_upload_maps():
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings, existing=True)
    result = Installer(lambda _: connection, RESOURCES).add_to_steam(settings)
    assert result.storage_id == SD_ID and result.reused and connection.closed
    assert all(command[-2:] == ["--storage-id", SD_ID] for command in connection.commands)
    assert not any(path.endswith(".map") for _, path in connection.uploads)
    assert not any(command[2] in ("build", "prepare") for command in connection.commands if command[1] != "-c")


def test_sd_build_failure_cancels_selected_run_and_does_not_register(tmp_path):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    connection.failure = SSHError("Build failed")
    with pytest.raises(SSHError, match="Build failed"):
        Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    steps = [command[2] for command in connection.commands if command[1] != "-c"]
    assert steps == ["prepare", "build", "cancel"] and connection.closed
    assert connection.commands[-1][-2:] == ["--storage-id", SD_ID]


def test_sd_uninstall_uses_selected_parent_for_backup_and_recovery_history():
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    result = Installer(lambda _: connection, RESOURCES).uninstall(settings)
    assert result.storage_id == SD_ID and result.uninstalled and connection.closed
    assert result.saved_backup_path.startswith(MOUNT + "/Games/HaloCENativeVR-saves-")
    assert result.recovered_save_backup_paths == (MOUNT + "/Games/HaloCENativeVR-saves-" + "b" * 32,)
    assert all("--storage-id" in command for command in connection.commands)


def test_sd_uninstall_rejects_history_from_internal_storage():
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    connection.bad_history = True
    with pytest.raises(SSHError, match="invalid uninstall recovery"):
        Installer(lambda _: connection, RESOURCES).uninstall(settings)
    assert connection.closed


def test_storage_settings_reject_arbitrary_target_paths():
    with pytest.raises(ValueError, match="detected SD"):
        Settings("frame", "private", storage_id="/run/media/steamos/card")


def test_discovery_cancel_before_connect_is_noop():
    settings = Settings("frame", "private")
    connection = StorageConnection(settings)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CancelledError):
        Installer(lambda _: connection, RESOURCES).discover_storage(settings, cancel)
    assert connection.closed and not connection.commands


@pytest.mark.parametrize("field,value", [
    ("kind", "internal"), ("mountPath", "/run/media/steamos/other"),
    ("mountId", True), ("device", "bad"), ("filesystem", "vfat"),
    ("rootDevice", 0), ("rootInode", -1), ("cardIdentity", "missing"),
    ("filesystemUuid", "bad/uuid"), ("blockDevice", "/dev/sda1"),
])
def test_sd_identity_fields_fail_closed(field, value):
    item = destination()
    item["identity"][field] = value
    with pytest.raises(SSHError, match="invalid SD card identity"):
        validate_storage_destination(item, SD_ID)


@pytest.mark.parametrize("field", [
    "kind", "mountPath", "mountId", "device", "filesystem", "rootDevice",
    "rootInode", "cardIdentity", "filesystemUuid",
])
def test_sd_identity_missing_fields_fail_closed(field):
    item = destination()
    del item["identity"][field]
    with pytest.raises(SSHError, match="invalid SD card identity"):
        validate_storage_destination(item, SD_ID)


def storage_checks(connection):
    return [command for command in connection.commands
            if command[1] == "-c" and len(command) > 3 and command[3] == "--storage-id"]


def remote_steps(connection):
    return [command[2] for command in connection.commands if command[1] != "-c"]


def test_sd_each_put_has_independent_bundled_before_and_after_checks(tmp_path):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    checks = storage_checks(connection)
    assert len(checks) == len(connection.uploads) * 2
    assert all(command[-2:] == ["--storage-id", SD_ID] for command in checks)
    assert all("types.ModuleType" in command[2] and "resolve_storage(sys.argv[-1])" in command[2]
               and "def _sd_identity(" in command[2] for command in checks)
    assert all("synthetic Xbox map" not in command[2] and "xbox-data-manifest" not in command[2]
               for command in checks)


@pytest.mark.parametrize("field,value", [
    ("mountId", 43), ("device", "179:2"), ("rootDevice", 45826),
    ("rootInode", 3), ("cardIdentity", "c" * 64),
    ("filesystemUuid", "new-filesystem"), ("filesystem", "f2fs"),
    ("blockDevice", "/dev/mmcblk0p2"),
])
def test_card_identity_changed_between_puts_stops_before_next_write(tmp_path, field, value):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    original = connection.put
    def put(local, remote, **kwargs):
        original(local, remote, **kwargs)
        if Path(local).name == "frame_storage.py":
            # The first upload's post-check still sees the original card.
            # Its next call models the card being swapped between files.
            original_run = connection.run
            def run(argv, **options):
                response = original_run(argv, **options)
                if argv[1] == "-c" and argv[3] == "--storage-id":
                    identity = dict(destination()["identity"], **{field: value})
                    connection.live_changes = {"identity": identity}
                    connection.run = original_run
                return response
            connection.run = run
    connection.put = put
    with pytest.raises(SSHError, match="SD card changed during transfer"):
        Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    assert connection.closed and len(connection.uploads) == 1
    assert not remote_steps(connection)


def test_card_swapped_during_large_map_is_checked_before_upload_continues(tmp_path, monkeypatch):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    original = connection.put
    clock = [0.0]
    monkeypatch.setattr("halo_frame_installer.install.time.monotonic", lambda: clock[0])
    callbacks = []
    def put(local, remote, **kwargs):
        original(local, remote, **kwargs)
        if Path(local).suffix == ".map":
            callback = kwargs["callback"]
            clock[0] = 0.5; callback(1, 8); callbacks.append(1)
            connection.live_changes = {"identity": dict(destination()["identity"], mountId=99)}
            clock[0] = 1.1; callback(2, 8)
            callbacks.append(2)  # Must never reach the next SFTP write callback.
    connection.put = put
    activity = []
    with pytest.raises(SSHError, match="SD card changed during transfer"):
        Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path),
                                                       lambda *update: activity.append(update))
    assert callbacks == [1] and connection.closed
    assert sum(name.endswith(".map") for name, _ in connection.uploads) == 1
    assert remote_steps(connection) == ["prepare", "cancel"]
    assert any("cancellation confirmed" in message for _, message, _ in activity)


def test_sd_post_upload_guard_stops_swapped_card_before_build(tmp_path):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    original = connection.put
    def put(local, remote, **kwargs):
        original(local, remote, **kwargs)
        if Path(local).suffix == ".map":
            connection.live_changes = {"identity": dict(destination()["identity"], rootInode=99)}
    connection.put = put
    with pytest.raises(SSHError, match="SD card changed during transfer"):
        Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    assert remote_steps(connection) == ["prepare", "cancel"] and connection.closed


def test_sd_guard_ignores_changing_free_space_and_install_metadata(tmp_path):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    connection.live_changes = {"freeBytes": 1, "installed": True, "label": "Halo SD renamed"}
    result = Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    assert result.storage_id == SD_ID and connection.closed and "shortcut" in remote_steps(connection)


def test_sd_uninstall_upload_guard_prevents_removal_on_changed_card():
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    connection.live_changes = {"identity": dict(destination()["identity"], mountId=99)}
    with pytest.raises(SSHError, match="SD card changed during transfer"):
        Installer(lambda _: connection, RESOURCES).uninstall(settings)
    assert not connection.uploads and not remote_steps(connection) and connection.closed


def test_sd_callback_cancel_stops_run_and_closes_connection(tmp_path):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    original = connection.put
    cancel = threading.Event()
    def put(local, remote, **kwargs):
        original(local, remote, **kwargs)
        if Path(local).suffix == ".map":
            cancel.set()
            kwargs["callback"](1, 8)
    connection.put = put
    with pytest.raises(CancelledError):
        Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path), cancel_event=cancel)
    assert remote_steps(connection) == ["prepare", "cancel"] and connection.closed


def test_internal_uploads_keep_original_transfer_behavior_without_sd_checks(tmp_path):
    settings = Settings("frame", "private")
    connection = StorageConnection(settings)
    result = Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    assert result.storage_id == "internal" and not storage_checks(connection) and connection.closed


def test_sd_preflight_requires_complete_identity_before_any_write(tmp_path):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    original = connection.run
    def run(argv, **kwargs):
        value = json.loads(original(argv, **kwargs).split(" ", 1)[1])
        if argv[1] == "-c" and argv[3] == "preflight":
            del value["storage"]["identity"]
        return "HFI_RESULT " + json.dumps(value)
    connection.run = run
    with pytest.raises(SSHError, match="invalid SD card identity"):
        Installer(lambda _: connection, RESOURCES).run(settings, maps_fixture(tmp_path))
    assert not connection.uploads and not remote_steps(connection) and connection.closed


def test_sd_guard_requires_original_fixed_paths_even_with_same_selected_id():
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings, existing=True)
    mount = "/run/media/steamos/Card moved"
    connection.live_changes = {"mountPath": mount, "gamePath": mount + "/Games/HaloCENativeVR",
                               "cachePath": mount + "/.halo-frame-installer",
                               "identity": dict(destination()["identity"], mountPath=mount)}
    with pytest.raises(SSHError, match="SD card changed during transfer"):
        Installer(lambda _: connection, RESOURCES).add_to_steam(settings)
    assert not connection.uploads and not remote_steps(connection) and connection.closed


def test_sd_periodic_guard_throttles_checks_and_preserves_progress(tmp_path, monkeypatch):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    clock = [0.0]
    monkeypatch.setattr("halo_frame_installer.install.time.monotonic", lambda: clock[0])
    progress = []
    def put(local, remote, **kwargs):
        for done, moment in enumerate((0.2, 0.4, 1.1, 1.3, 2.2), 1):
            clock[0] = moment
            kwargs["callback"](done, 5)
    connection.put = put
    upload = Installer(resource_dir=RESOURCES).guarded_upload(connection, settings, destination(), threading.Event())
    upload(tmp_path / "example.map", MOUNT + "/.halo-frame-installer/example.map",
           callback=lambda done, total: progress.append((done, total)))
    assert progress == [(done, 5) for done in range(1, 6)]
    assert len(storage_checks(connection)) == 4  # before, two elapsed seconds, after


def test_missing_card_inline_check_emits_bounded_error_without_traceback(tmp_path, monkeypatch):
    settings = Settings("frame", "private", storage_id=SD_ID)
    connection = StorageConnection(settings)
    (tmp_path / "frame_storage.py").write_text(
        "def resolve_storage(selected):\n    raise ValueError('card missing\\n' + 'x' * 1000)\n")
    messages = []
    def run(argv, **kwargs):
        output = io.StringIO()
        monkeypatch.setattr("sys.argv", ["-c", *argv[3:]])
        with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as stopped:
            exec(compile(argv[2], "<inline SD check>", "exec"), {})
        assert stopped.value.code == 1
        messages.append(output.getvalue())
        raise SSHError(output.getvalue())
    connection.run = run
    upload = Installer(resource_dir=tmp_path).guarded_upload(connection, settings, destination(), threading.Event())
    with pytest.raises(SSHError, match="HFI_ERROR card missing"):
        upload(tmp_path / "file", MOUNT + "/.halo-frame-installer/file")
    assert not connection.uploads and len(messages) == 1
    assert len(messages[0]) <= len("HFI_ERROR ") + 600 + 1
    assert messages[0].count("\n") == 1 and "Traceback" not in messages[0]
