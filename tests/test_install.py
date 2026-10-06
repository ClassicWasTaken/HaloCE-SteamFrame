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

from halo_frame_installer.install import EXPECTED_MAPS, Installer, SOURCE_COMMIT, map_manifest, parse_result
from halo_frame_installer.ssh import CancelledError, Settings, SSHError

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


def test_config_repair_preserves_save_location_and_user_preferences(remote):
    old = '[paths]\nsaves = "/another/save/location"\n\n[audio]\nvolume = 0.4\n\n[vr]\naim="head"\nturn="snap"\nrefresh_rate=90.0\n\n[[plugins]]\nname="custom"\n'
    result = remote.tomllib.loads(remote.merge_config(old))
    assert result["paths"]["saves"] == "/another/save/location"
    assert result["audio"]["volume"] == 0.4
    assert result["vr"]["aim"] == "controller"
    assert result["vr"]["turn"] == "snap" and result["vr"]["refresh_rate"] == 90.0
    assert result["plugins"] == [{"name": "custom"}]


def test_config_repair_refuses_semantic_changes_inside_multiline_string(remote):
    old = '[vr]\nnote = """\n[other]\nexample text\n"""\naim = "head"\nenabled = false\nmelee_gesture = true\n'
    with pytest.raises(ValueError, match="safely|unrelated"):
        remote.merge_config(old)


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
    (game / "config.toml").write_text('[paths]\nsaves="/my/saves"\n[audio]\nvolume=0.3\n[vr]\naim="head"\nturn="snap"\n')
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
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "native libraries resolved")
    response = remote.finalize(identifier, repair=True)
    assert response["repaired"] is True and response["mapsReinstalled"] is False
    assert (game / "halo").read_bytes() == header + b"new native game"
    assert (game / "save/checkpoint").read_bytes() == b"campaign progress"
    assert (game / "maps/custom.map").read_bytes() == b"user mod"
    merged = remote.tomllib.loads((game / "config.toml").read_text())
    assert merged["paths"]["saves"] == "/my/saves"
    assert merged["audio"]["volume"] == 0.3
    assert merged["vr"]["aim"] == "controller" and merged["vr"]["turn"] == "snap"
    assert remote.read_marker(game / remote.MARKER)["sourceCommit"] == remote.SOURCE_COMMIT
    assert remote.existing_install()["mapsVerified"] is True
