"""Uninstall real owned trees and VDF files without touching external data."""

import importlib.util
import json
import os
import sys
import types
from collections import OrderedDict
from pathlib import Path
from unittest.mock import Mock

import pytest


RESOURCES = Path(__file__).resolve().parents[1] / "resources"
RUN_ID = "b" * 32


@pytest.fixture
def installation(tmp_path, monkeypatch):
    if "pwd" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: None))
    if not hasattr(os, "getuid"):
        monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    modules = []
    for name, resource in (("uninstall_remote_test", "remote_install"), ("steam_shortcut", "steam_shortcut")):
        spec = importlib.util.spec_from_file_location(name, RESOURCES / (resource + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    remote, steam = modules
    remote.HOME = tmp_path / "home"
    remote.HOME.mkdir()
    remote.CACHE = remote.HOME / ".cache/halo-frame-installer"
    remote.GAME = remote.HOME / "Games/HaloCENativeVR"
    monkeypatch.setattr(remote.pwd, "getpwuid", lambda uid: types.SimpleNamespace(pw_name="steamos"))
    monkeypatch.setattr(remote.pathlib.Path, "home", lambda: remote.HOME)
    monkeypatch.setattr(remote.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(remote, "os_release", lambda: {"ID": "steamos"})
    monkeypatch.setattr(remote.shutil, "which", lambda executable: "/usr/bin/podman" if executable == "podman" else None)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "[]")
    monkeypatch.setattr(steam, "steam_running", lambda: False)
    if os.name == "nt":
        monkeypatch.setattr(remote, "game_closed", lambda *args: None)
        # Windows rename already refuses an existing destination. Linux tests use
        # the actual renameat2(RENAME_NOREPLACE) implementation.
        monkeypatch.setattr(remote, "rename_noreplace", lambda source, target: os.rename(source, target))
    remote.owned(remote.GAME)
    (remote.GAME / "maps").mkdir()
    (remote.GAME / "save").mkdir()
    (remote.GAME / "halo").write_bytes(b"damaged native executable")
    (remote.GAME / "libSDL3.so.0").write_bytes(b"damaged SDL3 library")
    (remote.GAME / "maps/a10.map").write_bytes(b"damaged or incomplete Xbox maps")
    (remote.GAME / "save/profile.sav").write_bytes(b"campaign progress")
    (remote.GAME / "config.toml").write_text('[paths]\nsaves = "save"\n[video]\ncustom = true\n')
    marker = json.loads((remote.GAME / remote.MARKER).read_text())
    marker["files"] = {"halo": "incorrect old hash"}
    (remote.GAME / remote.MARKER).write_text(json.dumps(marker))
    directory = remote.HOME / ".local/share/Steam"
    configs = [directory / "userdata" / account / "config" for account in ("10", "20")]
    foreign = OrderedDict([("appid", steam.Value(2, 2147483650)), ("AppName", steam.Value(1, "Other game")),
                           ("Exe", steam.Value(1, '"/other/game"')), ("unknown", steam.Value(7, b"FOREIGN!"))])
    base = steam.dumps(OrderedDict([("shortcuts", steam.Value(0, OrderedDict([("0", steam.Value(0, foreign))])))]))
    appids = []
    for config in configs:
        config.mkdir(parents=True)
        raw, appid = steam.update_shortcut(base, str(remote.GAME / "halo"), str(remote.GAME))
        root = steam.loads(raw)
        root["unknown-root"] = steam.Value(7, b"ROOTDATA")
        root["shortcuts"].value["2"] = steam.Value(0, OrderedDict([
            ("appid", steam.Value(2, 0xF1122334)), ("AppName", steam.Value(1, steam.NAME)),
            ("Exe", steam.Value(1, '"/external/Halo.exe"'))]))
        (config / "shortcuts.vdf").write_bytes(steam.dumps(root))
        steam.install_artwork(config, appid)
        appids.append(appid)
    (configs[1] / "grid" / f"{appids[1]}.png").write_bytes(b"custom user tile")
    (configs[0] / "grid/10p.jpg").write_bytes(b"other game's art")
    old_pc = remote.HOME / "Games/HaloCEVR"
    old_pc.mkdir()
    (old_pc / "halo.exe").write_bytes(b"old PC version; this operation must not delete it")
    remote.preflight_uninstall()
    retained = remote.CACHE / "runs" / ("c" * 32)
    remote.owned(retained)
    (retained / "native-build.log").write_bytes(b"previous build log retained")
    return remote, steam, configs, appids, foreign


def game_bytes(remote):
    return {str(path.relative_to(remote.GAME)): path.read_bytes() for path in remote.GAME.rglob("*")
            if path.is_file() and not path.is_symlink()}


def record_quarantine(remote, identifier, quarantine, saved=None, *, legacy=False):
    """Model the journal made by an actual interrupted uninstall, not a label."""
    directory = remote.CACHE / "runs" / identifier
    metadata = remote.owned(directory)
    metadata.update({"operation": "uninstall", "state": "removing", "quarantinePath": str(quarantine),
                     "savedBackupPath": str(saved) if saved else None})
    if not legacy:
        metadata["quarantineRoot"] = remote.uninstall_root_identity(quarantine)
    if saved:
        backup = {"owner": remote.OWNER + "-save-backup", "gamePath": str(remote.GAME)}
        if not legacy:
            backup["files"] = {str(path.relative_to(saved)): {"size": path.stat().st_size,
                                                             "sha256": remote.digest(path)}
                               for path in saved.rglob("*") if path.is_file() and path.name != remote.MARKER}
            metadata["savedBackupRoot"] = remote.uninstall_root_identity(saved)
        (saved / remote.MARKER).write_text(json.dumps(backup))
    remote.write_uninstall_record(directory, metadata)
    return directory / remote.MARKER


def test_uninstall_keeps_saves_removes_all_exact_native_entries_and_managed_art(installation, capsys):
    remote, steam, configs, appids, foreign = installation
    original_config = (remote.GAME / "config.toml").read_bytes()
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert result["uninstalled"] and result["steam"]["status"] == "removed"
    assert result["steam"]["accounts"] == ["10", "20"]
    assert not remote.GAME.exists()
    saved = Path(result["savedBackupPath"])
    assert saved == remote.HOME / ("Games/HaloCENativeVR-saves-" + RUN_ID)
    assert (saved / "save/profile.sav").read_bytes() == b"campaign progress"
    assert (saved / "config.toml").read_bytes() == original_config
    assert not (saved / "maps").exists() and not (saved / "halo").exists()
    for config, appid in zip(configs, appids):
        root = steam.loads((config / "shortcuts.vdf").read_bytes())
        assert root["unknown-root"].value == b"ROOTDATA"
        assert root["shortcuts"].value["0"].value == foreign
        assert set(root["shortcuts"].value) == {"0", "2"}
        assert not (config / "grid" / f"{appid}p.jpg").exists()
        backups = list(config.glob("shortcuts.vdf.halo-frame-uninstall-*.bak"))
        assert len(backups) == 1
        assert "1" in steam.loads(backups[0].read_bytes())["shortcuts"].value
    assert not (configs[0] / "grid" / f"{appids[0]}.png").exists()
    assert (configs[1] / "grid" / f"{appids[1]}.png").read_bytes() == b"custom user tile"
    assert (configs[0] / "grid/10p.jpg").read_bytes() == b"other game's art"
    assert (remote.HOME / "Games/HaloCEVR/halo.exe").is_file()
    assert (remote.CACHE / "runs" / ("c" * 32) / "native-build.log").is_file()
    updates = [json.loads(line.split(" ", 1)[1]) for line in capsys.readouterr().out.splitlines()
               if line.startswith("HFI_PROGRESS ")]
    assert updates[-1]["percent"] == 100 and all(update["stage"] == "uninstall" for update in updates)
    assert remote.uninstall(RUN_ID, keep_saves=True)["alreadyAbsent"]
    assert (saved / "save/profile.sav").read_bytes() == b"campaign progress"


def test_uninstall_removes_a_native_entry_the_user_renamed(installation):
    remote, steam, configs, appids, _ = installation
    config = configs[0]
    executable = str(remote.GAME / "halo")
    root = steam.loads((config / "shortcuts.vdf").read_bytes())
    for entry in root["shortcuts"].value.values():
        path = entry.value.get("Exe")
        if path is not None and path.value in (executable, f'"{executable}"'):
            entry.value["AppName"] = steam.Value(1, "My favorite Halo")
    (config / "shortcuts.vdf").write_bytes(steam.dumps(root))
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert result["uninstalled"] and result["steam"]["status"] == "removed"
    assert result["steam"]["accounts"] == ["10", "20"]
    remaining = steam.loads((config / "shortcuts.vdf").read_bytes())["shortcuts"].value
    assert set(remaining) == {"0", "2"}
    assert "My favorite Halo" not in {entry.value["AppName"].value for entry in remaining.values()}
    assert result["steam"]["appids"] == sorted(set(appids))
    assert not (config / "grid" / f"{appids[0]}p.jpg").exists()
    assert not (config / "grid" / f"{appids[0]}.png").exists()
    assert (configs[1] / "grid" / f"{appids[1]}.png").read_bytes() == b"custom user tile"
    assert (configs[0] / "grid/10p.jpg").read_bytes() == b"other game's art"
    backups = list(config.glob("shortcuts.vdf.halo-frame-uninstall-*.bak"))
    assert len(backups) == 1 and b"My favorite Halo" in backups[0].read_bytes()


def test_uninstall_refuses_exact_native_malformed_ids_without_changing_files_or_art(installation):
    remote, steam, configs, _, _ = installation
    config = configs[0]
    executable = str(remote.GAME / "halo")
    root = steam.loads((config / "shortcuts.vdf").read_bytes())
    root["shortcuts"].value["3"] = steam.Value(0, OrderedDict([
        ("appid", steam.Value(1, "not-a-number")), ("AppName", steam.Value(1, "Broken id")),
        ("Exe", steam.Value(1, executable))]))
    root["shortcuts"].value["4"] = steam.Value(0, OrderedDict([
        ("appid", steam.Value(2, 0xF2233445)), ("AppName", steam.Value(1, "Odd quotes")),
        ("Exe", steam.Value(1, executable + '"'))]))
    (config / "shortcuts.vdf").write_bytes(steam.dumps(root))
    before = game_bytes(remote)
    shortcut_bytes = [(path / "shortcuts.vdf").read_bytes() for path in configs]
    artwork = {str(path): path.read_bytes() for directory in configs for path in (directory / "grid").iterdir()}
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert not result["uninstalled"] and result["steam"]["status"] == "manual"
    assert game_bytes(remote) == before
    assert [(path / "shortcuts.vdf").read_bytes() for path in configs] == shortcut_bytes
    assert {str(path): path.read_bytes() for directory in configs for path in (directory / "grid").iterdir()} == artwork
    remaining = steam.loads((config / "shortcuts.vdf").read_bytes())["shortcuts"].value
    assert set(remaining) == {"0", "1", "2", "3", "4"}


def test_uninstall_without_keep_saves_deletes_contained_saves_only(installation):
    remote, _, _, _, _ = installation
    outside = remote.HOME / "external-saves"
    outside.mkdir()
    (outside / "campaign.sav").write_bytes(b"external campaign")
    (remote.GAME / "config.toml").write_text('[paths]\nsaves = ' + json.dumps(outside.as_posix()) + '\n')
    result = remote.uninstall(RUN_ID)
    assert result["uninstalled"] and result["savedBackupPath"] is None
    assert not remote.GAME.exists()
    assert (outside / "campaign.sav").read_bytes() == b"external campaign"
    assert not list((remote.HOME / "Games").glob("HaloCENativeVR-saves-*"))


@pytest.mark.parametrize("contained", [False, True])
def test_keep_saves_respects_configured_location_without_reading_external_data(installation, contained):
    remote, _, _, _, _ = installation
    configured = remote.GAME / "profiles/custom" if contained else remote.HOME / "external-saves"
    configured.mkdir(parents=True)
    (configured / "second.sav").write_bytes(b"other profile")
    (remote.GAME / "config.toml").write_text('[paths]\nsaves = ' + json.dumps(configured.as_posix()) + '\n')
    result = remote.uninstall(RUN_ID, keep_saves=True)
    saved = Path(result["savedBackupPath"])
    assert (saved / "save/profile.sav").is_file()
    if contained:
        assert (saved / "profiles/custom/second.sav").read_bytes() == b"other profile"
        assert result["externalSavePathsPreserved"] == []
    else:
        assert (configured / "second.sav").read_bytes() == b"other profile"
        assert not (saved / "external-saves").exists()
        assert result["externalSavePathsPreserved"] == [str(configured)]


def test_previous_guided_native_marker_allows_damaged_game_removal(installation):
    remote, _, _, _, _ = installation
    (remote.GAME / remote.MARKER).unlink()
    (remote.GAME / ".codex-halo-native-install.json").write_text(json.dumps({
        "owner": "codex-halo-native-frame-20261005", "build": {"sourceCommit": "older native revision"}}))
    (remote.GAME / "halo").unlink()
    assert remote.uninstall(RUN_ID)["uninstalled"]
    assert not remote.GAME.exists()


@pytest.mark.parametrize("foreign", [False, True])
def test_unmarked_or_foreign_folder_is_refused_before_steam_changes(installation, foreign):
    remote, _, configs, _, _ = installation
    marker = remote.GAME / remote.MARKER
    if foreign:
        marker.write_text('{"owner":"another-application"}')
    else:
        marker.unlink()
    before = game_bytes(remote)
    shortcuts = [(config / "shortcuts.vdf").read_bytes() for config in configs]
    with pytest.raises(ValueError, match="ownership|another application"):
        remote.uninstall(RUN_ID)
    assert game_bytes(remote) == before
    assert [(config / "shortcuts.vdf").read_bytes() for config in configs] == shortcuts


def test_live_steam_returns_manual_and_keeps_game_and_staged_saves_untouched(installation, monkeypatch):
    remote, steam, configs, _, _ = installation
    before = game_bytes(remote)
    raw = [(config / "shortcuts.vdf").read_bytes() for config in configs]
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert not result["uninstalled"] and result["steam"]["status"] == "manual"
    assert result["savedBackupPath"] is None
    assert game_bytes(remote) == before
    assert [(config / "shortcuts.vdf").read_bytes() for config in configs] == raw
    assert not list((remote.HOME / "Games").glob("*HaloCENativeVR-saves-*"))


@pytest.mark.parametrize("running", ["game", "build"])
def test_running_native_game_or_owned_build_prevents_all_mutation(installation, monkeypatch, running):
    remote, _, configs, _, _ = installation
    before = game_bytes(remote)
    raw = [(config / "shortcuts.vdf").read_bytes() for config in configs]
    if running == "game":
        def game_closed(*args):
            raise ValueError("Halo is still running")
        monkeypatch.setattr(remote, "game_closed", game_closed)
    else:
        monkeypatch.setattr(remote, "command", lambda argv, **kwargs: '[{"Names":["halo-frame-installer-active"]}]')
    with pytest.raises(ValueError, match="still running"):
        remote.uninstall(RUN_ID)
    assert game_bytes(remote) == before
    assert [(config / "shortcuts.vdf").read_bytes() for config in configs] == raw


@pytest.mark.parametrize("where", ["root", "nested"])
def test_symlink_paths_are_refused_without_deleting_their_targets(installation, where):
    remote, _, configs, _, _ = installation
    outside = remote.HOME / "outside"
    outside.mkdir()
    protected = outside / "keep.sav"
    protected.write_bytes(b"outside data")
    original = remote.GAME
    link = remote.GAME / "save/linked" if where == "nested" else remote.GAME
    if where == "root":
        original = remote.GAME.with_name("original-native")
        os.rename(remote.GAME, original)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation requires additional privileges.")
    before = [(config / "shortcuts.vdf").read_bytes() for config in configs]
    with pytest.raises(ValueError, match="Symbolic|symbolic"):
        remote.uninstall(RUN_ID)
    assert protected.read_bytes() == b"outside data"
    assert (original / "halo").is_file()
    assert [(config / "shortcuts.vdf").read_bytes() for config in configs] == before


def test_hardlinked_map_is_not_deleted_and_traversal_run_id_is_rejected(installation):
    remote, _, _, _, _ = installation
    outside = remote.HOME / "foreign.map"
    outside.write_bytes(b"outside file")
    os.link(outside, remote.GAME / "maps/linked.map")
    with pytest.raises(ValueError, match="hard link"):
        remote.uninstall(RUN_ID)
    with pytest.raises(ValueError, match="run identifier"):
        remote.uninstall("../" + RUN_ID)
    assert outside.read_bytes() == b"outside file" and remote.GAME.exists()


def test_same_device_bind_mount_is_rejected_before_removal(installation, monkeypatch):
    remote, _, _, _, _ = installation
    before = game_bytes(remote)
    monkeypatch.setattr(remote, "uninstall_mounts", lambda: [remote.GAME / "maps"])
    with pytest.raises(ValueError, match="mount"):
        remote.uninstall(RUN_ID)
    assert game_bytes(remote) == before


def test_partial_file_removal_reports_quarantine_and_save_backup_honestly(installation, monkeypatch):
    remote, _, _, _, _ = installation
    original_unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path.parent.name == ".HaloCENativeVR-uninstall-" + RUN_ID and path.name == "halo":
            raise OSError("simulated deletion failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(RuntimeError, match="Remaining native files are in") as error:
        remote.uninstall(RUN_ID, keep_saves=True)
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + RUN_ID)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + RUN_ID)
    assert not remote.GAME.exists() and (quarantine / "halo").is_file()
    assert (saved / "save/profile.sav").read_bytes() == b"campaign progress"
    assert str(saved) in str(error.value)
    assert "game was kept" not in str(error.value).lower()
    before = {str(path.relative_to(saved)): path.read_bytes() for path in saved.rglob("*") if path.is_file()}
    monkeypatch.setattr(Path, "unlink", original_unlink)
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert result["uninstalled"] and not result["alreadyAbsent"] and not quarantine.exists()
    assert result["savedBackupPath"] == str(saved)
    assert {str(path.relative_to(saved)): path.read_bytes() for path in saved.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("legacy", [False, True])
def test_interrupted_uninstall_leftovers_are_finished_by_the_next_run(installation, legacy):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + previous)
    os.rename(remote.GAME, quarantine)
    saved.mkdir()
    (saved / remote.MARKER).write_text(json.dumps({"owner": remote.OWNER + "-save-backup"}))
    (saved / "save").mkdir()
    (saved / "save/profile.sav").write_bytes(b"earlier campaign")
    record_quarantine(remote, previous, quarantine, saved, legacy=legacy)
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert result["uninstalled"] is True and result["alreadyAbsent"] is False
    assert not quarantine.exists() and not remote.GAME.exists()
    assert (saved / "save/profile.sav").read_bytes() == b"earlier campaign"
    assert str(quarantine) in result["warning"] and str(saved) in result["warning"]
    assert result["recoveredSaveBackupPaths"] == [str(saved)]
    assert result["savedBackupPath"] is None and result["removalPending"] is False


def test_reinstall_after_interrupted_uninstall_still_clears_the_old_quarantine(installation):
    remote, _, _, _, _ = installation
    previous = "e" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + previous)
    os.rename(remote.GAME, quarantine)
    saved.mkdir()
    (saved / remote.MARKER).write_text(json.dumps({"owner": remote.OWNER + "-save-backup"}))
    (saved / "config.toml").write_bytes(b"earlier settings")
    record_quarantine(remote, previous, quarantine, saved)
    remote.owned(remote.GAME)
    (remote.GAME / "halo").write_bytes(b"rebuilt native executable")
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert result["uninstalled"] is True and not result.get("alreadyAbsent", False)
    assert not quarantine.exists() and not remote.GAME.exists()
    assert str(saved) in result["warning"]


