import importlib.util
import json
import sys
import struct
import threading
import types
from collections import OrderedDict
from pathlib import Path
from unittest.mock import Mock

import pytest

from halo_frame_installer.install import EXPECTED_MAPS, Installer, SOURCE_COMMIT, close_connection, map_manifest, parse_result
from halo_frame_installer.ssh import CancelledError, RemoteTimeoutError, Settings, SSHError

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def load_resource(name):
    spec = importlib.util.spec_from_file_location("resource_" + name, RESOURCES / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_shortcut_roundtrip_preserves_foreign_entry_and_is_idempotent():
    steam = load_resource("steam_shortcut")
    other = OrderedDict([("appid", steam.Value(2, 2147483650)), ("AppName", steam.Value(1, "Other game")),
                         ("Exe", steam.Value(1, '"/somewhere/game"')), ("custom", steam.Value(7, b"12345678"))])
    root = OrderedDict([("shortcuts", steam.Value(0, OrderedDict([("0", steam.Value(0, other))])))])
    before = steam.dumps(root)
    first, appid = steam.update_shortcut(before, "/home/steamos/Games/HaloCENativeVR/halo", "/home/steamos/Games/HaloCENativeVR")
    after = steam.loads(first)["shortcuts"].value
    assert after["0"].value == other
    assert len(after) == 2
    assert after["1"].value["OpenVR"].value == 1
    assert after["1"].value["LaunchOptions"].value == "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%"
    assert steam.update_shortcut(first, "/home/steamos/Games/HaloCENativeVR/halo", "/home/steamos/Games/HaloCENativeVR") == (first, appid)


def test_shortcut_update_preserves_user_library_choices():
    steam = load_resource("steam_shortcut")
    executable = "/home/steamos/Games/HaloCENativeVR/halo"
    directory = "/home/steamos/Games/HaloCENativeVR"
    first, appid = steam.update_shortcut(None, executable, directory)
    root = steam.loads(first)
    fields = next(iter(root["shortcuts"].value.values())).value
    for key, value in {"IsHidden": 1, "AllowDesktopConfig": 0, "AllowOverlay": 0,
                       "OpenVR": 0, "Devkit": 1, "DevkitOverrideAppID": 480}.items():
        fields[key] = steam.Value(2, value)
    fields["LaunchOptions"] = steam.Value(1, "user-modified --mods")
    updated, same = steam.update_shortcut(steam.dumps(root), executable, directory)
    after = next(iter(steam.loads(updated)["shortcuts"].value.values())).value
    assert after["IsHidden"].value == 1 and after["AllowDesktopConfig"].value == 0
    assert after["AllowOverlay"].value == 0
    assert after["Devkit"].value == 1 and after["DevkitOverrideAppID"].value == 480
    assert after["OpenVR"].value == 1  # required for the VR library; still managed
    assert after["LaunchOptions"].value == steam.LAUNCH_OPTIONS  # identity fields still refreshed
    assert after["Exe"].value == f'"{executable}"'
    assert same == appid


def test_shortcut_update_keeps_case_variant_choices_and_repairs_damaged_flags():
    steam = load_resource("steam_shortcut")
    executable = "/home/steamos/Games/HaloCENativeVR/halo"
    directory = "/home/steamos/Games/HaloCENativeVR"
    first, _ = steam.update_shortcut(None, executable, directory)
    root = steam.loads(first)
    fields = next(iter(root["shortcuts"].value.values())).value
    del fields["IsHidden"], fields["Devkit"]
    fields["ishidden"] = steam.Value(2, 1)        # old-format casing keeps the choice
    fields["Devkit"] = steam.Value(1, "damaged")  # wrong value kind cannot be a choice
    updated, _ = steam.update_shortcut(steam.dumps(root), executable, directory)
    after = next(iter(steam.loads(updated)["shortcuts"].value.values())).value
    assert after["ishidden"].value == 1 and "IsHidden" not in after
    assert after["Devkit"].kind == 2 and after["Devkit"].value == 0


def test_shortcut_rejects_unknown_types_or_duplicate_fields():
    steam = load_resource("steam_shortcut")
    with pytest.raises(ValueError, match="Unsupported"):
        steam.loads(b"\x09unknown\0\x08")
    with pytest.raises(ValueError, match="duplicate"):
        steam.loads(b"\x01a\0b\0\x01a\0c\0\x08")


def test_shortcut_wont_change_live_steam_files(tmp_path, monkeypatch):
    steam = load_resource("steam_shortcut")
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    result = steam.add_native_shortcut(tmp_path, tmp_path / "game")
    assert result["status"] == "manual"
    assert list(tmp_path.iterdir()) == []


def test_forced_proton_mapping_reports_manual_step_without_rewriting_config(tmp_path):
    steam = load_resource("steam_shortcut")
    config = tmp_path / "config/config.vdf"
    config.parent.mkdir()
    before = '"InstallConfigStore" { "Software" { "Valve" { "Steam" { "CompatToolMapping" { "123" { "name" "proton_9" } "456" { "name" "" } } } } } }'
    config.write_text(before)
    warning = steam._compatibility_warning(tmp_path, 123)
    assert "proton_9" in warning and "turn off" in warning
    assert steam._compatibility_warning(tmp_path, 456) is None
    assert config.read_text() == before


def test_legacy_shutdown_request_leaves_running_steam_and_games_untouched(tmp_path, monkeypatch):
    import subprocess
    steam = load_resource("steam_shortcut")
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    shutdown, restart = Mock(), Mock()
    monkeypatch.setattr(subprocess, "run", shutdown)
    monkeypatch.setattr(subprocess, "Popen", restart)
    result = steam.add_native_shortcut(tmp_path, tmp_path / "game", close_steam=True)
    assert result["status"] == "manual"
    shutdown.assert_not_called()
    restart.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_closed_steam_registration_does_not_start_a_new_client(tmp_path, monkeypatch):
    import subprocess
    steam = load_resource("steam_shortcut")
    monkeypatch.setattr(steam, "steam_running", lambda: False)
    monkeypatch.setattr(steam, "_write_native_shortcut", lambda home, game: {"status": "added", "appid": 42})
    normal_shutdown = Mock()
    restart = Mock()
    monkeypatch.setattr(subprocess, "run", normal_shutdown)
    monkeypatch.setattr(subprocess, "Popen", restart)
    assert steam.add_native_shortcut(tmp_path, tmp_path / "game", close_steam=True)["status"] == "added"
    normal_shutdown.assert_not_called()
    restart.assert_not_called()


def test_original_maps_manifest_never_includes_iso_or_symlinks(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    for name in EXPECTED_MAPS:
        (maps / name).write_bytes(name.encode())
    root, manifest = map_manifest(tmp_path)
    assert root == maps and len(manifest["files"]) == 24
    assert all(file["path"].startswith("maps/") for file in manifest["files"])
    (maps / "game.iso").write_bytes(b"private")
    with pytest.raises(ValueError, match="24 original Xbox"):
        map_manifest(tmp_path)


class FakeConnection:
    def __init__(self, settings, *, existing=True):
        self.settings = settings
        self.existing = existing
        self.commands = []
        self.uploads = []
        self.closed = False
        self.host_fingerprint = "SHA256:public"
    def connect(self):
        pass
    def close(self):
        self.closed = True
    def put(self, local, remote, **kwargs):
        self.uploads.append((str(local), remote))
    def run(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[1] == "-c":
            return "HFI_RESULT " + json.dumps({"home": "/home/steamos", "cachePath": "/home/steamos/.cache/halo-frame-installer",
                "gamePath": "/home/steamos/Games/HaloCENativeVR", "existing": {"gamePath": "/home/steamos/Games/HaloCENativeVR", "reused": True, "mapsVerified": True} if self.existing else None})
        if argv[2] == "shortcut":
            return 'HFI_RESULT {"status":"added","appid":3732925724}'
        if argv[2] == "prepare":
            return "HFI_RESULT " + json.dumps({"uploadPath": "/home/steamos/.cache/halo-frame-installer/runs/" + argv[argv.index("--run-id") + 1] + "/upload"})
        if argv[2] == "build":
            raise SSHError("Native build failed. The existing game was kept.")
        raise AssertionError(argv)


def test_add_to_steam_retry_reuses_files_without_build_or_map_upload():
    fake = FakeConnection(Settings("frame", "private", close_steam_for_shortcut=True))
    result = Installer(lambda settings: fake, RESOURCES).add_to_steam(fake.settings)
    assert result.reused and result.steam_appid == 3732925724
    assert fake.closed
    assert all(not remote.endswith(".map") for _, remote in fake.uploads)
    assert any(remote.endswith("/artwork/halo-ce-cover.jpg") for _, remote in fake.uploads)
    assert any(remote.endswith("/artwork/halo-ce-landscape.png") for _, remote in fake.uploads)
    assert not any("build" in command[2:] for command in fake.commands)
    assert not any("--close-steam" in command for command in fake.commands)
    assert fake.commands[0][-1] == 'preflight-library'
    for name in ('halo-ce-hero.jpg', 'halo-ce-logo.png', 'halo-ce-icon.png', 'steam_notes.py'):
        assert any(remote.endswith('/' + name) for _, remote in fake.uploads)
    assert not any(Path(local).name in ('build-native.sh', 'frame-controls.patch') for local, _ in fake.uploads)


def test_library_update_requires_existing_game_and_cannot_start_build():
    fake = FakeConnection(Settings('frame', 'private'), existing=False)
    with pytest.raises(SSHError, match='before updating'):
        Installer(lambda settings: fake, RESOURCES).add_to_steam(fake.settings)
    assert fake.closed and not fake.uploads
    assert len(fake.commands) == 1 and fake.commands[0][-1] == 'preflight-library'


def test_setup_reports_success_only_after_ssh_disconnects():
    fake = FakeConnection(Settings('frame', 'private', reinstall_existing=False))
    seen = []
    def report(stage, message, percent=None):
        seen.append(stage)
        if stage in ('disconnected', 'complete'):
            assert fake.closed
        elif stage == 'disconnect':
            assert not fake.closed
    Installer(lambda settings: fake, RESOURCES).run(fake.settings, None, report)
    assert seen[-3:] == ['disconnect', 'disconnected', 'complete']


@pytest.mark.parametrize("mode", ["fresh", "repair"])
def test_normal_install_and_repair_automatically_publish_steam_information(tmp_path, mode):
    steam_info = {"status": "added", "appid": 3732925724, "libraryAdded": True,
                  "artwork": {"status": "added", "installed": ["cover", "header", "hero", "logo"],
                              "icon": {"status": "added"}},
                  "notes": {"ok": True, "status": "added", "title": "About and controls"}}

    class SuccessfulConnection(FakeConnection):
        def __init__(self, settings):
            super().__init__(settings, existing=mode == "repair")
            self.events = []

        def put(self, local, remote, **kwargs):
            self.events.append(("upload", Path(local).name))
            super().put(local, remote, **kwargs)

        def run(self, argv, **kwargs):
            if argv[1] != "-c" and argv[2] in ("build", "finalize", "shortcut"):
                self.commands.append(argv)
                self.events.append(("step", argv[2]))
                responses = {"build": {"built": True},
                             "finalize": {"gamePath": "/home/steamos/Games/HaloCENativeVR",
                                          "reused": False, "repaired": mode == "repair"},
                             "shortcut": steam_info}
                return "HFI_RESULT " + json.dumps(responses[argv[2]])
            return super().run(argv, **kwargs)

    settings = Settings("frame", "private", reinstall_existing=mode == "repair",
                        close_steam_for_shortcut=True)
    fake = SuccessfulConnection(settings)
    maps = None
    if mode == "fresh":
        maps = tmp_path / "maps"
        maps.mkdir()
        for name in EXPECTED_MAPS:
            (maps / name).write_bytes(name.encode())
    result = Installer(lambda _: fake, RESOURCES).run(settings, maps)

    steps = [argv[2] for argv in fake.commands if argv[1] != "-c"]
    assert steps == ["prepare", "build", "finalize", "shortcut"]
    assert fake.commands[0][3] == "preflight"
    assert steps.count("shortcut") == 1
    assert fake.events.index(("step", "finalize")) < fake.events.index(("step", "shortcut"))
    for filename in ("steam_notes.py", "halo-ce-cover.jpg", "halo-ce-landscape.png",
                     "halo-ce-hero.jpg", "halo-ce-logo.png", "halo-ce-icon.png"):
        assert fake.events.index(("upload", filename)) < fake.events.index(("step", "build"))
    assert result.steam == steam_info
    assert result.repaired is (mode == "repair")
    assert fake.closed
    assert not any("--close-steam" in argv for argv in fake.commands)
    uploaded_maps = [remote for _, remote in fake.uploads if remote.endswith(".map")]
    assert len(uploaded_maps) == (len(EXPECTED_MAPS) if mode == "fresh" else 0)


def test_default_existing_install_rebuilds_without_uploading_maps():
    fake = FakeConnection(Settings("frame", "private"))
    with pytest.raises(SSHError, match="build failed"):
        Installer(lambda settings: fake, RESOURCES).run(fake.settings, None)
    assert any("--use-existing-maps" in command for command in fake.commands)
    assert any(command[2] == "build" and "--repair" in command for command in fake.commands if command[1] != "-c")
    assert all(not remote.endswith(".map") for _, remote in fake.uploads)


def test_failed_build_does_not_finalize_or_modify_game(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    for name in EXPECTED_MAPS:
        (maps / name).write_bytes(name.encode())
    fake = FakeConnection(Settings("frame", "private"), existing=False)
    with pytest.raises(SSHError, match="build failed"):
        Installer(lambda settings: fake, RESOURCES).run(fake.settings, maps)
    assert not any(command[2] in ("finalize", "shortcut") for command in fake.commands if len(command) > 2 and command[1] != "-c")
    assert fake.closed


def test_step_failure_is_not_replaced_by_a_failed_disconnect():
    class ForwardCleanupFailure(FakeConnection):
        def close(self):
            raise SSHError("USB forward cleanup failed")

    fake = ForwardCleanupFailure(Settings("frame", "private"))
    with pytest.raises(SSHError, match="build failed"):
        Installer(lambda settings: fake, RESOURCES).run(fake.settings, None)


def test_cancelled_install_is_not_replaced_by_a_failed_disconnect():
    class ForwardCleanupFailure(FakeConnection):
        def close(self):
            raise SSHError("USB forward cleanup failed")

    event = threading.Event()
    event.set()
    fake = ForwardCleanupFailure(Settings("frame", "private"))
    with pytest.raises(CancelledError):
        Installer(lambda settings: fake, RESOURCES).run(fake.settings, None, cancel_event=event)


def test_close_connection_reports_a_swallowed_cleanup_failure():
    class FailingClose:
        settings = Settings('', 'private', transport='usb')
        def close(self):
            raise SSHError("SSH has closed, but the temporary USB forward could not be removed.")

    seen = []
    warning = close_connection(FailingClose(), lambda *args: seen.append(args))
    assert warning.startswith('SSH has closed, but the temporary USB forward could not be removed.')
    assert 'Unplug the USB cable' in warning
    assert seen == [('detail', warning, None)]


def test_successful_install_with_failed_cleanup_retains_result_and_needs_attention():
    class ForwardCleanupFailure(FakeConnection):
        def close(self):
            self.closed = True
            raise SSHError('USB forward cleanup failed private')
    fake = ForwardCleanupFailure(Settings('', 'private', transport='usb', reinstall_existing=False))
    events = []
    result = Installer(lambda settings: fake, RESOURCES).run(fake.settings, None,
        lambda *event: events.append(event))
    assert result.steam_appid == 3732925724 and result.reused
    assert result.connection_cleanup_pending and 'Unplug the USB cable' in result.cleanup_warning
    assert 'private' not in result.cleanup_warning
    assert 'disconnected' not in [event[0] for event in events]
    assert 'complete' not in [event[0] for event in events]
    assert events[-1][0] == 'cleanup-pending' and events[-1][2] == 99


@pytest.mark.parametrize('primary_error', [CancelledError, RemoteTimeoutError, SSHError])
@pytest.mark.parametrize('original_active', [False, True])
def test_failed_remote_stop_uses_one_pinned_fresh_connection(primary_error, original_active):
    class BrokenConnection(FakeConnection):
        def is_active(self):
            return original_active
        def run(self, argv, **kwargs):
            if argv[1] != '-c' and argv[2] == 'build':
                self.commands.append(argv)
                if primary_error is not SSHError:
                    kwargs['on_cancel']()
                messages = {CancelledError: 'Installation cancelled.',
                            RemoteTimeoutError: 'The remote step timed out.',
                            SSHError: 'The remote connection stopped before this step could be verified.'}
                raise primary_error(messages[primary_error])
            if argv[1] != '-c' and argv[2] == 'cancel':
                self.commands.append(argv)
                raise SSHError('Connection stopped')
            return super().run(argv, **kwargs)
    class RecoveryConnection(FakeConnection):
        def connect(self, *, timeout):
            self.connect_timeout = timeout
        def run(self, argv, **kwargs):
            self.commands.append(argv)
            assert kwargs['timeout'] == 45 and 'cancel_event' not in kwargs
            return 'HFI_RESULT {"cancelled":true}'
    settings = Settings('frame', 'private', accept_host_key=Mock(side_effect=AssertionError('No new approval')))
    original = BrokenConnection(settings)
    created = []
    def factory(current):
        if not created:
            created.append(original)
            return original
        recovery = RecoveryConnection(current)
        created.append(recovery)
        return recovery
    events = []
    with pytest.raises(primary_error) as error:
        Installer(factory, RESOURCES).run(settings, None, lambda *event: events.append(event))
    assert len(created) == 2
    recovery = created[1]
    build = next(command for command in original.commands if command[1] != '-c' and command[2] == 'build')
    expected_id = build[build.index('--run-id') + 1]
    assert recovery.commands == [['python3', '/home/steamos/.cache/halo-frame-installer/resources/remote_install.py', 'cancel', '--run-id', expected_id]]
    assert recovery.connect_timeout == 10
    assert recovery.settings.known_host_fingerprint == 'SHA256:public'
    assert recovery.settings.accept_host_key is None and recovery.settings.known_host_fingerprints == {}
    assert recovery.settings.password == '' and settings.password == 'private'
    assert original.closed and recovery.closed
    assert 'could not be confirmed' not in str(error.value)
    assert not any(command[2] in ('finalize', 'shortcut') for command in original.commands if command[1] != '-c')
    assert any(event[1] == 'Remote build cancellation confirmed.' for event in events)


@pytest.mark.parametrize('failure', ['unapproved', 'changed-key', 'unconfirmed-response'])
def test_unconfirmed_remote_stop_is_visible_without_masking_cancel(failure):
    class BrokenConnection(FakeConnection):
        def is_active(self):
            return False
        def run(self, argv, **kwargs):
            if argv[1] != '-c' and argv[2] == 'build':
                self.commands.append(argv)
                raise CancelledError('Installation cancelled. Existing games and saves were kept.')
            return super().run(argv, **kwargs)
    settings = Settings('frame', 'private')
    original = BrokenConnection(settings)
    if failure == 'unapproved':
        original.host_fingerprint = None
    created = []
    def factory(current):
        if not created:
            created.append(original)
            return original
        recovery = FakeConnection(current)
        recovery.connect = Mock(side_effect=SSHError('SSH host key has changed.')) if failure == 'changed-key' else Mock()
        recovery.run = Mock(return_value='HFI_RESULT {"cancelled":"true"}')
        created.append(recovery)
        return recovery
    with pytest.raises(CancelledError) as error:
        Installer(factory, RESOURCES).run(settings, None)
    first_line = str(error.value).splitlines()[0]
    assert 'cancelled' in first_line and 'Remote stopping could not be confirmed' in first_line
    assert 'In the Frame\'s terminal, run: python3 /home/steamos/.cache/' in str(error.value)
    assert 'private' not in str(error.value) and original.closed
    assert len(created) == (1 if failure == 'unapproved' else 2)
    if len(created) == 2:
        assert created[1].closed and created[1].settings.password == ''


def test_cleanup_display_failure_cannot_replace_the_primary_error():
    fake = FakeConnection(Settings('frame', 'private'))
    fake.close = Mock(side_effect=EOFError('private'))
    def progress(stage, message, percent=None):
        if stage == 'detail':
            raise ValueError('Display failed')
    with pytest.raises(SSHError, match='build failed') as error:
        Installer(lambda settings: fake, RESOURCES).run(fake.settings, None, progress)
    assert 'private' not in str(error.value)


def test_cancelled_before_connect_has_no_remote_mutation():
    event = threading.Event()
    event.set()
    fake = FakeConnection(Settings("frame", "private"))
    with pytest.raises(CancelledError):
        Installer(lambda settings: fake, RESOURCES).run(fake.settings, None, cancel_event=event)
    assert not fake.commands and not fake.uploads


def test_installer_delivers_live_phase_counts_and_detail_lines_before_build_returns():
    delivered = []

    class ActivityConnection(FakeConnection):
        def run(self, argv, **kwargs):
            if argv[1] != '-c' and argv[2] == 'build':
                self.commands.append(argv)
                report = kwargs['progress']
                report('HFI_PROGRESS {"stage":"toolchain","message":"Installing LLVM 22"}')
                report('HFI_LOG {"stage":"toolchain","message":"Unpacking clang-22"}')
                report('HFI_PROGRESS {"stage":"compile","message":"Compiled 42 of 100 tasks","percent":42}')
                assert ('compile', 'Compiled 42 of 100 tasks', 42) in delivered
                assert ('detail', 'toolchain: Unpacking clang-22', None) in delivered
                return 'HFI_RESULT {"built":true}'
            if argv[1] != '-c' and argv[2] == 'finalize':
                self.commands.append(argv)
                return 'HFI_RESULT {"gamePath":"/home/steamos/Games/HaloCENativeVR","repaired":true}'
            return super().run(argv, **kwargs)

    fake = ActivityConnection(Settings('frame', 'private'))
    result = Installer(lambda settings: fake, RESOURCES).run(fake.settings, None,
        lambda stage, message, percent=None: delivered.append((stage, message, percent)))
    assert result.repaired and fake.closed
    assert delivered[-1][0] == 'complete'


def test_result_protocol_requires_one_result():
    with pytest.raises(SSHError):
        parse_result("random text")
    with pytest.raises(SSHError):
        parse_result('HFI_RESULT {}\nHFI_RESULT {}')


@pytest.fixture
def remote(tmp_path, monkeypatch):
    if "pwd" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: None))
    module = load_resource("remote_install")
    home = tmp_path / "home"
    home.mkdir()
    module.HOME = home
    module.CACHE = home / "cache"
    module.GAME = home / "Games/HaloCENativeVR"
    monkeypatch.setattr(module.os, "getuid", lambda: home.stat().st_uid, raising=False)
    monkeypatch.setattr(module, "game_closed", lambda: None)
    return module


def xbox_maps(directory, remote):
    (directory / "maps").mkdir(parents=True)
    header = bytearray(2048)
    header[:4] = b"daeh"
    header[-4:] = b"toof"
    struct.pack_into("<II", header, 4, 5, 2048)
    header[64:64 + 13] = b"01.10.12.2276"
    files = []
    for relative in sorted(remote.EXPECTED_MAPS):
        target = directory / relative
        target.write_bytes(header)
        files.append({"path": relative, "size": len(header), "sha256": remote.digest(target)})
    return {"files": files, "totalBytes": len(header) * len(files)}


def test_library_preflight_does_not_require_compiler_or_build_space(remote, monkeypatch):
    owner_uid = remote.HOME.stat().st_uid
    monkeypatch.setattr(remote.os, 'getuid', lambda: owner_uid, raising=False)
    monkeypatch.setattr(remote.pwd, 'getpwuid', lambda uid: types.SimpleNamespace(pw_name='steamos'))
    monkeypatch.setattr(remote.pathlib.Path, 'home', lambda: remote.HOME)
    monkeypatch.setattr(remote.platform, 'machine', lambda: 'aarch64')
    monkeypatch.setattr(remote, 'os_release', lambda: {'ID': 'steamos'})
    build_tools = Mock(side_effect=AssertionError('Library info must not require build tools'))
    monkeypatch.setattr(remote.shutil, 'which', build_tools)
    monkeypatch.setattr(remote.shutil, 'disk_usage', build_tools)
    monkeypatch.setattr(remote, 'command', build_tools)
    verified = {'gamePath': str(remote.GAME), 'mapsVerified': True, 'sourceCommit': SOURCE_COMMIT}
    monkeypatch.setattr(remote, 'existing_install', lambda: verified)
    result = remote.preflight_library()
    assert result['existing'] == verified and 'uninstallSupported' not in result
    assert result['cachePath'] == str(remote.CACHE)
    build_tools.assert_not_called()


def test_library_preflight_requires_verified_game(remote, monkeypatch):
    monkeypatch.setattr(remote, 'preflight_uninstall', lambda: {'home': str(remote.HOME)})
    monkeypatch.setattr(remote, 'existing_install', lambda: None)
    with pytest.raises(ValueError, match='before updating'):
        remote.preflight_library()


@pytest.mark.parametrize('shortcut_status', ['added', 'manual'])
def test_remote_notes_enrichment_is_independent_of_verified_shortcut_status(remote, monkeypatch, shortcut_status):
    monkeypatch.setattr(remote, 'existing_install', lambda: {'mapsVerified': True})
    monkeypatch.setattr(sys, 'path', list(sys.path))
    register = Mock(return_value={'status': shortcut_status, 'appid': 3000000001})
    notes = Mock(return_value={'status': 'manual', 'content': 'Description to copy'})
    monkeypatch.setitem(sys.modules, 'steam_shortcut', types.SimpleNamespace(add_native_shortcut=register))
    monkeypatch.setitem(sys.modules, 'steam_notes', types.SimpleNamespace(add_notes=notes))
    result = remote.shortcut()
    assert result['status'] == shortcut_status
    register.assert_called_once_with(remote.HOME, remote.GAME, close_steam=False)
    if shortcut_status == 'added':
        notes.assert_called_once_with(remote.HOME, remote.GAME, 3000000001)
        assert result['notes']['status'] == 'manual'
    else:
        notes.assert_not_called()
        assert 'notes' not in result


def test_remote_rejects_bogus_maps_and_traversal(remote, tmp_path):
    manifest = xbox_maps(tmp_path / "data", remote)
    assert remote.verify_maps(tmp_path / "data", manifest) == 24 * 2048
    manifest["files"][0]["path"] = "maps/../maps/a10.map"
    with pytest.raises(ValueError, match="24 expected"):
        remote.verify_maps(tmp_path / "data", manifest)


def test_remote_path_guard_rejects_parent_traversal(remote):
    with pytest.raises(ValueError, match="traversal"):
        remote.beneath(remote.HOME / "../outside", remote.HOME)


def test_existing_custom_maps_preserved_but_never_uploaded(remote, tmp_path):
    directory = tmp_path / "data"
    manifest = xbox_maps(directory, remote)
    (directory / "maps/custom.map").write_bytes(b"unrelated user mod")
    with pytest.raises(ValueError, match="extra"):
        remote.verify_maps(directory, manifest)
    assert remote.verify_maps(directory, manifest, allow_extra=True) == 24 * 2048


def test_remote_detects_changed_original_xbox_header(remote, tmp_path):
    directory = tmp_path / "data"
    manifest = xbox_maps(directory, remote)
    target = directory / manifest["files"][0]["path"]
    data = bytearray(target.read_bytes())
    struct.pack_into("<I", data, 4, 7)
    target.write_bytes(data)
    with pytest.raises(ValueError, match="header"):
        remote.verify_maps(directory, manifest)


def test_repair_applies_standing_snap_without_resetting_other_vr_preferences(remote):
    old = '[vr]\nheight="seated"\nturn="smooth"\nsnap_turn_angle=45.0\nrefresh_rate=90.0\nplayer_height=1.8\n'
    updated = remote.tomllib.loads(remote.merge_config(old))
    assert updated['vr']['height'] == 'standing' and updated['vr']['turn'] == 'snap'
    assert updated['vr']['snap_turn_angle'] == 45.0
    assert updated['vr']['refresh_rate'] == 90.0 and updated['vr']['player_height'] == 1.8


def test_config_repair_preserves_isolated_save_location_and_user_preferences(remote):
    old = '[paths]\nsaves = ' + json.dumps(str(remote.save_root())) + '\n\n[audio]\nvolume = 0.4\n\n[vr]\naim="head"\nturn="snap"\nrefresh_rate=90.0\n\n[[plugins]]\nname="custom"\n'
    result = remote.tomllib.loads(remote.merge_config(old))
    assert result["paths"]["saves"] == str(remote.save_root())
    assert result["audio"]["volume"] == 0.4
    assert result["vr"]["aim"] == "controller"
    assert result["vr"]["turn"] == "snap" and result["vr"]["refresh_rate"] == 90.0
    assert result["plugins"] == [{"name": "custom"}]


def test_config_repair_refuses_semantic_changes_inside_multiline_string(remote):
    old = '[vr]\nnote = """\n[other]\nexample text\n"""\naim = "head"\nenabled = false\nmelee_gesture = true\n'
    with pytest.raises(ValueError, match="safely|unrelated"):
        remote.merge_config(old)


@pytest.mark.parametrize('value', ['/another/save/location', '../HaloCENativeVR/save', 'save', '', False])
def test_new_config_refuses_legacy_external_or_ambiguous_save_paths(remote, value):
    original = '[paths]\nsaves = ' + json.dumps(value) + '\n'
    with pytest.raises(ValueError, match='owned|own game folder|version 1.4'):
        remote.merge_config(original)


def test_new_config_missing_paths_gets_versioned_defaults(remote):
    updated = remote.tomllib.loads(remote.merge_config('[audio]\nvolume = 0.4\n'))
    assert updated['paths'] == {'data': str(remote.GAME), 'saves': str(remote.save_root())}
    assert updated['audio']['volume'] == 0.4
    assert updated['vr']['aim'] == 'controller' and updated['vr']['movement'] == 'head'
    assert updated['vr']['sun_glow_strength'] == 0.5
    assert updated['vr']['turn'] == 'snap' and updated['vr']['height'] == 'standing'
    assert updated['network']['coop_enemies_mode'] == 'none'


def test_repair_preserves_custom_sun_glow_strength(remote):
    updated = remote.tomllib.loads(remote.merge_config('[vr]\nsun_glow_strength=0.25\n'))
    assert updated['vr']['sun_glow_strength'] == 0.25


@pytest.mark.parametrize('repair', [False, True])
@pytest.mark.parametrize('unsafe', ['legacy-save-config', 'copied-experimental-config', 'symlinked-save-directory', 'missing-paths'])
def test_new_reuse_and_repair_guard_save_format_and_keep_experimental_instance(remote, repair, unsafe):
    experimental = remote.GAME.parent / 'HaloCENativeVRExperimental'
    (experimental / 'save').mkdir(parents=True)
    (experimental / 'halo').write_bytes(b'experimental executable')
    (experimental / 'save/checkpoint').write_bytes(b'experimental checkpoint')
    game = remote.GAME
    game.mkdir()
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', header, 18, 183)
    for name in ('halo', 'libSDL3.so.0'):
        (game / name).write_bytes(header)
    maps = xbox_maps(game, remote)
    (game / 'xbox-data-manifest.json').write_text(json.dumps(maps))
    (game / remote.MARKER).write_text(json.dumps({'owner': remote.OWNER,
        'sourceCommit': remote.SOURCE_COMMIT,
        'files': {name: remote.digest(game / name) for name in ('halo', 'libSDL3.so.0')}}))
    if unsafe == 'legacy-save-config':
        config = {'paths': {'data': str(game), 'saves': str(game / 'save')}}
    elif unsafe == 'copied-experimental-config':
        config = {'paths': {'data': str(experimental), 'saves': str(experimental / 'save')}}
    elif unsafe == 'missing-paths':
        config = {'audio': {'volume': 0.4}}
    else:
        try:
            remote.save_root().symlink_to(experimental / 'save', target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip('This host cannot create directory symlinks')
        config = {'paths': {'data': str(game), 'saves': str(remote.save_root())}}
    original = '\n'.join('[' + section + ']\n' + '\n'.join(key + ' = ' + json.dumps(value)
        for key, value in entries.items()) for section, entries in config.items()) + '\n'
    (game / 'config.toml').write_text(original)
    if unsafe == 'missing-paths' and repair:
        assert remote.existing_install(repair=True)['mapsVerified']
    else:
        with pytest.raises(ValueError, match='version 1.4|owned|own game folder|Symbolic links'):
            remote.existing_install(repair=repair)
    assert (game / 'config.toml').read_text() == original
    assert (experimental / 'halo').read_bytes() == b'experimental executable'
    assert (experimental / 'save/checkpoint').read_bytes() == b'experimental checkpoint'


def test_repair_backup_and_replacements_preserve_saves_and_unrelated_files(remote):
    game = remote.GAME
    game.mkdir(parents=True)
    (game / "halo").write_bytes(b"old executable")
    (game / "libSDL3.so.0").write_bytes(b"old library")
    (game / "save").mkdir()
    (game / "save/checkpoint").write_bytes(b"my campaign")
    (game / "notes.txt").write_bytes(b"my notes")
    directory = remote.CACHE / "runs" / ("a" * 32)
    stage = directory / "stage"
    stage.mkdir(parents=True)
    (stage / "halo").write_bytes(b"new executable")
    (stage / "libSDL3.so.0").write_bytes(b"new library")
    backup = remote.repair_program_files(stage, directory, ["halo", "libSDL3.so.0"], lambda: None)
    assert (game / "halo").read_bytes() == b"new executable"
    assert (Path(backup) / "halo").read_bytes() == b"old executable"
    assert (game / "save/checkpoint").read_bytes() == b"my campaign"
    assert (game / "notes.txt").read_bytes() == b"my notes"


def test_repair_rolls_back_on_failed_second_replacement(remote, monkeypatch):
    game = remote.GAME
    game.mkdir(parents=True)
    for name in ("halo", "libSDL3.so.0"):
        (game / name).write_bytes(("old " + name).encode())
    directory = remote.CACHE / "runs" / ("b" * 32)
    stage = directory / "stage"
    stage.mkdir(parents=True)
    for name in ("halo", "libSDL3.so.0"):
        (stage / name).write_bytes(("new " + name).encode())
    replace = remote.os.replace
    def fail_second(source, target):
        if Path(source) == stage / "libSDL3.so.0":
            raise OSError("simulated disk error")
        replace(source, target)
    monkeypatch.setattr(remote.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        remote.repair_program_files(stage, directory, ["halo", "libSDL3.so.0"], lambda: None)
    for name in ("halo", "libSDL3.so.0"):
        assert (game / name).read_bytes() == ("old " + name).encode()


def test_repair_rolls_back_if_cancel_arrives_after_first_file(remote, monkeypatch):
    game = remote.GAME
    game.mkdir(parents=True)
    (game / "halo").write_bytes(b"old halo")
    (game / "config.toml").write_bytes(b"old config")
    directory = remote.CACHE / "runs" / ("c" * 32)
    stage = directory / "stage"
    stage.mkdir(parents=True)
    (stage / "halo").write_bytes(b"new halo")
    (stage / "config.toml").write_bytes(b"new config")
    cancelled = False
    replace = remote.os.replace
    def after_first(source, target):
        nonlocal cancelled
        replace(source, target)
        if Path(source) == stage / "halo":
            cancelled = True
    def cancel_check():
        if cancelled:
            raise ValueError("cancelled")
    monkeypatch.setattr(remote.os, "replace", after_first)
    with pytest.raises(ValueError, match="cancelled"):
        remote.repair_program_files(stage, directory, ["halo", "config.toml"], cancel_check)
    assert (game / "halo").read_bytes() == b"old halo"
    assert (game / "config.toml").read_bytes() == b"old config"


def test_full_repair_rebuilds_damaged_native_files_preserves_maps_saves_and_config(remote, monkeypatch):
    game = remote.GAME
    game.mkdir(parents=True)
    maps = xbox_maps(game, remote)
    (game / "xbox-data-manifest.json").write_text(json.dumps(maps))
    (game / "halo").write_bytes(b"damaged executable")
    (game / "libSDL3.so.0").write_bytes(b"old library")
    (game / "config.toml").write_text('[paths]\nsaves=' + json.dumps(str(game / "save")) + '\n[audio]\nvolume=0.3\n[vr]\naim="head"\nturn="snap"\n')
    (game / "save").mkdir()
    (game / "save/checkpoint").write_bytes(b"campaign progress")
    (game / "maps/custom.map").write_bytes(b"user mod")
    marker = {"owner": remote.OWNER, "sourceCommit": "previous-source-revision", "files": {
        "halo": "0" * 64, "libSDL3.so.0": "0" * 64}}
    (game / remote.MARKER).write_text(json.dumps(marker))
    remote.owned(remote.CACHE)
    resources = remote.CACHE / "resources"
    resources.mkdir()
    (resources / "frame-controls.patch").write_bytes(b"frame controls patch")
    identifier = "d" * 32
    directory = remote.CACHE / "runs" / identifier
    remote.owned(directory)
    run_marker = remote.read_marker(directory / remote.MARKER)
    run_marker["mapsOrigin"] = "existing"
    (directory / remote.MARKER).write_text(json.dumps(run_marker))
    (directory / "stage").mkdir()
    (directory / "upload").mkdir()
    (directory / "upload/xbox-data-manifest.json").write_text(json.dumps(maps))
    build = directory / "src/build/linux_arm64"
    build.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    (build / "halo").write_bytes(header + b"new native game")
    (build / "libSDL3.so.0").write_bytes(header + b"new native library")
    (build / "brokers.txt").write_text("broker.example.org:1883\n")
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "native libraries resolved")
    response = remote.finalize(identifier, repair=True)
    assert response["repaired"] is True and response["mapsReinstalled"] is False
    assert (game / "halo").read_bytes() == header + b"new native game"
    assert (game / "save/checkpoint").read_bytes() == b"campaign progress"
    assert (game / "brokers.txt").read_text() == "broker.example.org:1883\n"
    assert remote.read_marker(game / remote.MARKER)["files"]["brokers.txt"] == remote.digest(game / "brokers.txt")
    assert (game / "maps/custom.map").read_bytes() == b"user mod"
    merged = remote.tomllib.loads((game / "config.toml").read_text())
    assert merged["paths"]["saves"] == str(remote.save_root())
    assert remote.save_root().is_dir() and not any(remote.save_root().iterdir())
    assert merged["audio"]["volume"] == 0.3
    assert merged["vr"]["aim"] == "controller" and merged["vr"]["turn"] == "snap"
    assert remote.read_marker(game / remote.MARKER)["sourceCommit"] == remote.SOURCE_COMMIT
    assert remote.existing_install()["mapsVerified"] is True


def native_install(remote, *, source=None, save_path=None):
    game = remote.GAME
    game.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    for name in ("halo", "libSDL3.so.0"):
        (game / name).write_bytes(header + b"previous native program")
    manifest = xbox_maps(game, remote)
    (game / "xbox-data-manifest.json").write_text(json.dumps(manifest))
    save_path = save_path or game / "save"
    save_path.mkdir(parents=True)
    (save_path / "checkpoint").write_bytes(b"incompatible previous checkpoint")
    (game / "config.toml").write_text('[paths]\ndata = ' + json.dumps(str(game))
        + '\nsaves = ' + json.dumps(str(save_path)) + '\n[audio]\nvolume = 0.3\n[vr]\nturn = "snap"\n')
    marker = {"owner": remote.OWNER, "sourceCommit": source or remote.LEGACY_SOURCE_COMMIT,
              "files": {name: remote.digest(game / name) for name in ("halo", "libSDL3.so.0")}}
    (game / remote.MARKER).write_text(json.dumps(marker))
    return manifest, save_path


def built_run(remote, manifest, identifier, *, existing=True):
    remote.owned(remote.CACHE)
    resources = remote.CACHE / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "frame-controls.patch").write_bytes(b"tested gameplay patch")
    directory = remote.CACHE / "runs" / identifier
    remote.owned(directory)
    metadata = remote.read_marker(directory / remote.MARKER)
    metadata["mapsOrigin"] = "existing" if existing else "upload"
    (directory / remote.MARKER).write_text(json.dumps(metadata))
    (directory / "stage").mkdir()
    upload = directory / "upload"
    upload.mkdir()
    if not existing:
        manifest = xbox_maps(upload, remote)
    (upload / "xbox-data-manifest.json").write_text(json.dumps(manifest))
    build = directory / "src/build/linux_arm64"
    build.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    for name in ("halo", "libSDL3.so.0"):
        (build / name).write_bytes(header + b"new native program")
    (build / "brokers.txt").write_text("broker.example.org:1883\n")
    return directory


@pytest.mark.parametrize("kind", ["default", "custom-internal", "external"])
def test_verified_stable_upgrade_keeps_old_checkpoints_and_backs_up_config(remote, monkeypatch, kind):
    path = {"default": remote.GAME / "save", "custom-internal": remote.GAME / "profiles/custom",
            "external": remote.HOME / "external-checkpoints"}[kind]
    manifest, previous = native_install(remote, save_path=path)
    checkpoint = previous / "checkpoint"
    before = (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns)
    old_config = (remote.GAME / "config.toml").read_bytes()
    old_program = (remote.GAME / "halo").read_bytes()
    closed = Mock()
    monkeypatch.setattr(remote, "game_closed", closed)
    verified = remote.existing_install()
    assert verified["needsUpgrade"] and verified["mapsVerified"]
    assert verified["previousSavePaths"] == [str(previous)]
    closed.assert_called_once()
    identifier = "e" * 32
    built_run(remote, manifest, identifier)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "native libraries resolved")
    result = remote.finalize(identifier, repair=True)
    assert result["repaired"] and not result["mapsReinstalled"]
    assert result["previousSavePaths"] == [str(previous)]
    assert (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns) == before
    assert (Path(result["backupPath"]) / "config.toml").read_bytes() == old_config
    assert (Path(result["backupPath"]) / "halo").read_bytes() == old_program
    settings = remote.tomllib.loads((remote.GAME / "config.toml").read_text())
    assert settings["paths"] == {"data": str(remote.GAME), "saves": str(remote.save_root())}
    assert settings["audio"]["volume"] == 0.3 and settings["vr"]["turn"] == "snap"
    assert remote.save_root().is_dir() and not any(remote.save_root().iterdir())
    marker = remote.read_marker(remote.GAME / remote.MARKER)
    assert marker["installerVersion"] == "1.4.1" and marker["networkProtocol"] == 17
    assert marker["saveRoot"] == str(remote.save_root()) and "experimental" not in marker
    assert not remote.existing_install()["needsUpgrade"]
    # A later Repair preserves both generations and the former custom location.
    (remote.save_root() / "checkpoint").write_bytes(b"new compatible checkpoint")
    built_run(remote, manifest, "f" * 32)
    remote.finalize("f" * 32, repair=True)
    assert remote.read_marker(remote.GAME / remote.MARKER)["previousSavePaths"] == [str(previous)]
    assert checkpoint.read_bytes() == before[0]
    assert (remote.save_root() / "checkpoint").read_bytes() == b"new compatible checkpoint"
    inventory = remote.uninstall_inventory(remote.GAME)
    selected, external = remote.uninstall_save_files(inventory)
    assert str(Path("save-v1.4/checkpoint")) in selected
    if kind == "external":
        assert external == [str(previous)] and not any("external-checkpoints" in item for item in selected)
    else:
        assert str(checkpoint.relative_to(remote.GAME)) in selected


@pytest.mark.parametrize("trigger", ["marker-failure", "cancel-after-marker"])
def test_failed_upgrade_restores_original_program_config_marker_and_all_checkpoints(remote, monkeypatch, trigger):
    manifest, previous = native_install(remote)
    old = {name: (remote.GAME / name).read_bytes() for name in ("halo", "libSDL3.so.0", "config.toml", remote.MARKER)}
    checkpoint = previous / "checkpoint"
    checkpoint_signature = (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns)
    identifier = "a" * 32
    directory = built_run(remote, manifest, identifier)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "native libraries resolved")
    replace = remote.os.replace
    def fail_marker(source, target):
        if Path(source) == directory / "stage" / remote.MARKER:
            if trigger == "marker-failure":
                raise OSError("injected final marker failure")
            replace(source, target)
            (directory / "cancelled").write_text("cancel immediately after marker publication")
            return
        return replace(source, target)
    monkeypatch.setattr(remote.os, "replace", fail_marker)
    with pytest.raises((OSError, ValueError), match="marker failure|cancelled"):
        remote.finalize(identifier, repair=True)
    assert {name: (remote.GAME / name).read_bytes() for name in old} == old
    assert (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns) == checkpoint_signature
    assert remote.save_root().is_dir() and not any(remote.save_root().iterdir())
    assert remote.existing_install()["needsUpgrade"]  # Empty failed-run directory permits retry.


