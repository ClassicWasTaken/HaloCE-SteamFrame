"""Library registration must not manage Steam Frame's headset session."""

import importlib.util
import os
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from unittest.mock import Mock

import pytest


RESOURCES = Path(__file__).resolve().parents[1] / "resources"


@pytest.fixture
def steam(monkeypatch):
    spec = importlib.util.spec_from_file_location("steam_session_safety", RESOURCES / "steam_shortcut.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError("A library operation tried to control the headset session")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(module.os, "system", forbidden)
    monkeypatch.setattr(module.os, "kill", forbidden)
    monkeypatch.setattr(module.os, "killpg", forbidden, raising=False)
    monkeypatch.setattr(module, "_session_environment", forbidden)
    return module


@pytest.mark.parametrize("operation", ["add", "remove"])
@pytest.mark.parametrize("legacy_close_flag", [False, True])
def test_active_steam_is_a_manual_result_with_zero_filesystem_or_process_changes(
        steam, tmp_path, monkeypatch, operation, legacy_close_flag):
    config = tmp_path / ".local/share/Steam/userdata/10/config"
    config.mkdir(parents=True)
    path = config / "shortcuts.vdf"
    raw = b"Existing library bytes must stay unchanged"
    path.write_bytes(raw)
    grid = config / "grid"
    grid.mkdir()
    (grid / "custom.jpg").write_bytes(b"custom artwork")
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    monkeypatch.setattr(steam, "_live_native", Mock(side_effect=RuntimeError("No verified live context")))
    writer = Mock(side_effect=AssertionError("The live library writer was invoked"))
    monkeypatch.setattr(steam, "_write_native_shortcut" if operation == "add" else "_write_removed_shortcuts", writer)
    action = steam.add_native_shortcut if operation == "add" else steam.remove_native_shortcut
    result = action(tmp_path, tmp_path / "Games/HaloCENativeVR", close_steam=legacy_close_flag)
    assert result["status"] == "manual"
    assert "running" in result["reason"]
    assert not any(word in result["instructions"].lower() for word in ("quit", "shutdown", "restart"))
    assert path.read_bytes() == raw and (grid / "custom.jpg").read_bytes() == b"custom artwork"
    assert sorted(child.name for child in config.iterdir()) == ["grid", "shortcuts.vdf"]
    writer.assert_not_called()


@pytest.mark.parametrize("operation", ["add", "remove"])
@pytest.mark.parametrize("legacy_close_flag", [False, True])
def test_active_steam_uses_client_api_and_never_invokes_file_writer(
        steam, tmp_path, monkeypatch, operation, legacy_close_flag):
    monkeypatch.setattr(steam, "steam_running", lambda: True)
    live_result = {"status": "added" if operation == "add" else "removed", "transport": "live-client"}
    client = Mock(return_value=live_result)
    monkeypatch.setattr(steam, "_live_native", client)
    writer = Mock(side_effect=AssertionError("A live library file writer was invoked"))
    monkeypatch.setattr(steam, "_write_native_shortcut" if operation == "add" else "_write_removed_shortcuts", writer)
    game = tmp_path / "Games/HaloCENativeVR"
    action = steam.add_native_shortcut if operation == "add" else steam.remove_native_shortcut
    assert action(tmp_path, game, close_steam=legacy_close_flag) == live_result
    client.assert_called_once_with(tmp_path, game, operation)
    writer.assert_not_called()


@pytest.mark.parametrize("legacy_close_flag", [False, True])
def test_already_closed_steam_keeps_atomic_add_and_remove_with_foreign_data_preserved(
        steam, tmp_path, monkeypatch, legacy_close_flag):
    monkeypatch.setattr(steam, "steam_running", lambda: False)
    config = tmp_path / ".local/share/Steam/userdata/10/config"
    config.mkdir(parents=True)
    game = tmp_path / "Games/HaloCENativeVR"
    foreign = OrderedDict([("appid", steam.Value(2, 0x80000001)),
                           ("AppName", steam.Value(1, "Other game")),
                           ("Exe", steam.Value(1, '"/unrelated/game"')),
                           ("unknown", steam.Value(7, b"FOREIGN!"))])
    before = steam.dumps(OrderedDict([("shortcuts", steam.Value(0, OrderedDict([
        ("0", steam.Value(0, foreign))])))]))
    path = config / "shortcuts.vdf"
    path.write_bytes(before)
    added = steam.add_native_shortcut(tmp_path, game, close_steam=legacy_close_flag)
    assert added["status"] == "added"
    assert steam.loads(path.read_bytes())["shortcuts"].value["0"].value == foreign
    assert (config / "grid" / f"{added['appid']}p.jpg").is_file()
    removed = steam.remove_native_shortcut(tmp_path, game, close_steam=legacy_close_flag)
    assert removed["status"] == "removed"
    assert path.read_bytes() == before
    assert list((config / "grid").iterdir()) == []
    assert len(list(config.glob("shortcuts.vdf.halo-frame-*.bak"))) == 2


def test_steam_client_with_another_uid_still_blocks_on_disk_edits(steam, tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    client = proc / "123"
    client.mkdir(parents=True)
    (client / "comm").write_text("steam\n")
    monkeypatch.setattr(steam.os, "readlink", lambda path: "/some-user/Steam/steam")
    actual_uid = client.stat().st_uid
    monkeypatch.setattr(steam.os, "getuid", lambda: actual_uid + 1, raising=False)
    assert steam.steam_running(proc)


def test_foreign_steam_with_unreadable_executable_still_blocks_file_edits(steam, tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    client = proc / "456"
    client.mkdir(parents=True)
    (client / "comm").write_text("steam\n")
    readlink = Mock(side_effect=PermissionError("Foreign process executable is private"))
    monkeypatch.setattr(steam.os, "readlink", readlink)
    assert steam.steam_running(proc)
    readlink.assert_not_called()


def test_artwork_manual_instructions_do_not_request_session_shutdown(steam, tmp_path, monkeypatch):
    def corrupt(*args, **kwargs):
        raise ValueError("Bundled artwork failed verification")
    monkeypatch.setattr(steam, "install_artwork", corrupt)
    result = steam._artwork_result(tmp_path, 0x80000001)
    assert result["status"] == "manual"
    assert "custom artwork" in result["instructions"]
    assert not any(word in result["instructions"].lower() for word in ("quit", "shutdown", "restart"))