def test_quarantine_pattern_folders_without_a_valid_run_or_marker_are_kept(installation):
    remote, _, _, _, _ = installation
    games = remote.GAME.parent
    decoy = games / ".HaloCENativeVR-uninstall-not-a-run-id"
    decoy.mkdir()
    (decoy / "notes.txt").write_bytes(b"user data")
    unmarked = games / (".HaloCENativeVR-uninstall-" + "f" * 32)
    unmarked.mkdir()
    (unmarked / "stray.txt").write_bytes(b"not ours")
    forged = games / (".HaloCENativeVR-uninstall-" + "a" * 32)
    forged.mkdir()
    (forged / remote.MARKER).write_text(json.dumps({"owner": "someone-else"}))
    (forged / "precious.bin").write_bytes(b"user data")
    marker_dir = games / (".HaloCENativeVR-uninstall-" + "1" * 32)
    marker_dir.mkdir()
    (marker_dir / remote.MARKER).mkdir()
    (marker_dir / "note.txt").write_bytes(b"kept")
    result = remote.uninstall(RUN_ID)
    assert not result["uninstalled"] and result["removalPending"]
    assert "manually" in result["warning"]
    assert set(result["retainedQuarantinePaths"]) == {str(decoy), str(unmarked), str(forged), str(marker_dir)}
    assert (decoy / "notes.txt").read_bytes() == b"user data"
    assert (unmarked / "stray.txt").read_bytes() == b"not ours"
    assert (forged / "precious.bin").read_bytes() == b"user data"
    assert (marker_dir / "note.txt").read_bytes() == b"kept"