@pytest.mark.parametrize("damage", ["program-hash", "map", "unknown-revision", "occupied-new-save"])
def test_automatic_upgrade_refuses_unverified_or_unknown_state(remote, damage):
    _, previous = native_install(remote)
    config = (remote.GAME / "config.toml").read_bytes()
    if damage == "program-hash":
        with (remote.GAME / "halo").open("ab") as stream:
            stream.write(b"modified")
    elif damage == "map":
        (remote.GAME / "maps/a10.map").write_bytes(b"invalid map")
    elif damage == "unknown-revision":
        marker = remote.read_marker(remote.GAME / remote.MARKER)
        marker["sourceCommit"] = "unknown source"
        (remote.GAME / remote.MARKER).write_text(json.dumps(marker))
    else:
        remote.save_root().mkdir()
        (remote.save_root() / "checkpoint").write_bytes(b"unknown save format")
    with pytest.raises(ValueError):
        remote.existing_install()
    assert (remote.GAME / "config.toml").read_bytes() == config
    assert (previous / "checkpoint").read_bytes() == b"incompatible previous checkpoint"


def test_legacy_library_and_finalize_cannot_shortcut_the_upgrade(remote, monkeypatch):
    manifest, _ = native_install(remote)
    monkeypatch.setattr(remote, "preflight_uninstall", lambda: {"home": str(remote.HOME)})
    with pytest.raises(ValueError, match="Use Install"):
        remote.preflight_library()
    with pytest.raises(ValueError, match="Use Install"):
        remote.shortcut()
    built_run(remote, manifest, "b" * 32)
    with pytest.raises(ValueError, match="needs a version 1.4 upgrade"):
        remote.build("b" * 32)
    with pytest.raises(ValueError, match="needs a version 1.4 upgrade"):
        remote.finalize("b" * 32)


