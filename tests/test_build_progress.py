"""Exercise real incremental build logs, phase counts, EOF and cancellation."""

import importlib.util
import json
import os
import struct
import sys
import types
from pathlib import Path

import pytest


RESOURCES = Path(__file__).resolve().parents[1] / "resources"
RUN_ID = "d" * 32


@pytest.fixture
def remote(tmp_path, monkeypatch):
    if "pwd" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: None))
    if not hasattr(os, "getuid"):
        monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    spec = importlib.util.spec_from_file_location("build_progress_remote", RESOURCES / "remote_install.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    module.HOME = tmp_path / "home"
    module.HOME.mkdir()
    module.CACHE = module.HOME / "cache"
    module.GAME = module.HOME / "Games/HaloCENativeVR"
    module.owned(module.CACHE)
    module.owned(module.CACHE / "runs" / RUN_ID)
    module.prepare(RUN_ID)
    return module


def append(path, encoded):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as output:
        output.write(encoded)


def events(capsys):
    return [(prefix, json.loads(encoded)) for line in capsys.readouterr().out.splitlines()
            if line.startswith(("HFI_PROGRESS ", "HFI_LOG "))
            for prefix, encoded in [line.split(" ", 1)]]


def test_reports_actual_phases_and_nested_sdl_counts_without_regression(remote, capsys):
    directory = remote.run_dir(RUN_ID)
    main = directory / "native-build.log"
    sdl_configure = directory / "src/build/linux_arm64/sdl3-configure.log"
    sdl_build = directory / "src/build/linux_arm64/sdl3-build.log"
    monitor = remote.BuildLogMonitor(directory)
    append(main, b"Pulling image\nHFI_BUILD_PHASE dependencies Installing packages\n")
    monitor.poll()
    assert monitor.stage == "dependencies" and monitor.percent is None
    append(main, b"HFI_BUILD_PHASE toolchain Installing LLVM\n"
                 b"HFI_BUILD_PHASE configure Configuring VR\n"
                 b"HFI_BUILD_PHASE sdl Building SDL3\n"
                 b"[1/500] LINUX ARM64 CC early-guest.o\n")
    monitor.poll()
    assert monitor.stage == "sdl" and monitor.percent is None
    append(main, b"[1/500] LINUX ARM64 SDL3 release-3.4.16\n")
    append(sdl_configure, b"-- Checking audio backends\n")
    append(sdl_build, b"[1/2] Building C object SDL_audio.c.o\n")
    monitor.poll()
    assert monitor.stage == "sdl" and monitor.percent == 50
    append(main, b"[20/500] LINUX ARM64 CC game.o\n")
    append(sdl_build, b"[2/2] Linking C shared library libSDL3.so\n")
    monitor.poll()
    assert monitor.stage == "compile" and monitor.percent == 4
    append(main, b"[500/500] LINUX ARM64 STAGE build/linux_arm64/libSDL3.so.0\n"
                 b"HFI_BUILD_PHASE build-check Checking executable\nFinished without a newline")
    monitor.drain()
    emitted = events(capsys)
    updates = [event for prefix, event in emitted if prefix == "HFI_PROGRESS"]
    ranks = [remote.BUILD_PHASE_ORDER[event["stage"]] for event in updates]
    assert ranks == sorted(ranks)
    assert any(event["stage"] == "compile" and event.get("percent") == 100 for event in updates)
    assert not any(event["stage"] == "sdl" and event.get("percent") == 100 for event in updates)
    details = [event for prefix, event in emitted if prefix == "HFI_LOG"]
    assert any(event["stage"] == "sdl" and "[2/2]" in event["message"] for event in details)
    assert any(event["message"] == "-- Checking audio backends" for event in details)
    assert details[-1] == {"stage": "build-check", "message": "Finished without a newline"}
    assert any(event["stage"] == "compile" and "STAGE" in event["message"] for event in details)


def test_fragmented_utf8_cr_ansi_controls_and_huge_lines_are_bounded(remote, capsys):
    directory = remote.run_dir(RUN_ID)
    path = directory / "native-build.log"
    monitor = remote.BuildLogMonitor(directory)
    append(path, b"partial \x1b[31mCaf\xc3")
    monitor.poll()
    assert events(capsys) == []
    append(path, b"\xa9\x1b[0m\x00\x07\r\ntwo\x1b]0;secret-title\x07 shown\rsafe")
    monitor.poll()
    assert [event["message"] for prefix, event in events(capsys)] == ["partial Café", "two shown"]
    append(path, b"\n" + b"x" * 250000)
    while monitor.poll():
        assert len(monitor.tails[0].pending) <= remote.MAX_RAW_LOG_LINE
    append(path, b"\n\xff\nlast fragment")
    monitor.drain()
    details = [event["message"] for prefix, event in events(capsys) if prefix == "HFI_LOG"]
    assert details[0] == "safe"
    assert details[1].endswith("[line truncated]")
    assert len(details[1]) <= remote.MAX_LOG_MESSAGE
    assert details[2:] == ["\ufffd", "last fragment"]
    assert path.stat().st_size > 250000  # The full log was never truncated.
    assert remote.clean_build_line("\x9b31mred\x9b0m\x9dtitle\x9c\u202e safe") == "red safe"


def test_truncated_or_replaced_log_discards_old_partial_line(remote, capsys):
    directory = remote.run_dir(RUN_ID)
    path = directory / "native-build.log"
    monitor = remote.BuildLogMonitor(directory)
    append(path, b"old partial line")
    monitor.poll()
    path.write_bytes(b"new\n")
    monitor.poll()
    replacement = directory / "replacement"
    replacement.write_bytes(b"replacement\n")
    os.replace(replacement, path)
    monitor.poll()
    assert [event["message"] for prefix, event in events(capsys)] == ["new", "replacement"]


def test_quiet_heartbeat_retains_phase_and_last_real_percent(remote, monkeypatch, capsys):
    now = [0.0]
    monkeypatch.setattr(remote.time, "monotonic", lambda: now[0])
    directory = remote.run_dir(RUN_ID)
    monitor = remote.BuildLogMonitor(directory)
    append(directory / "native-build.log", b"HFI_BUILD_PHASE sdl Building SDL3\n")
    append(directory / "src/build/linux_arm64/sdl3-build.log", b"[5/10] Building audio\n")
    monitor.poll()
    events(capsys)
    now[0] = 14.9
    monitor.heartbeat()
    assert events(capsys) == []
    now[0] = 15
    monitor.heartbeat()
    update = events(capsys)[0][1]
    assert update["stage"] == "sdl" and update["percent"] == 50
    assert "phase elapsed 15s" in update["message"]
    assert "no new build output for 15s" in update["message"]
    now[0] = 16
    append(directory / "src/build/linux_arm64/sdl3-build.log", b"Compiler is still emitting a fragment")
    monitor.poll()
    now[0] = 30
    monitor.heartbeat()
    update = events(capsys)[0][1]
    assert update["percent"] == 50
    assert "no new build output for 14s" in update["message"]


def test_log_reader_rejects_outside_path_hard_links_and_wrong_owner(remote, monkeypatch):
    directory = remote.run_dir(RUN_ID)
    path = directory / "native-build.log"
    path.write_bytes(b"private\n")
    outside = remote.HOME / "outside.log"
    outside.write_bytes(b"not build output\n")
    with pytest.raises(ValueError, match="outside"):
        remote.BuildLogTail(outside, directory, lambda line: None).read()
    alias = directory / "alias.log"
    os.link(path, alias)
    with pytest.raises(ValueError, match="private ordinary"):
        remote.BuildLogMonitor(directory).poll()
    alias.unlink()
    original_uid = os.getuid()
    monkeypatch.setattr(remote.os, "getuid", lambda: original_uid + 1)
    with pytest.raises(ValueError, match="private ordinary"):
        remote.BuildLogMonitor(directory).poll()


def test_log_reader_rejects_symlinks_in_generated_path(remote):
    directory = remote.run_dir(RUN_ID)
    actual = directory / "actual"
    actual.mkdir()
    (actual / "build/linux_arm64").mkdir(parents=True)
    (actual / "build/linux_arm64/sdl3-build.log").write_bytes(b"[1/2] unsafe\n")
    try:
        (directory / "src").symlink_to(actual, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Creating a test symlink is unavailable: {error}")
    with pytest.raises(ValueError, match="Symbolic links"):
        remote.BuildLogMonitor(directory).poll()


def setup_build(remote, monkeypatch):
    directory = remote.run_dir(RUN_ID)
    resources = remote.CACHE / "resources"
    resources.mkdir()
    (resources / "frame-controls.patch").write_bytes(b"git is mocked")
    (resources / "build-native.sh").write_bytes((RESOURCES / "build-native.sh").read_bytes())
    (directory / "upload/xbox-data-manifest.json").write_text("{}")
    monkeypatch.setattr(remote, "existing_install", lambda *args: None)
    monkeypatch.setattr(remote, "verify_maps", lambda *args, **kwargs: 0)
    monkeypatch.setattr(remote.time, "sleep", lambda seconds: None)
    original_which = remote.shutil.which
    monkeypatch.setattr(remote.shutil, "which", lambda name: (
        "podman" if name == "podman" else None if name == "systemd-inhibit" else original_which(name)))

    def git(argv, **kwargs):
        if argv[:2] == ["podman", "ps"]:
            return "[]"
        assert argv[0] == "git"
        if argv[1] == "init":
            Path(argv[2]).mkdir()
        return remote.SOURCE_COMMIT if argv[-2:] == ["rev-parse", "HEAD"] else ""

    monkeypatch.setattr(remote, "command", git)
    return directory


@pytest.mark.parametrize("exit_code", [0, 100])
def test_actual_build_drains_immediate_exit_and_checks_success(remote, monkeypatch, capsys, exit_code):
    directory = setup_build(remote, monkeypatch)
    build_files = directory / "src/build/linux_arm64"

    def immediate(argv, **kwargs):
        kwargs["stdout"].write(b"HFI_BUILD_PHASE dependencies Installing packages\n"
                               b"last package-manager output without newline")
        if exit_code == 0:
            build_files.mkdir(parents=True)
            header = bytearray(64)
            header[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<H", header, 18, 183)
            (build_files / "halo").write_bytes(header)
            (build_files / "libSDL3.so.0").write_bytes(b"synthetic SDL3")
        return types.SimpleNamespace(returncode=exit_code, poll=lambda: exit_code)

    monkeypatch.setattr(remote.subprocess, "Popen", immediate)
    if exit_code:
        with pytest.raises(RuntimeError, match="last package-manager output without newline"):
            remote.build(RUN_ID)
    else:
        assert remote.build(RUN_ID)["built"] is True
    emitted = events(capsys)
    assert any(prefix == "HFI_LOG" and event["message"] == "last package-manager output without newline"
               for prefix, event in emitted)
    assert any(event["stage"] == "build-check" and event.get("percent") == 100
               for prefix, event in emitted if prefix == "HFI_PROGRESS") == (exit_code == 0)
    assert not remote.GAME.exists()


def test_actual_live_build_cancellation_stops_owned_process_and_drains_last_line(remote, monkeypatch, capsys):
    directory = setup_build(remote, monkeypatch)
    stopped, cancelled = [], []

    def live(argv, **kwargs):
        def poll():
            kwargs["stdout"].write(b"HFI_BUILD_PHASE toolchain Installing LLVM\nlast output on cancel")
            kwargs["stdout"].flush()
            (directory / "cancelled").touch()
            return None
        return types.SimpleNamespace(returncode=None, poll=poll)

    monkeypatch.setattr(remote.subprocess, "Popen", live)
    monkeypatch.setattr(remote, "cancel", lambda run: cancelled.append(run))
    monkeypatch.setattr(remote, "stop_build_process", lambda process: stopped.append(process))
    with pytest.raises(RuntimeError, match="Build cancelled"):
        remote.build(RUN_ID)
    assert cancelled and set(cancelled) == {RUN_ID}
    assert stopped and len({id(process) for process in stopped}) == 1
    assert any(prefix == "HFI_LOG" and event["message"] == "last output on cancel"
               for prefix, event in events(capsys))
    assert not remote.GAME.exists()


def test_progress_percent_is_optional_and_never_invented(remote, capsys):
    remote.progress("dependencies", "Downloading packages")
    remote.progress("compile", "37 of 100 steps", 37)
    emitted = events(capsys)
    assert emitted[0][1] == {"stage": "dependencies", "message": "Downloading packages"}
    assert emitted[1][1]["percent"] == 37
    with pytest.raises(ValueError):
        remote.progress("compile", "invalid", float("nan"))
    script = (RESOURCES / "build-native.sh").read_text()
    assert "export NINJA_STATUS='[%f/%t] '" in script
