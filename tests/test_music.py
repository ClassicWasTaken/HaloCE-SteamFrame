"""Synthetic cache/audio tests; no Halo recordings or game data are fixtures."""
from pathlib import Path
import io
import struct
import sys
import threading
import time
import types
from unittest.mock import Mock
import wave
import zlib

import pytest

from halo_frame_installer import music


TAG = 2048
TABLE = TAG + 36
METADATA = 2304
PITCH = 2560
PERMUTATIONS = 2816
RAW = 4096
MAGIC = 0x40440000 - TABLE


def xbox_cache(channels=1, compressed=False):
    """Construct the few retail-layout structures the music reader consumes."""
    cache = bytearray(8192)
    cache[:4] = b"daeh"
    struct.pack_into("<II", cache, 4, 5, len(cache))
    struct.pack_into("<II", cache, 16, TAG, 2048)
    cache[32:34] = b"ui"
    build = b"01.10.12.2276"
    cache[64:64 + len(build)] = build
    cache[2044:2048] = b"toof"
    struct.pack_into("<9I", cache, TAG, MAGIC + TABLE, 0, 0, 1, 0, 0, 0, 0, 0x74616773)
    name = 2160
    tag_name = b"sound\\music\\title1\\loops\0"
    cache[name:name + len(tag_name)] = tag_name
    struct.pack_into("<8I", cache, TABLE, 0x736E6421, 0, 0, 0,
                     MAGIC + name, MAGIC + METADATA, 0, 0)
    struct.pack_into("<h", cache, METADATA + 6, 0)
    struct.pack_into("<hh", cache, METADATA + 108, channels - 1, 1)
    struct.pack_into("<3I", cache, METADATA + 152, 1, MAGIC + PITCH, 0)
    struct.pack_into("<h", cache, PITCH + 44, 1)
    struct.pack_into("<3I", cache, PITCH + 60, 2, MAGIC + PERMUTATIONS, 0)
    for index, following in ((0, 1), (1, -1)):
        permutation = PERMUTATIONS + index * 124
        block = b"".join(struct.pack("<hBB", 1000 if channel == 0 else -1000, 0, 0)
                         for channel in range(channels)) + bytes(32 * channels)
        offset = RAW + index * len(block)
        cache[offset:offset + len(block)] = block
        struct.pack_into("<hh", cache, permutation + 40, 1, following)
        struct.pack_into("<5I", cache, permutation + 64, len(block), 0, offset, 0, 0)
    raw = bytes(cache)
    return raw[:2048] + zlib.compress(raw[2048:]) if compressed else raw


def map_folder(tmp_path, cache):
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "ui.map").write_bytes(cache)
    return tmp_path


@pytest.mark.parametrize("compressed", [False, True])
def test_menu_cache_and_chained_tracks_are_decoded_locally(tmp_path, compressed):
    expected = xbox_cache()
    source = map_folder(tmp_path, xbox_cache(compressed=compressed))
    assert music.read_menu_map(source) == expected
    assert music.read_menu_map(source / "maps") == expected
    channels, rate, tracks = music.menu_tracks(expected)
    assert channels == 1 and rate == 22050
    assert len(tracks) == 1 and len(tracks[0]) == 72
    destination = tmp_path / "quiet-preview.wav"
    assert music.prepare_menu_music(source, destination) == destination
    with wave.open(str(destination), "rb") as result:
        assert (result.getnchannels(), result.getsampwidth(), result.getframerate(), result.getnframes()) == (1, 2, 22050, 128)
        assert set(struct.unpack("<128h", result.readframes(128))) == {120}


def test_stereo_channel_headers_and_interleaving_remain_distinct():
    channels, rate, tracks = music.menu_tracks(xbox_cache(channels=2))
    assert (channels, rate) == (2, 22050)
    output = music.decode_adpcm(tracks[0], channels)
    samples = struct.unpack("<256h", output)
    assert samples[::2] == (120,) * 128
    assert samples[1::2] == (-120,) * 128