def test_install_automatically_promotes_verified_legacy_source_to_repair_without_map_upload():
    class UpgradeConnection(FakeConnection):
        def run(self, argv, **kwargs):
            if argv[1] == "-c":
                reply = json.loads(super().run(argv, **kwargs).removeprefix("HFI_RESULT "))
                reply["existing"]["needsUpgrade"] = True
                return "HFI_RESULT " + json.dumps(reply)
            if argv[2] in ("build", "finalize"):
                self.commands.append(argv)
                return "HFI_RESULT " + json.dumps({"gamePath": "/home/steamos/Games/HaloCENativeVR", "repaired": True})
            return super().run(argv, **kwargs)
    settings = Settings("frame", "private", reinstall_existing=False)
    fake = UpgradeConnection(settings)
    progress = []
    result = Installer(lambda _: fake, RESOURCES).run(settings, None, lambda *args: progress.append(args))
    assert result.repaired and not result.reused and fake.closed
    steps = [argv for argv in fake.commands if argv[1] != "-c"]
    assert [argv[2] for argv in steps] == ["prepare", "build", "finalize", "shortcut"]
    assert all("--repair" in argv for argv in steps)
    assert "--use-existing-maps" in steps[0]
    assert all(not remote.endswith(".map") for _, remote in fake.uploads)
    assert any(args[0] == "upgrade" and "save-v1.4" in args[1] for args in progress)


