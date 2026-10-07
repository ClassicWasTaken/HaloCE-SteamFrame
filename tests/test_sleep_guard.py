"""Exercise the production sleep-lock lifecycle without invoking host services."""

import io
import json
import struct
import subprocess
import sys
import threading
import types

import pytest

from test_build_progress import RUN_ID, events, remote, setup_build


def fake_service(remote, monkeypatch, mode="ready", container=None):
    """Run the actual Python lock holder behind a local fake service boundary."""
    original_popen = subprocess.Popen
    original_which = remote.shutil.which
    processes, launches = [], []
    monkeypatch.setattr(remote.shutil, "which", lambda name: (
        "fake-systemd-inhibit" if name == "systemd-inhibit" else original_which(name)))

    def launch(argv, **kwargs):
        if argv[0] != "fake-systemd-inhibit":
            assert container is not None
            return container(argv, **kwargs)
        launches.append((argv, kwargs.copy()))
        assert argv[1:7] == ["--what=idle:sleep", "--mode=block", "--who=Halo Frame Installer",
                             "--why=Building the native Halo VR game", "--no-ask-password", sys.executable]
        assert kwargs == {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                          "stderr": subprocess.DEVNULL, "start_new_session": True, "bufsize": 0}
        command = argv[6:]
        if mode == "denied":
            command = [sys.executable, "-u", "-c", "raise SystemExit(1)"]
        elif mode == "malformed":
            command = [sys.executable, "-u", "-c", "import sys; print('WRONG', flush=True); sys.stdin.buffer.read()"]
        elif mode == "timeout":
            command = [sys.executable, "-u", "-c", "import sys; sys.stdin.buffer.read()"]
        elif mode == "blocked":
            command = [sys.executable, "-u", "-c", "import time; time.sleep(30)"]
        process = original_popen(command, **kwargs)
        if mode == "blocked":
            process.real_wait = process.wait
            def failed_wait(timeout):
                raise subprocess.TimeoutExpired(command, timeout)
            process.wait = failed_wait
        processes.append(process)
        return process

    monkeypatch.setattr(remote.subprocess, "Popen", launch)
    return processes, launches


def released(process):
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed


@pytest.mark.parametrize("result", ["success", "failure", "cancelled"])
def test_real_holder_lives_inside_context_and_releases_for_every_exit(remote, monkeypatch, capsys, result):
    processes, launches = fake_service(remote, monkeypatch)
    try:
        with remote.build_sleep_inhibitor(lambda: None) as lock:
            assert lock is processes[0] and lock.poll() is None
            assert not lock.stdin.closed and not lock.stdout.closed
            if result != "success":
                raise RuntimeError(result)
    except RuntimeError as error:
        assert str(error) == result and result != "success"
    assert len(launches) == 1
    released(processes[0])
    updates = events(capsys)
    assert len(updates) == 1 and "temporarily blocked" in updates[0][1]["message"]
    assert "HFI_SLEEP_INHIBITOR_READY" not in updates[0][1]["message"]


@pytest.mark.parametrize("mode", ["denied", "malformed", "timeout"])
def test_denied_bad_or_unresponsive_service_releases_before_fallback(remote, monkeypatch, capsys, mode):
    processes, _ = fake_service(remote, monkeypatch, mode)
    if mode == "timeout":
        monkeypatch.setattr(remote, "SLEEP_INHIBITOR_START_SECONDS", 0.05)
    with remote.build_sleep_inhibitor(lambda: None) as lock:
        assert lock is None
        released(processes[0])
    assert "Keep the Frame awake" in events(capsys)[0][1]["message"]


@pytest.mark.parametrize("unavailable", ["absent", "spawn-failed"])
def test_unavailable_inhibitor_does_not_prevent_the_build(remote, monkeypatch, capsys, unavailable):
    monkeypatch.setattr(remote.shutil, "which", lambda name: None if unavailable == "absent" else "missing-service")
    def unavailable_process(*args, **kwargs):
        raise OSError("service unavailable")
    monkeypatch.setattr(remote.subprocess, "Popen", unavailable_process)
    with remote.build_sleep_inhibitor(lambda: None) as lock:
        assert lock is None
    assert "sleep prevention is unavailable" in events(capsys)[0][1]["message"]


