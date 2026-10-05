"""Artwork registration must preserve custom images and unrelated accounts."""
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


@pytest.fixture
def steam(monkeypatch):
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
    assert struct.unpack(">II", wide[16:24]) == (920, 430)
    assert struct.unpack(">II", thumbnail[16:24]) == (180, 270)


def test_new_shortcut_gets_box_art_in_only_active_account(steam, tmp_path):
    home, active, directory = make_steam_home(tmp_path)
    result = steam.add_native_shortcut(home, home / "Games/HaloCENativeVR")
    appid = result["appid"]
    assert result["status"] == "added"
    assert result["artwork"]["status"] == "added"
    assert (active / "grid" / f"{appid}p.jpg").read_bytes() == (RESOURCES / "artwork/halo-ce-cover.jpg").read_bytes()
    assert (active / "grid" / f"{appid}.png").read_bytes() == (RESOURCES / "artwork/halo-ce-landscape.png").read_bytes()
    assert not (directory / "userdata/10/config/grid").exists()
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
    assert sorted(path.name for path in (active / "grid").iterdir()) == [f"{appid}.png", f"{appid}p.jpg"]


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
    contents = {f"{appid}p.png": b"user portrait", f"{appid}.jpeg": b"user landscape", "10p.png": b"other game"}
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
    assert result["installed"] == ["3732925724.png"]
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