def test_library_registration_rejects_legacy_preflight_response_without_upload_or_build():
    class LegacyConnection(FakeConnection):
        def run(self, argv, **kwargs):
            reply = json.loads(super().run(argv, **kwargs).removeprefix("HFI_RESULT "))
            reply["existing"]["needsUpgrade"] = True
            return "HFI_RESULT " + json.dumps(reply)
    fake = LegacyConnection(Settings("frame", "private"))
    with pytest.raises(SSHError, match="Use Install"):
        Installer(lambda _: fake, RESOURCES).add_to_steam(fake.settings)
    assert fake.closed and not fake.uploads and len(fake.commands) == 1


def test_keep_saves_retains_both_known_roots_even_without_config(remote):
    native_install(remote)
    (remote.GAME / "config.toml").unlink()
    remote.save_root().mkdir()
    (remote.save_root() / "checkpoint").write_bytes(b"new checkpoint")
    selected, external = remote.uninstall_save_files(remote.uninstall_inventory(remote.GAME))
    assert selected == [str(Path("save-v1.4/checkpoint")), str(Path("save/checkpoint"))] and not external


def frame_preflight(remote, monkeypatch, free):
    monkeypatch.setattr(remote.pwd, "getpwuid", lambda uid: types.SimpleNamespace(pw_name="steamos"))
    monkeypatch.setattr(remote.pathlib.Path, "home", lambda: remote.HOME)
    monkeypatch.setattr(remote.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(remote, "os_release", lambda: {"ID": "steamos"})
    monkeypatch.setattr(remote.shutil, "which", lambda name: name)
    monkeypatch.setattr(remote.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=free))
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: '{"host":{"security":{"rootless":true}}}')
    library = remote.HOME / "steamvr/linuxarm64/runtime.so"
    library.parent.mkdir(parents=True)
    library.write_bytes(b"test runtime")
    runtime = remote.HOME / ".config/openxr/1/active_runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({"runtime": {"library_path": str(library)}}))