def test_unfinishable_leftover_is_named_and_skipped_instead_of_blocking(installation):
    remote, _, _, _, _ = installation
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + "2" * 32)
    quarantine.mkdir()
    (quarantine / remote.MARKER).write_text(json.dumps({"owner": remote.OWNER}))
    record_quarantine(remote, "2" * 32, quarantine)
    outside = remote.HOME / "foreign.map"
    outside.write_bytes(b"outside file")
    os.link(outside, quarantine / "linked.map")
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert not result["uninstalled"] and result["removalPending"]
    assert (quarantine / "linked.map").is_file() and outside.read_bytes() == b"outside file"
    assert str(quarantine) in result["warning"] and "manually" in result["warning"]


def test_many_leftovers_are_all_removed_with_a_bounded_warning(installation):
    remote, _, _, _, _ = installation
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + "3" * 32)
    os.rename(remote.GAME, quarantine)
    record_quarantine(remote, "3" * 32, quarantine)
    for index in range(40):
        folder = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + f"{index:032x}")
        folder.mkdir()
        (folder / remote.MARKER).write_text(json.dumps({"owner": remote.OWNER}))
        (folder / "halo").write_bytes(b"earlier binary")
        record_quarantine(remote, f"{index:032x}", folder)
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert result["uninstalled"] is True and result["alreadyAbsent"] is False
    assert not list((remote.GAME.parent).glob(".HaloCENativeVR-uninstall-*"))
    assert len(result["warning"]) <= remote.MAX_WARNING_CHARS and "additional notes omitted" in result["warning"]


