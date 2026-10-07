"""Artwork registration must preserve custom images and unrelated accounts."""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


@pytest.fixture
def steam(monkeypatch):
    storage_spec = importlib.util.spec_from_file_location("frame_storage", RESOURCES / "frame_storage.py")
    storage = importlib.util.module_from_spec(storage_spec)
    monkeypatch.setitem(sys.modules, storage_spec.name, storage)
    storage_spec.loader.exec_module(storage)
    spec = importlib.util.spec_from_file_location("steam_artwork_test", RESOURCES / "steam_shortcut.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "steam_running", lambda: False)
    return module


def make_steam_home(tmp_path):
    home = tmp_path / "home"
    steam = home / ".local/share/Steam"
    (steam / "config").mkdir(parents=True)
    (steam / "userdata/10/config").mkdir(parents=True)
    active = steam / "userdata/20/config"
    active.mkdir(parents=True)
    (steam / "config/loginusers.vdf").write_text(
        '"users" { "76561197960265738" { "MostRecent" "0" } '
        '"76561197960265748" { "MostRecent" "1" } }')
    return home, active, steam


def test_bundled_artwork_integrity_and_png_dimensions(steam):
    for _, _, name, expected in steam.ARTWORK:
        assert hashlib.sha256((RESOURCES / "artwork" / name).read_bytes()).hexdigest() == expected
    import struct
    wide = (RESOURCES / "artwork/halo-ce-landscape.png").read_bytes()
    thumbnail = (RESOURCES / "artwork/halo-ce-thumbnail.png").read_bytes()
    logo = (RESOURCES / "artwork/halo-ce-logo.png").read_bytes()
    icon = (RESOURCES / "artwork" / steam.ICON_NAME).read_bytes()
    assert struct.unpack(">II", wide[16:24]) == (920, 430)
    assert struct.unpack(">II", thumbnail[16:24]) == (180, 270)
    assert struct.unpack(">II", logo[16:24]) == (1000, 431)
    assert logo[25] == 6  # RGBA, preserving the logo's transparent background.
    assert struct.unpack(">II", icon[16:24]) == (256, 256)
    assert hashlib.sha256(icon).hexdigest() == steam.ICON_SHA256
    assert steam.ARTWORK_TYPES == {"p": 0, "_hero": 1, "_logo": 2, "": 3}


def test_new_shortcut_gets_box_art_in_only_active_account(steam, tmp_path):
    home, active, directory = make_steam_home(tmp_path)
    result = steam.add_native_shortcut(home, home / "Games/HaloCENativeVR")
    appid = result["appid"]
    assert result["status"] == "added"
    assert result["artwork"]["status"] == "added"
    assert (active / "grid" / f"{appid}p.jpg").read_bytes() == (RESOURCES / "artwork/halo-ce-cover.jpg").read_bytes()
    assert (active / "grid" / f"{appid}.png").read_bytes() == (RESOURCES / "artwork/halo-ce-landscape.png").read_bytes()
    assert not (directory / "userdata/10/config/grid").exists()
    assert (active / "grid" / f"{appid}_hero.jpg").read_bytes() == (RESOURCES / "artwork/halo-ce-hero.jpg").read_bytes()
    assert (active / "grid" / f"{appid}_logo.png").read_bytes() == (RESOURCES / "artwork/halo-ce-logo.png").read_bytes()
    assert steam.loads((active / "shortcuts.vdf").read_bytes())["shortcuts"].value["0"].value["appid"].value == appid


def test_retry_fills_missing_art_for_unchanged_existing_shortcut(steam, tmp_path):
    home, active, _ = make_steam_home(tmp_path)
    game = home / "Games/HaloCENativeVR"
    raw, appid = steam.update_shortcut(None, str(game / "halo"), str(game))
    (active / "shortcuts.vdf").write_bytes(raw)
    result = steam.add_native_shortcut(home, game)
    assert result["unchanged"] and result["appid"] == appid
    assert result["artwork"]["status"] == "added"
    assert (active / "shortcuts.vdf").read_bytes() == raw
    again = steam.add_native_shortcut(home, game)
    assert again["artwork"]["status"] == "unchanged"
    assert sorted(path.name for path in (active / "grid").iterdir()) == sorted(
        str(appid) + suffix + extension for suffix, extension, _, _ in steam.ARTWORK)


def test_existing_unsigned_shortcut_id_is_used_even_if_crc_differs(steam, tmp_path):
    home, active, _ = make_steam_home(tmp_path)
    game = home / "Games/HaloCENativeVR"
    raw, original = steam.update_shortcut(None, str(game / "halo"), str(game))
    root = steam.loads(raw)
    selected = 0xF1234567
    assert selected != original
    root["shortcuts"].value["0"].value["appid"].value = selected
    (active / "shortcuts.vdf").write_bytes(steam.dumps(root))
    result = steam.add_native_shortcut(home, game)
    assert result["appid"] == selected
    assert (active / "grid" / f"{selected}p.jpg").is_file()
    assert not (active / "grid" / f"{original}p.jpg").exists()


def test_custom_art_with_other_extensions_and_other_games_is_kept(steam, tmp_path):
    config = tmp_path / "config"
    grid = config / "grid"
    grid.mkdir(parents=True)
    appid = 3732925724
    contents = {str(appid) + suffix + ".jpeg": b"custom " + suffix.encode() for suffix, _, _, _ in steam.ARTWORK}
    contents["10p.png"] = b"other game"
    for name, content in contents.items():
        (grid / name).write_bytes(content)
    result = steam.install_artwork(config, appid)
    assert result["status"] == "preserved"
    assert result["installed"] == []
    assert {path.name: path.read_bytes() for path in grid.iterdir()} == contents


def test_custom_portrait_is_kept_and_missing_wide_tile_is_added(steam, tmp_path):
    config = tmp_path / "config"
    grid = config / "grid"
    grid.mkdir(parents=True)
    (grid / "3732925724p.jpg").write_bytes(b"custom portrait")
    result = steam.install_artwork(config, 3732925724)
    assert result["installed"] == ["3732925724" + suffix + extension for suffix, extension, _, _ in steam.ARTWORK if suffix != "p"]
    assert result["preserved"] == ["3732925724p.jpg"]
    assert (grid / "3732925724p.jpg").read_bytes() == b"custom portrait"


def test_corrupt_bundle_adds_no_art_but_reports_shortcut_separately(steam, tmp_path, monkeypatch):
    home, active, _ = make_steam_home(tmp_path)
    real = steam.install_artwork
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "halo-ce-cover.jpg").write_bytes(b"bad")
    monkeypatch.setattr(steam, "install_artwork", lambda config, appid: real(config, appid, broken))
    result = steam.add_native_shortcut(home, home / "Games/HaloCENativeVR")
    assert result["status"] == "added" and (active / "shortcuts.vdf").is_file()
    assert result["artwork"]["status"] == "manual"
    assert "integrity" in result["artwork"]["reason"]
    assert not (active / "grid").exists()