def test_automatic_upgrade_requires_build_space_and_closed_game(remote, monkeypatch):
    native_install(remote)
    frame_preflight(remote, monkeypatch, free=remote.MIN_FREE_BYTES - 1)
    with pytest.raises(ValueError, match="12 GiB"):
        remote.preflight()
    monkeypatch.setattr(remote.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=remote.MIN_FREE_BYTES))
    closed = Mock(side_effect=ValueError("game is running"))
    monkeypatch.setattr(remote, "game_closed", closed)
    with pytest.raises(ValueError, match="game is running"):
        remote.preflight()
    closed.assert_called_once()
    monkeypatch.setattr(remote, "game_closed", lambda: None)
    assert remote.preflight()["existing"]["needsUpgrade"]


def test_fresh_install_publishes_only_new_save_format(remote, monkeypatch):
    identifier = "c" * 32
    built_run(remote, {}, identifier, existing=False)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "native libraries resolved")
    monkeypatch.setattr(remote, "rename_noreplace", lambda source, target: source.rename(target))
    result = remote.finalize(identifier)
    assert not result["reused"] and remote.save_root().is_dir()
    assert not (remote.GAME / "save").exists()
    settings = remote.tomllib.loads((remote.GAME / "config.toml").read_text())
    assert settings["paths"]["saves"] == str(remote.save_root())
    assert remote.read_marker(remote.GAME / remote.MARKER)["previousSavePaths"] == []
    assert not remote.existing_install()["needsUpgrade"]