def test_saves_note_requires_an_owned_backup_marker(installation):
    remote, _, _, _, _ = installation
    previous = "4" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + previous)
    os.rename(remote.GAME, quarantine)
    saved.mkdir()
    (saved / remote.MARKER).write_text(json.dumps({"owner": "someone-else"}))
    record_quarantine(remote, previous, quarantine)
    journal = remote.CACHE / "runs" / previous / remote.MARKER
    metadata = json.loads(journal.read_text())
    metadata["savedBackupPath"] = str(saved)
    journal.write_text(json.dumps(metadata))
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert not result["uninstalled"] and quarantine.exists() and result["removalPending"]
    assert str(quarantine) in result["warning"] and result["recoveredSaveBackupPaths"] == []


@pytest.mark.parametrize("same_run", [False, True])
@pytest.mark.parametrize("keep_saves", [False, True])
def test_retry_finishes_markerless_quarantine_after_root_removal_failure(
        installation, monkeypatch, same_run, keep_saves):
    remote, _, _, _, _ = installation
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + RUN_ID)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + RUN_ID)
    real_rmdir = Path.rmdir

    def fail_root(path, *args, **kwargs):
        if path == quarantine:
            raise OSError("root directory removal interrupted")
        return real_rmdir(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rmdir", fail_root)
        with pytest.raises(RuntimeError, match="Remaining native files"):
            remote.uninstall(RUN_ID, keep_saves=keep_saves)
    assert quarantine.is_dir() and not list(quarantine.iterdir())
    journal = json.loads((remote.CACHE / "runs" / RUN_ID / remote.MARKER).read_text())
    assert journal["quarantineRoot"] == remote.uninstall_root_identity(quarantine)
    before = {str(path.relative_to(saved)): path.read_bytes() for path in saved.rglob("*") if path.is_file()}
    result = remote.uninstall(RUN_ID if same_run else "d" * 32, keep_saves=keep_saves)
    assert result["uninstalled"] and not result["alreadyAbsent"] and not result["removalPending"]
    assert not quarantine.exists()
    assert {str(path.relative_to(saved)): path.read_bytes() for path in saved.rglob("*") if path.is_file()} == before
    assert result["recoveredSaveBackupPaths"] == ([str(saved)] if keep_saves else [])
    assert result["savedBackupPath"] == (str(saved) if keep_saves and same_run else None)


def test_quarantine_journal_precedes_the_rename_and_survives_that_crash_window(installation, monkeypatch):
    remote, _, _, _, _ = installation
    real_rename = remote.rename_noreplace
    seen = []

    def check(source, target):
        if source == remote.GAME:
            metadata = remote.private_json(remote.CACHE / "runs" / RUN_ID / remote.MARKER,
                                           remote.CACHE / "runs" / RUN_ID)
            assert metadata["state"] == "quarantining"
            assert metadata["quarantinePath"] == str(target)
            assert metadata["quarantineRoot"] == remote.uninstall_root_identity(source)
            seen.append(metadata)
        real_rename(source, target)

    monkeypatch.setattr(remote, "rename_noreplace", check)
    assert remote.uninstall(RUN_ID, keep_saves=True)["uninstalled"]
    assert len(seen) == 1
    # A process killed after rename but before the next journal update leaves
    # this exact state. It remains sufficient proof even without a game marker.
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + "d" * 32)
    quarantine.mkdir()
    (quarantine / "remaining.bin").write_bytes(b"native remainder")
    record = record_quarantine(remote, "d" * 32, quarantine)
    metadata = json.loads(record.read_text())
    metadata["state"] = "quarantining"
    record.write_text(json.dumps(metadata))
    assert remote.uninstall("e" * 32)["uninstalled"] and not quarantine.exists()