def test_startup_cancellation_closes_holder_without_entering_build(remote, monkeypatch):
    processes, _ = fake_service(remote, monkeypatch, "timeout")
    def cancelled():
        raise RuntimeError("Build cancelled")
    entered = []
    with pytest.raises(RuntimeError, match="Build cancelled"):
        with remote.build_sleep_inhibitor(cancelled):
            entered.append(True)
    assert not entered
    released(processes[0])


def test_failed_startup_cleanup_is_bounded_even_while_ready_reader_is_blocked(remote, monkeypatch):
    processes, _ = fake_service(remote, monkeypatch, "blocked")
    monkeypatch.setattr(remote, "SLEEP_INHIBITOR_START_SECONDS", 0.05)
    def foreign_group(process):
        raise ValueError("owned private process group changed")
    monkeypatch.setattr(remote, "stop_build_process", foreign_group)
    results = []
    def attempt():
        try:
            with remote.build_sleep_inhibitor(lambda: None):
                results.append("unexpectedly entered build")
        except BaseException as error:
            results.append(error)
    operation = threading.Thread(target=attempt, daemon=True)
    operation.start()
    try:
        operation.join(timeout=3)
        assert not operation.is_alive(), "closing stdout waited for the blocked READY reader"
        assert len(results) == 1 and isinstance(results[0], ValueError)
        assert "owned private process group" in str(results[0])
        assert processes[0].stdin.closed
    finally:
        # This local fake service deliberately ignored stdin and was declared
        # foreign by the mock. The test itself owns and reaps its real child.
        for process in processes:
            process.kill()
            process.real_wait(timeout=3)
        operation.join(timeout=3)
    # Once its read ends, the reader itself releases the remaining pipe.
    assert processes[0]._hfi_sleep_read_done.wait(timeout=3)


def test_private_stdin_eof_releases_holder_on_parent_pipe_loss(remote, monkeypatch):
    processes, _ = fake_service(remote, monkeypatch)
    with remote.build_sleep_inhibitor(lambda: None):
        # Parent death closes its sole writer too; the holder needs no heartbeat
        # timer or persistent systemd/power configuration to release the lock.
        process = processes[0]
        process.stdin.close()
        assert process.wait(timeout=3) == 0
    released(process)


def test_hung_release_uses_only_the_owned_process_group_cleanup(remote, monkeypatch):
    waits, stopped = [], []
    def wait(timeout):
        waits.append(timeout)
        raise subprocess.TimeoutExpired("fake-systemd-inhibit", timeout)
    process = types.SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(), wait=wait)
    monkeypatch.setattr(remote, "stop_build_process", lambda child: stopped.append(child))
    remote.release_sleep_inhibitor(process)
    assert waits == [3] and stopped == [process]
    assert process.stdin.closed and process.stdout.closed


@pytest.mark.parametrize("foreign_group", [False, True])
def test_actual_group_cleanup_rechecks_identity_before_forcing_release(remote, monkeypatch, foreign_group):
    waits, signals = [], []
    def wait(timeout):
        waits.append(timeout)
        if len(waits) <= 2:
            raise subprocess.TimeoutExpired("fake-systemd-inhibit", timeout)
        return -9
    process = types.SimpleNamespace(pid=12345, stdin=io.BytesIO(), stdout=io.BytesIO(),
                                    poll=lambda: None, wait=wait)
    monkeypatch.setattr(remote.os, "getpgid", lambda pid: pid + 1 if foreign_group else pid, raising=False)
    monkeypatch.setattr(remote.os, "killpg", lambda pid, sig: signals.append((pid, sig)), raising=False)
    monkeypatch.setattr(remote.signal, "SIGKILL", 9, raising=False)
    if foreign_group:
        with pytest.raises(ValueError, match="owned private process group"):
            remote.release_sleep_inhibitor(process)
        assert waits == [3] and not signals
    else:
        remote.release_sleep_inhibitor(process)
        assert waits == [3, 10, 10]
        assert signals == [(process.pid, remote.signal.SIGTERM), (process.pid, remote.signal.SIGKILL)]
    assert process.stdin.closed and process.stdout.closed