def test_legacy_upgrade_refuses_previous_save_metadata_overflow_before_any_replacement(remote):
    native_install(remote)
    marker = remote.read_marker(remote.GAME / remote.MARKER)
    marker["previousSavePaths"] = [str(remote.GAME / ("previous-" + str(index))) for index in range(32)]
    (remote.GAME / remote.MARKER).write_text(json.dumps(marker))
    config = (remote.GAME / "config.toml").read_bytes()
    with pytest.raises(ValueError, match="save-location count"):
        remote.existing_install()
    assert (remote.GAME / "config.toml").read_bytes() == config and not remote.save_root().exists()


def test_recognized_codex_legacy_marker_upgrades_without_changing_old_checkpoint(remote, monkeypatch):
    manifest, previous = native_install(remote)
    marker = remote.read_marker(remote.GAME / remote.MARKER)
    marker["owner"] = "codex-halo-native-frame-20261005"
    marker["build"] = {"sourceCommit": marker.pop("sourceCommit")}
    (remote.GAME / remote.MARKER).unlink()
    codex = remote.GAME / ".codex-halo-native-install.json"
    codex.write_text(json.dumps(marker))
    before = codex.read_bytes()
    assert remote.existing_install()["needsUpgrade"]
    built_run(remote, manifest, "d" * 32)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "native libraries resolved")
    remote.finalize("d" * 32, repair=True)
    assert codex.read_bytes() == before
    assert (previous / "checkpoint").read_bytes() == b"incompatible previous checkpoint"
    assert remote.read_marker(remote.GAME / remote.MARKER)["sourceCommit"] == remote.SOURCE_COMMIT
    assert not remote.existing_install()["needsUpgrade"]