@pytest.mark.parametrize("damage", ["missing", "corrupt", "foreign-owner", "foreign-operation", "wrong-path",
                                  "complete", "oversize", "hardlink", "invalid-root", "foreign-marker"])
def test_unverified_quarantine_journals_are_reported_and_never_adopted(installation, damage):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    os.rename(remote.GAME, quarantine)
    record = record_quarantine(remote, previous, quarantine)
    metadata = json.loads(record.read_text())
    if damage == "missing":
        record.unlink()
    elif damage == "corrupt":
        record.write_text("{broken")
    elif damage == "oversize":
        record.write_bytes(b"x" * (remote.MAX_MANIFEST_BYTES + 1))
    elif damage == "hardlink":
        os.link(record, remote.HOME / "copied-journal.json")
    elif damage == "foreign-marker":
        (quarantine / remote.MARKER).write_text('{"owner":"another-application"}')
    else:
        key, value = {"foreign-owner": ("owner", "other"), "foreign-operation": ("operation", "install"),
                      "wrong-path": ("quarantinePath", str(remote.HOME / "unrelated")),
                      "complete": ("state", "complete"), "invalid-root": ("quarantineRoot", {"device": True})}[damage]
        metadata[key] = value
        record.write_text(json.dumps(metadata))
    before = {str(path.relative_to(quarantine)): path.read_bytes() for path in quarantine.rglob("*") if path.is_file()}
    result = remote.uninstall(RUN_ID)
    assert not result["uninstalled"] and not result["alreadyAbsent"] and result["removalPending"]
    assert result["retainedQuarantinePaths"] == [str(quarantine)] and str(quarantine) in result["warning"]
    assert {str(path.relative_to(quarantine)): path.read_bytes() for path in quarantine.rglob("*") if path.is_file()} == before