def test_release_error_preserves_the_original_build_error(remote, monkeypatch):
    processes, _ = fake_service(remote, monkeypatch)
    release = remote.release_sleep_inhibitor
    def unconfirmed(process):
        release(process)
        raise RuntimeError("owned process group changed")
    monkeypatch.setattr(remote, "release_sleep_inhibitor", unconfirmed)
    with pytest.raises(RuntimeError, match="original build failure") as caught:
        with remote.build_sleep_inhibitor(lambda: None):
            raise RuntimeError("original build failure")
    assert "sleep lock" in caught.value.__notes__[0]
    released(processes[0])


def write_binary(directory):
    build_files = directory / "src/build/linux_arm64"
    build_files.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    (build_files / "halo").write_bytes(header)
    (build_files / "libSDL3.so.0").write_bytes(b"synthetic SDL3")


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "spawn-failed", "drain-failed"])
def test_actual_build_holds_lock_through_log_drain_and_releases(remote, monkeypatch, capsys, result):
    directory = setup_build(remote, monkeypatch)
    stopped, cancelled, drained = [], [], []
    def container(argv, **kwargs):
        assert argv[:2] == ["podman", "run"]
        assert processes[0].poll() is None
        if result == "spawn-failed":
            raise OSError("podman spawn failure")
        kwargs["stdout"].write(b"HFI_BUILD_PHASE compile Compiling game\nlast build fragment")
        if result == "success":
            write_binary(directory)
        code = 100 if result == "failure" else 0
        def poll():
            if result == "cancelled":
                (directory / "cancelled").touch()
                return None
            return code
        return types.SimpleNamespace(returncode=code, poll=poll)
    processes, _ = fake_service(remote, monkeypatch, container=container)
    original_drain = remote.BuildLogMonitor.drain
    def drain(monitor):
        assert processes[0].poll() is None
        drained.append(True)
        original_drain(monitor)
        if result == "drain-failed":
            raise RuntimeError("log drain failure")
    monkeypatch.setattr(remote.BuildLogMonitor, "drain", drain)
    monkeypatch.setattr(remote, "cancel", lambda run: cancelled.append(run))
    monkeypatch.setattr(remote, "stop_build_process", lambda process: stopped.append(process))
    if result == "success":
        assert remote.build(RUN_ID)["built"]
    else:
        message = {"failure": "Native build failed", "cancelled": "Build cancelled",
                   "spawn-failed": "podman spawn failure", "drain-failed": "log drain failure"}[result]
        with pytest.raises((RuntimeError, OSError), match=message):
            remote.build(RUN_ID)
    released(processes[0])
    assert bool(drained) == (result != "spawn-failed")
    assert bool(stopped) == bool(cancelled) == (result == "cancelled")
    if result != "spawn-failed":
        assert any(prefix == "HFI_LOG" and event["message"] == "last build fragment"
                   for prefix, event in events(capsys))
    assert not remote.GAME.exists()


def test_actual_build_warns_once_if_acquired_lock_ends_unexpectedly(remote, monkeypatch, capsys):
    directory = setup_build(remote, monkeypatch)
    polls = []
    def container(argv, **kwargs):
        assert processes[0].poll() is None
        processes[0].stdin.close()
        processes[0].wait(timeout=3)
        kwargs["stdout"].write(b"HFI_BUILD_PHASE compile Compiling game\n")
        write_binary(directory)
        def poll():
            polls.append(True)
            return 0 if len(polls) == 3 else None
        return types.SimpleNamespace(returncode=0, poll=poll)
    processes, _ = fake_service(remote, monkeypatch, container=container)
    assert remote.build(RUN_ID)["built"]
    updates = [event for prefix, event in events(capsys) if prefix == "HFI_PROGRESS"]
    assert sum("ended unexpectedly" in event["message"] for event in updates) == 1
    released(processes[0])