def test_quiet_gain_is_bounded_and_zero_gain_is_silent():
    block = struct.pack("<hBB", 32767, 88, 0) + b"\x77" * 32
    samples = struct.unpack("<64h", music.decode_adpcm(block, 1))
    assert max(abs(sample) for sample in samples) <= int(32768 * 0.12)
    assert music.decode_adpcm(block, 1, gain=0) == bytes(128)
    with pytest.raises(music.MusicError, match="quiet"):
        music.decode_adpcm(block, 1, gain=0.13)
    with pytest.raises(music.MusicError):
        music.decode_adpcm(block, 3)
    with pytest.raises(music.MusicError):
        music.decode_adpcm(block[:-1], 1)
    with pytest.raises(music.MusicError, match="predictor"):
        music.decode_adpcm(struct.pack("<hBB", 0, 89, 0) + bytes(32), 1)


@pytest.mark.parametrize("offset,fmt,value", [
    (16, "<I", 8192),
    (TAG + 12, "<I", 32769),
    (TAG + 32, "<I", 0),
    (TABLE + 20, "<I", MAGIC + 8192),
    (METADATA + 110, "<h", 2),
    (PITCH + 60, "<I", 257),
    (PERMUTATIONS + 42, "<h", 0),
    (PERMUTATIONS + 42, "<h", 2),
    (PERMUTATIONS + 64, "<I", 37),
    (PERMUTATIONS + 72, "<I", 8192),
])
def test_malformed_pointers_counts_formats_and_chains_are_rejected(offset, fmt, value):
    cache = bytearray(xbox_cache())
    struct.pack_into(fmt, cache, offset, value)
    with pytest.raises(music.MusicError):
        music.menu_tracks(bytes(cache))


def test_cache_expansion_and_track_duration_are_bounded(tmp_path, monkeypatch):
    cache = xbox_cache()
    oversized = cache[:2048] + zlib.compress(bytes(1024 * 1024))
    source = map_folder(tmp_path, oversized)
    with pytest.raises(music.MusicError, match="decompression"):
        music.read_menu_map(source)
    monkeypatch.setattr(music, "MAX_SECONDS", 0)
    with pytest.raises(music.MusicError, match="duration"):
        music.menu_tracks(cache)


def test_cancelled_music_read_decode_and_prepare_never_publish_preview(tmp_path):
    source = map_folder(tmp_path, xbox_cache())
    cancel = threading.Event()
    cancel.set()
    block = struct.pack("<hBB", 0, 0, 0) + bytes(32)
    with pytest.raises(music.MusicError, match="cancelled"):
        music.read_menu_map(source, cancel)
    with pytest.raises(music.MusicError, match="cancelled"):
        music.decode_adpcm(block, 1, cancel)
    destination = tmp_path / "not-created.wav"
    with pytest.raises(music.MusicError, match="cancelled"):
        music.prepare_menu_music(source, destination, cancel)
    assert not destination.exists()


def test_menu_cache_limits_truncation_and_chunked_read_cancellation(tmp_path, monkeypatch):
    source = map_folder(tmp_path, xbox_cache())
    monkeypatch.setattr(music, "MAX_CACHE", 4096)
    with pytest.raises(music.MusicError, match="preview limit"):
        music.read_menu_map(source)
    with pytest.raises(music.MusicError, match="truncated"):
        music._read_cache(io.BytesIO(b"short"), 10, None)
    cancel = threading.Event()

    class CancelAfterFirstRead(io.BytesIO):
        def read(self, count):
            result = super().read(count)
            cancel.set()
            return result

    with pytest.raises(music.MusicError, match="cancelled"):
        music._read_cache(CancelAfterFirstRead(bytes(256 * 1024)), 256 * 1024, cancel)


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "Background music worker did not reach the expected state."


@pytest.fixture
def playback(monkeypatch):
    sound = types.SimpleNamespace(PlaySound=Mock(), SND_FILENAME=1,
                                  SND_ASYNC=2, SND_LOOP=4, SND_NODEFAULT=8)
    monkeypatch.setitem(sys.modules, "winsound", sound)
    monkeypatch.setattr(music, "sys", types.SimpleNamespace(platform="win32", byteorder="little"))
    players = []

    def create():
        player = music.MenuMusic()
        players.append(player)
        return player

    yield create, sound
    for player in players:
        player.close()


def fake_prepare(source, destination, cancel):
    destination.write_bytes(b"synthetic preview bytes")
    return destination