def test_copied_known_owner_marker_does_not_authorize_unrelated_folder_deletion(installation):
    remote, _, _, _, _ = installation
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + "d" * 32)
    quarantine.mkdir()
    (quarantine / remote.MARKER).write_bytes((remote.GAME / remote.MARKER).read_bytes())
    (quarantine / "precious.bin").write_bytes(b"user data")
    result = remote.uninstall(RUN_ID)
    assert result["removalPending"] and not result["uninstalled"]
    assert (quarantine / "precious.bin").read_bytes() == b"user data"
    assert str(quarantine) in result["warning"]


def test_replaced_quarantine_root_is_kept_even_if_the_old_marker_was_copied(installation):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    os.rename(remote.GAME, quarantine)
    record_quarantine(remote, previous, quarantine)
    intact = remote.GAME.parent / "original-quarantined-game"
    os.rename(quarantine, intact)
    quarantine.mkdir()
    (quarantine / remote.MARKER).write_bytes((intact / remote.MARKER).read_bytes())
    (quarantine / "precious.bin").write_bytes(b"replacement data")
    result = remote.uninstall(RUN_ID)
    assert result["removalPending"] and "identity" in result["warning"]
    assert (quarantine / "precious.bin").read_bytes() == b"replacement data"
    assert (intact / "halo").read_bytes() == b"damaged native executable"


def test_markerless_legacy_quarantine_is_named_and_kept_for_manual_review(installation):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    os.rename(remote.GAME, quarantine)
    record_quarantine(remote, previous, quarantine, legacy=True)
    (quarantine / remote.MARKER).unlink()
    result = remote.uninstall(RUN_ID)
    assert result["removalPending"] and "older uninstall" in result["warning"]
    assert (quarantine / "save/profile.sav").read_bytes() == b"campaign progress"


@pytest.mark.parametrize("damage", ["missing", "corrupt-marker", "oversize-marker", "foreign-marker",
                                  "hardlink", "changed-content", "empty", "symlink-root", "symlink-child"])