@pytest.mark.parametrize("exists_code", [0, 1, 125, 2, -1])
def test_stop_owned_container_distinguishes_absence_from_check_failure(remote, monkeypatch, exists_code):
    calls, stops = [], []
    labels = {"org.halo-frame-installer.owner": remote.OWNER, "org.halo-frame-installer.run": RUN_ID}
    def run(argv, **kwargs):
        calls.append(argv)
        return types.SimpleNamespace(returncode=exists_code if argv[2] == "exists" else 0,
                                     stdout=json.dumps([{"Config": {"Labels": labels}}]))
    monkeypatch.setattr(remote.subprocess, "run", run)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: stops.append(argv))
    if exists_code in (0, 1):
        assert remote.stop_owned_container(RUN_ID) == {"cancelled": True}
    else:
        with pytest.raises(RuntimeError, match="presence could not be verified"):
            remote.stop_owned_container(RUN_ID)
    assert calls[0] == ["podman", "container", "exists", "halo-frame-installer-" + RUN_ID]
    assert len(calls) == (2 if exists_code == 0 else 1)
    assert stops == ([["podman", "stop", "--time", "10", "halo-frame-installer-" + RUN_ID]] if exists_code == 0 else [])


def test_inspect_failure_after_confirmed_container_is_not_reported_as_stopped(remote, monkeypatch):
    stops = []
    monkeypatch.setattr(remote.subprocess, "run", lambda argv, **kwargs:
                        types.SimpleNamespace(returncode=0 if argv[2] == "exists" else 125, stdout=""))
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: stops.append(argv))
    with pytest.raises(RuntimeError, match="could not be inspected"):
        remote.stop_owned_container(RUN_ID)
    assert not stops


@pytest.mark.parametrize("response", ["[]", '[{"Names": ["old installer"]}]', "{}", "null", "not json"])
def test_actual_active_build_gate_blocks_before_source_or_container_creation(remote, monkeypatch, response):
    directory = setup_build(remote, monkeypatch)
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        assert argv[:2] == ["podman", "ps"]
        assert "label=org.halo-frame-installer.owner=" + remote.OWNER in argv
        return response
    monkeypatch.setattr(remote, "command", command)
    if response == "[]":
        remote.no_active_build()
    else:
        with pytest.raises(ValueError):
            remote.build(RUN_ID)
        assert not (directory / "src").exists()
        assert not (directory / "native-build.log").exists()
    assert len(calls) == 1


def test_active_build_query_failure_is_not_assumed_to_mean_no_build(remote, monkeypatch):
    directory = setup_build(remote, monkeypatch)
    def failed(argv, **kwargs):
        raise RuntimeError("podman storage unavailable")
    monkeypatch.setattr(remote, "command", failed)
    with pytest.raises(ValueError, match="safely check for an active installer build"):
        remote.build(RUN_ID)
    assert not (directory / "src").exists()


def test_build_rechecks_prior_container_after_source_fetch_and_releases_lock(remote, monkeypatch):
    directory = setup_build(remote, monkeypatch)
    source_command = remote.command
    active, checked = [], []
    def command(argv, **kwargs):
        if argv[:2] == ["podman", "ps"]:
            checked.append(True)
            if active:
                assert processes[0].poll() is None
                return '[{"Names":["older installer run"]}]'
            return "[]"
        if "fetch" in argv:
            active.append(True)
        return source_command(argv, **kwargs)
    monkeypatch.setattr(remote, "command", command)
    def container(*args, **kwargs):
        pytest.fail("A second build container must not start")
    processes, _ = fake_service(remote, monkeypatch, container=container)
    with pytest.raises(ValueError, match="No second build was started"):
        remote.build(RUN_ID)
    assert len(checked) == 2 and (directory / "src").is_dir()
    assert not remote.GAME.exists()
    released(processes[0])


def test_missing_podman_refuses_retry_without_creating_any_source(remote, monkeypatch):
    directory = setup_build(remote, monkeypatch)
    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="active installer build cannot be checked"):
        remote.build(RUN_ID)
    assert not (directory / "src").exists()


@pytest.mark.parametrize("failure", ["exists", "inspect"])
def test_container_query_timeout_never_reports_successful_stop(remote, monkeypatch, failure):
    stops = []
    def run(argv, **kwargs):
        if argv[2] == failure:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return types.SimpleNamespace(returncode=0, stdout="")
    monkeypatch.setattr(remote.subprocess, "run", run)
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: stops.append(argv))
    with pytest.raises(subprocess.TimeoutExpired):
        remote.stop_owned_container(RUN_ID)
    assert not stops