def test_second_publication_failure_rolls_back_only_new_art(steam, tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    real_link = os.link
    count = 0

    def link(source, destination):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated filesystem failure")
        real_link(source, destination)

    monkeypatch.setattr(steam.os, "link", link)
    with pytest.raises(OSError, match="simulated"):
        steam.install_artwork(config, 3732925724)
    assert list((config / "grid").iterdir()) == []


def test_concurrent_custom_art_is_preserved_and_first_new_file_rolled_back(steam, tmp_path, monkeypatch):
    config = tmp_path / "config"
    grid = config / "grid"
    grid.mkdir(parents=True)
    real_link = os.link

    def link(source, destination):
        real_link(source, destination)
        (grid / "3732925724.jpeg").write_bytes(b"new user art")

    monkeypatch.setattr(steam.os, "link", link)
    with pytest.raises(ValueError, match="changed during"):
        steam.install_artwork(config, 3732925724)
    assert {path.name: path.read_bytes() for path in grid.iterdir()} == {"3732925724.jpeg": b"new user art"}


def test_artwork_is_left_untouched_if_steam_reopens(steam, tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    states = iter([False, False, True])
    monkeypatch.setattr(steam, "steam_running", lambda: next(states))
    with pytest.raises(ValueError, match="reopened"):
        steam.install_artwork(config, 3732925724)
    assert list((config / "grid").iterdir()) == []


def test_symlink_artwork_folder_is_rejected_without_touching_target(steam, tmp_path):
    config = tmp_path / "config"
    outside = tmp_path / "outside"
    config.mkdir()
    outside.mkdir()
    try:
        (config / "grid").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links requires Windows privileges.")
    with pytest.raises(ValueError, match="ordinary directory"):
        steam.install_artwork(config, 3732925724)
    assert list(outside.iterdir()) == []


def test_hardlinked_custom_art_is_rejected_before_writing_other_tile(steam, tmp_path):
    config = tmp_path / "config"
    grid = config / "grid"
    grid.mkdir(parents=True)
    foreign = tmp_path / "foreign.jpg"
    foreign.write_bytes(b"keep")
    os.link(foreign, grid / "3732925724p.jpg")
    with pytest.raises(ValueError, match="hard-linked"):
        steam.install_artwork(config, 3732925724)
    assert foreign.read_bytes() == b"keep"
    assert sorted(path.name for path in grid.iterdir()) == ["3732925724p.jpg"]


def owned_game(tmp_path):
    game = tmp_path / "Games/HaloCENativeVR"
    game.mkdir(parents=True)
    program = bytearray(64)
    program[:6] = b"\x7fELF\x02\x01"
    program[18:20] = (183).to_bytes(2, "little")
    (game / "halo").write_bytes(program)
    (game / ".halo-frame-installer.json").write_text(json.dumps({
        "owner": "halo-frame-installer", "sourceCommit": "2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4",
        "files": {"halo": hashlib.sha256(program).hexdigest()}}))
    return game


def test_sd_closed_shortcut_keeps_internal_entry_and_uses_home_grid(steam, tmp_path, monkeypatch):
    home, active, _ = make_steam_home(tmp_path)
    internal_game = owned_game(home)
    mount = tmp_path / "media" / "Halo SD Ω"
    game = owned_game(mount)
    storage = sys.modules["frame_storage"]
    internal = storage.discover_storage(home)["destinations"][0]
    descriptor = {"id": "sd:" + "c" * 32, "kind": "sd", "mountPath": str(mount),
                  "gamePath": str(game)}
    monkeypatch.setattr(storage, "discover_storage", lambda home=home: {
        "home": str(home), "destinations": [internal, descriptor]})
    raw, internal_id = steam.update_shortcut(None, str(internal_game / "halo"), str(internal_game))
    path = active / "shortcuts.vdf"
    path.write_bytes(raw)
    result = steam.add_native_shortcut(home, game)
    assert result["status"] == "added" and result["name"] == steam.SD_NAME
    assert result["appid"] != internal_id
    records = steam.loads(path.read_bytes())["shortcuts"].value
    assert records["0"] == steam.loads(raw)["shortcuts"].value["0"]
    assert records["1"].value["AppName"].value == steam.SD_NAME
    assert records["1"].value["Exe"].value == '"' + str(game / "halo") + '"'
    assert records["1"].value["StartDir"].value == '"' + str(game) + '"'
    assert records["1"].value["icon"].value == str(game / ".installer-artwork" / steam.ICON_NAME)
    assert (active / "grid" / (str(result["appid"]) + "p.jpg")).is_file()
    assert not (mount / ".local").exists()
    removed = steam.remove_native_shortcut(home, game)
    assert removed["status"] == "removed" and path.read_bytes() == raw
    assert not (active / "grid" / (str(result["appid"]) + "p.jpg")).exists()


def test_closed_shortcut_rejects_unapproved_display_title(steam, tmp_path):
    game = owned_game(tmp_path)
    with pytest.raises(ValueError, match="name is unsupported"):
        steam.update_shortcut(None, str(game / "halo"), str(game), "Another game")


def test_sd_closed_retry_preserves_user_flags_and_internal_entry(steam, tmp_path, monkeypatch):
    home, active, _ = make_steam_home(tmp_path)
    internal_game = owned_game(home)
    mount = tmp_path / "media" / "Halo SD Ω"
    game = owned_game(mount)
    storage = sys.modules["frame_storage"]
    internal = storage.discover_storage(home)["destinations"][0]
    card = {"id": "sd:" + "c" * 32, "kind": "sd", "mountPath": str(mount), "gamePath": str(game)}
    monkeypatch.setattr(storage, "discover_storage", lambda home=home: {
        "home": str(home), "destinations": [internal, card]})
    raw, internal_id = steam.update_shortcut(None, str(internal_game / "halo"), str(internal_game))
    path = active / "shortcuts.vdf"
    path.write_bytes(raw)
    first = steam.add_native_shortcut(home, game)
    root = steam.loads(path.read_bytes())
    fields = root["shortcuts"].value["1"].value
    del fields["IsHidden"]
    fields["ishidden"] = steam.Value(2, 1)
    choices = {"AllowDesktopConfig": 0, "AllowOverlay": 0, "Devkit": 1, "DevkitOverrideAppID": 480}
    for key, value in choices.items():
        fields[key] = steam.Value(2, value)
    fields["OpenVR"] = steam.Value(2, 0)
    path.write_bytes(steam.dumps(root))

    retry = steam.add_native_shortcut(home, game)
    stable = path.read_bytes()
    after = steam.loads(stable)["shortcuts"].value
    assert retry["appid"] == first["appid"] != internal_id
    assert after["0"] == steam.loads(raw)["shortcuts"].value["0"]
    fields = after["1"].value
    assert fields["ishidden"].value == 1 and "IsHidden" not in fields
    assert all(fields[key].value == value for key, value in choices.items())
    assert fields["OpenVR"].value == 1 and fields["AppName"].value == steam.SD_NAME
    assert steam.add_native_shortcut(home, game)["unchanged"]
    assert path.read_bytes() == stable


def test_closed_shortcut_icon_uses_persistent_owned_sidecar(steam, tmp_path):
    game = owned_game(tmp_path)
    raw, appid = steam.update_shortcut(None, str(game / "halo"), str(game))
    updated, result = steam._closed_shortcut_icon(raw, game, appid)
    target = game / ".installer-artwork" / steam.ICON_NAME
    assert result == {"status": "added", "path": str(target)}
    assert target.read_bytes() == (RESOURCES / "artwork" / steam.ICON_NAME).read_bytes()
    _, _, selected = steam._shortcut_icon_field(updated, appid, str(game / "halo"))
    assert selected == str(target)
    unchanged, retry = steam._closed_shortcut_icon(updated, game, appid)
    assert unchanged == updated and retry["status"] == "unchanged"


def test_closed_shortcut_custom_icon_path_is_preserved_without_sidecar(steam, tmp_path):
    game = owned_game(tmp_path)
    raw, appid = steam.update_shortcut(None, str(game / "halo"), str(game))
    root = steam.loads(raw)
    root["shortcuts"].value["0"].value["icon"] = steam.Value(1, "/custom/chief.png")
    custom = steam.dumps(root)
    unchanged, result = steam._closed_shortcut_icon(custom, game, appid)
    assert unchanged == custom and result["status"] == "preserved"
    assert not (game / ".installer-artwork").exists()


def test_changed_managed_icon_is_kept_in_both_empty_and_selected_shortcut(steam, tmp_path):
    game = owned_game(tmp_path)
    raw, appid = steam.update_shortcut(None, str(game / "halo"), str(game))
    updated, result = steam._closed_shortcut_icon(raw, game, appid)
    icon = Path(result["path"])
    icon.write_bytes(b"my custom Chief icon")
    for content in (raw, updated):
        unchanged, retry = steam._closed_shortcut_icon(content, game, appid)
        assert unchanged == content and retry["status"] == "preserved"
    assert icon.read_bytes() == b"my custom Chief icon"


def test_icon_publication_requires_installer_owned_game(steam, tmp_path):
    game = owned_game(tmp_path)
    (game / ".halo-frame-installer.json").write_text('{"owner":"another-application"}')
    with pytest.raises(ValueError, match="ownership"):
        steam._publish_shortcut_icon(game)
    assert not (game / ".installer-artwork").exists()


def test_icon_source_integrity_failure_does_not_create_sidecar(steam, tmp_path):
    game = owned_game(tmp_path)
    broken = tmp_path / "artwork"
    broken.mkdir()
    (broken / steam.ICON_NAME).write_bytes(b"changed bundle")
    with pytest.raises(ValueError, match="integrity"):
        steam._publish_shortcut_icon(game, broken)
    assert not (game / ".installer-artwork").exists()


def test_later_corrupt_logo_prevents_all_artwork_writes(steam, tmp_path):
    sources = tmp_path / "artwork"
    sources.mkdir()
    for _, _, name, _ in steam.ARTWORK:
        (sources / name).write_bytes((RESOURCES / "artwork" / name).read_bytes())
    (sources / "halo-ce-logo.png").write_bytes(b"corrupted last category")
    config = tmp_path / "config"
    config.mkdir()
    with pytest.raises(ValueError, match="integrity"):
        steam.install_artwork(config, 3000000001, sources)
    assert not (config / "grid").exists()


def test_corrupt_optional_icon_prevents_any_artwork_publication(steam, tmp_path):
    source = tmp_path / "corrupt-icon"
    source.mkdir()
    for _, _, filename, _ in steam.ARTWORK:
        (source / filename).write_bytes((RESOURCES / "artwork" / filename).read_bytes())
    (source / steam.ICON_NAME).write_bytes(b"corrupted optional icon")
    config = tmp_path / "config"
    config.mkdir()
    with pytest.raises(ValueError, match="icon.*integrity"):
        steam.install_artwork(config, 3000000001, source)
    assert not (config / "grid").exists()


def test_original_guided_native_install_gets_icon_without_marker_adoption(steam, tmp_path):
    game = owned_game(tmp_path)
    metadata = json.loads((game / ".halo-frame-installer.json").read_text())
    (game / ".halo-frame-installer.json").unlink()
    marker = game / ".codex-halo-native-install.json"
    metadata["owner"] = "codex-halo-native-frame-20261005"
    metadata["build"] = {"sourceCommit": metadata.pop("sourceCommit")}
    before = json.dumps(metadata).encode()
    marker.write_bytes(before)
    program_before = (game / "halo").read_bytes()
    result = steam._publish_shortcut_icon(game)
    assert result["status"] == "added"
    assert marker.read_bytes() == before and not (game / ".halo-frame-installer.json").exists()
    assert (game / "halo").read_bytes() == program_before
    assert hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest() == steam.ICON_SHA256


@pytest.mark.parametrize("change", ["source", "program", "architecture"])
def test_icon_sidecar_needs_pinned_source_and_verified_native_identity(steam, tmp_path, change):
    game = owned_game(tmp_path)
    marker = game / ".halo-frame-installer.json"
    metadata = json.loads(marker.read_text())
    if change == "source":
        metadata["sourceCommit"] = "f" * 40
    else:
        program = bytearray((game / "halo").read_bytes())
        program[18:20] = (62).to_bytes(2, "little") if change == "architecture" else program[18:20]
        program.extend(b"modified")
        (game / "halo").write_bytes(program)
        if change == "architecture":
            metadata["files"]["halo"] = hashlib.sha256(program).hexdigest()
    marker.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="verified|revision"):
        steam._publish_shortcut_icon(game)
    assert not (game / ".installer-artwork").exists()