def test_unverifiable_save_backup_preserves_quarantine_and_all_backup_data(installation, damage):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + previous)
    os.rename(remote.GAME, quarantine)
    saved.mkdir()
    (saved / "campaign.sav").write_bytes(b"previous campaign")
    record_quarantine(remote, previous, quarantine, saved)
    marker = saved / remote.MARKER
    protected = None
    if damage == "missing":
        (saved / "campaign.sav").unlink()
        marker.unlink()
        saved.rmdir()
    elif damage == "corrupt-marker":
        marker.write_text("not-json")
    elif damage == "oversize-marker":
        marker.write_bytes(b"x" * (remote.MAX_MANIFEST_BYTES + 1))
    elif damage == "foreign-marker":
        marker.write_text('{"owner":"another-application"}')
    elif damage == "hardlink":
        protected = remote.HOME / "protected-campaign.sav"
        os.link(saved / "campaign.sav", protected)
    elif damage == "changed-content":
        (saved / "campaign.sav").write_bytes(b"modified campaign")
    elif damage == "empty":
        (saved / "campaign.sav").unlink()
    else:
        protected = remote.HOME / "protected-saves"
        protected.mkdir()
        (protected / "keep.sav").write_bytes(b"external campaign")
        if damage == "symlink-root":
            os.rename(saved, remote.GAME.parent / "actual-backup")
            link = saved
        else:
            link = saved / "linked"
        try:
            link.symlink_to(protected, target_is_directory=True)
        except OSError:
            pytest.skip("Windows symlink creation requires additional privileges.")
    before = {str(path): path.read_bytes() for path in saved.rglob("*") if path.is_file() and not path.is_symlink()}
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert not result["uninstalled"] and result["removalPending"] and quarantine.exists()
    assert result["recoveredSaveBackupPaths"] == []
    assert (quarantine / "save/profile.sav").read_bytes() == b"campaign progress"
    assert {str(path): path.read_bytes() for path in saved.rglob("*") if path.is_file() and not path.is_symlink()} == before
    if protected:
        assert (protected.read_bytes() if protected.is_file() else (protected / "keep.sav").read_bytes()) in (
            b"previous campaign", b"external campaign")


def test_same_device_bind_mount_in_a_quarantine_is_kept(installation, monkeypatch):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    os.rename(remote.GAME, quarantine)
    record_quarantine(remote, previous, quarantine)
    monkeypatch.setattr(remote, "uninstall_mounts", lambda: [quarantine / "maps"])
    result = remote.uninstall(RUN_ID)
    assert result["removalPending"] and "mount" in result["warning"]
    assert (quarantine / "maps/a10.map").read_bytes() == b"damaged or incomplete Xbox maps"


def test_recovery_and_verified_saves_are_reported_when_steam_removal_is_pending(installation, monkeypatch):
    remote, steam, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    saved = remote.GAME.parent / ("HaloCENativeVR-saves-" + previous)
    os.rename(remote.GAME, quarantine)
    saved.mkdir()
    (saved / "campaign.sav").write_bytes(b"earlier campaign")
    record_quarantine(remote, previous, quarantine, saved)
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    result = remote.uninstall(RUN_ID)
    assert not result["uninstalled"] and result["steam"]["status"] == "manual"
    assert not quarantine.exists() and str(quarantine) in result["warning"]
    assert result["savedBackupPath"] is None and result["recoveredSaveBackupPaths"] == [str(saved)]
    assert (saved / "campaign.sav").read_bytes() == b"earlier campaign"


def test_recovery_has_bounded_work_and_can_continue_on_another_run(installation, monkeypatch):
    remote, _, _, _, _ = installation
    previous = "d" * 32
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + previous)
    os.rename(remote.GAME, quarantine)
    record_quarantine(remote, previous, quarantine)
    monkeypatch.setattr(remote, "MAX_UNINSTALL_RECOVERIES", 4)
    for index in range(5):
        identifier = f"{index:032x}"
        path = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + identifier)
        path.mkdir()
        (path / "remaining.bin").write_bytes(b"verified remainder")
        record_quarantine(remote, identifier, path)
    result = remote.uninstall(RUN_ID)
    assert not result["uninstalled"] and result["removalPending"] and not result["alreadyAbsent"]
    assert len(list(remote.GAME.parent.glob(".HaloCENativeVR-uninstall-*"))) == 2
    assert "one operation" in result["warning"] and len(result["warning"]) <= remote.MAX_WARNING_CHARS
    assert remote.uninstall("e" * 32)["uninstalled"]
    assert not list(remote.GAME.parent.glob(".HaloCENativeVR-uninstall-*"))


@pytest.mark.skipif(os.name == "nt", reason="Windows forbids these Unix filename characters.")
@pytest.mark.parametrize("suffix", ["bad\nname", "bad\\name", "bad\x7fname"])
def test_unreportable_quarantine_filenames_stay_pending_without_unsafe_path_fields(installation, suffix):
    remote, _, _, _, _ = installation
    quarantine = remote.GAME.parent / (".HaloCENativeVR-uninstall-" + suffix)
    quarantine.mkdir()
    (quarantine / "precious.bin").write_bytes(b"user data")
    result = remote.uninstall(RUN_ID)
    assert result["removalPending"] and not result["uninstalled"]
    assert result["retainedQuarantinePaths"] == []
    assert (quarantine / "precious.bin").read_bytes() == b"user data"
    assert ascii(quarantine.name) in result["warning"]