def test_controller_mute_resume_clear_and_close_only_control_own_playback(playback, monkeypatch):
    create, sound = playback
    monkeypatch.setattr(music, "prepare_menu_music", fake_prepare)
    player = create()
    folder = Path(player._temporary.name)
    player.load(Path("synthetic-source"))
    wait_until(lambda: player.status == "Halo menu music · quiet")
    first = sound.PlaySound.call_args
    assert Path(first.args[0]).parent == folder
    assert first.args[1] == 15  # filename + async + loop + no default fallback
    assert player.toggle() is True and player.status == "Menu music muted."
    assert sound.PlaySound.call_args.args == (None, 0)
    assert player.toggle() is False
    assert sound.PlaySound.call_args.args[0] == first.args[0]
    player.load(None)
    assert "Choose Xbox data" in player.status
    assert sound.PlaySound.call_args.args == (None, 0)
    assert list(folder.glob("*.wav")) == []
    player.close()
    assert not folder.exists()
    count = sound.PlaySound.call_count
    player.load(Path("ignored-after-close"))
    player.close()
    assert sound.PlaySound.call_count == count


def test_latest_selection_wins_and_cancelled_worker_does_not_restart_music(playback, monkeypatch):
    create, sound = playback
    entered = threading.Event()
    release = threading.Event()
    old_cancel = []

    def prepare(source, destination, cancel):
        if source.name == "first":
            old_cancel.append(cancel)
            entered.set()
            assert release.wait(3)
        return fake_prepare(source, destination, cancel)

    monkeypatch.setattr(music, "prepare_menu_music", prepare)
    player = create()
    folder = Path(player._temporary.name)
    try:
        player.load(Path("first"))
        assert entered.wait(2)
        player.load(Path("second"))
        wait_until(lambda: player.status == "Halo menu music · quiet")
        release.set()
        wait_until(lambda: not player._workers)
        assert not (folder / "menu-1.wav").exists()
        assert old_cancel[0].is_set()
        played = [Path(call.args[0]).name for call in sound.PlaySound.call_args_list if call.args[0] is not None]
        assert played == ["menu-2.wav"]
    finally:
        release.set()
        player.close()


def test_preparation_failure_removes_partial_preview_and_keeps_setup_available(playback, monkeypatch):
    create, sound = playback

    def failure(source, destination, cancel):
        destination.write_bytes(b"partial synthetic bytes")
        raise music.MusicError("unsupported synthetic sound")

    monkeypatch.setattr(music, "prepare_menu_music", failure)
    player = create()
    folder = Path(player._temporary.name)
    player.load(Path("synthetic-failure"))
    wait_until(lambda: "setup can continue" in player.status)
    assert list(folder.iterdir()) == []
    assert not sound.PlaySound.called


def test_windows_playback_failure_is_nonfatal_and_removes_preview(playback, monkeypatch):
    create, sound = playback
    monkeypatch.setattr(music, "prepare_menu_music", fake_prepare)
    sound.PlaySound.side_effect = RuntimeError("synthetic unavailable audio device")
    player = create()
    folder = Path(player._temporary.name)
    player.load(Path("synthetic-source"))
    wait_until(lambda: "setup can continue" in player.status)
    assert list(folder.iterdir()) == []
    player.close()
    assert not folder.exists()


def test_close_with_output_still_open_does_not_raise_and_worker_cleans_later(playback, monkeypatch):
    create, sound = playback
    entered = threading.Event()
    release = threading.Event()

    def hold_output(source, destination, cancel):
        with destination.open("wb") as stream:
            stream.write(b"held synthetic bytes")
            entered.set()
            assert release.wait(3)
        return destination

    monkeypatch.setattr(music, "prepare_menu_music", hold_output)
    monkeypatch.setattr(music.MenuMusic, "JOIN_SECONDS", 0.02, raising=False)
    player = create()
    folder = Path(player._temporary.name)
    try:
        player.load(Path("held-synthetic-source"))
        assert entered.wait(2)
        player.close()
        assert not sound.PlaySound.called
    finally:
        release.set()
    wait_until(lambda: not folder.exists())


def test_public_resources_contain_no_audio_recordings():
    resources = Path(__file__).resolve().parents[1] / "resources"
    audio = {".wav", ".ogg", ".mp3", ".flac", ".wma", ".aif", ".aiff"}
    assert not [path for path in resources.rglob("*") if path.is_file() and path.suffix.lower() in audio]