def test_absent_games_parent_needs_no_creation_or_cleanup(installation):
    remote, _, _, _, _ = installation
    protected = remote.HOME / "original-games"
    os.rename(remote.GAME.parent, protected)
    result = remote.uninstall(RUN_ID)
    assert result["uninstalled"] and result["alreadyAbsent"] and not result["removalPending"]
    assert not remote.GAME.parent.exists()
    assert (protected / "HaloCEVR/halo.exe").read_bytes() == b"old PC version; this operation must not delete it"


def test_failure_before_first_delete_restores_the_intact_game_folder(installation, monkeypatch):
    remote, _, _, _, _ = installation
    before = game_bytes(remote)
    original_unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path.parent.name == ".HaloCENativeVR-uninstall-" + RUN_ID:
            raise OSError("first deletion failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(OSError, match="first deletion"):
        remote.uninstall(RUN_ID)
    assert game_bytes(remote) == before
    assert not (remote.GAME.parent / (".HaloCENativeVR-uninstall-" + RUN_ID)).exists()


def test_second_steam_account_write_failure_restores_first_account_and_game(installation, monkeypatch):
    remote, steam, configs, _, _ = installation
    game_before = game_bytes(remote)
    raw = [(config / "shortcuts.vdf").read_bytes() for config in configs]
    real = steam._replace_shortcut_bytes
    calls = [0]

    def replace(path, content):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("second account write failed")
        return real(path, content)

    monkeypatch.setattr(steam, "_replace_shortcut_bytes", replace)
    result = remote.uninstall(RUN_ID, keep_saves=True)
    assert not result["uninstalled"] and result["steam"]["status"] == "manual"
    assert game_bytes(remote) == game_before
    assert [(config / "shortcuts.vdf").read_bytes() for config in configs] == raw
    assert not list((remote.HOME / "Games").glob("*HaloCENativeVR-saves-*"))


def test_legacy_close_flag_leaves_active_steam_and_game_running(installation, monkeypatch):
    import subprocess
    remote, steam, _, _, _ = installation
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    session, removal = Mock(), Mock()
    monkeypatch.setattr(steam, "_session_environment", session)
    monkeypatch.setattr(steam, "_write_removed_shortcuts", removal)
    shutdown, restart = Mock(), Mock()
    monkeypatch.setattr(subprocess, "run", shutdown)
    monkeypatch.setattr(subprocess, "Popen", restart)
    assert steam.remove_native_shortcut(remote.HOME, remote.GAME, close_steam=True)["status"] == "manual"
    shutdown.assert_not_called()
    restart.assert_not_called()
    session.assert_not_called()
    removal.assert_not_called()
    assert remote.GAME.exists()


def test_uninstall_preflight_needs_no_game_maps_space_vr_or_compiler(installation, monkeypatch):
    remote, _, _, _, _ = installation
    def forbidden(*args, **kwargs):
        raise AssertionError("Install-only prerequisite was used")
    monkeypatch.setattr(remote, "existing_install", forbidden)
    monkeypatch.setattr(remote, "elf_arm64", forbidden)
    monkeypatch.setattr(remote.shutil, "disk_usage", forbidden)
    monkeypatch.setattr(remote.shutil, "which", forbidden)
    monkeypatch.setattr(remote, "command", forbidden)
    result = remote.preflight_uninstall()
    assert result == {"home": str(remote.HOME), "cachePath": str(remote.CACHE),
                      "gamePath": str(remote.GAME), "uninstallSupported": True}


@pytest.mark.parametrize("failure", ["space", "config"])
def test_save_backup_prerequisite_failure_keeps_game_and_steam_untouched(installation, monkeypatch, failure):
    remote, _, configs, _, _ = installation
    if failure == "space":
        monkeypatch.setattr(remote.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=0))
    else:
        (remote.GAME / "config.toml").write_text("[not valid toml")
    before = game_bytes(remote)
    raw = [(config / "shortcuts.vdf").read_bytes() for config in configs]
    with pytest.raises(ValueError, match="space|damaged"):
        remote.uninstall(RUN_ID, keep_saves=True)
    assert game_bytes(remote) == before
    assert [(config / "shortcuts.vdf").read_bytes() for config in configs] == raw


def test_completed_removal_is_not_reported_as_failed_if_operation_bookkeeping_fails(installation, monkeypatch):
    remote, _, _, _, _ = installation
    real_write = remote.write_uninstall_record

    def write(directory, metadata, *args, **kwargs):
        if directory.name == RUN_ID and metadata.get("state") == "complete":
            raise OSError("operation record update failed")
        return real_write(directory, metadata, *args, **kwargs)

    monkeypatch.setattr(remote, "write_uninstall_record", write)
    result = remote.uninstall(RUN_ID)
    assert result["uninstalled"] is True and not remote.GAME.exists()
    assert "operation record" in result["warning"]
