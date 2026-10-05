"""The setup bar follows reported work, never a timer or phase-local reset."""
import pytest

from halo_frame_installer.progress import SetupProgress


def test_full_flow_is_monotonic_and_only_result_finishes():
    progress = SetupProgress()
    values = [progress.update(stage, percent) for stage, percent in (
        ("Preparing maps", 0), ("Preparing maps", 100), ("connect", None),
        ("preflight", None), ("verify", None), ("reuse", 100),
        ("upload", 0), ("upload", 50), ("upload", 100),
        ("source", None), ("build", None), ("dependencies", None),
        ("toolchain", None), ("configure", None), ("sdl", 50),
        ("sdl", 100), ("compile", 0), ("compile", 50),
        ("compile", 100), ("build-check", None), ("install", None),
        ("steam", None), ("disconnect", None), ("disconnected", None), ("complete", 100),
    )]
    assert values == sorted(values)
    assert max(values) == 99
    assert values[5] == 20  # Reusing all maps does not finish the wizard.
    assert progress.finish() == 100


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"),
                                -float("inf"), "50", True, {}, -1, 101, 10**1000])
def test_invalid_stage_percentage_only_advances_to_phase_start(bad):
    progress = SetupProgress()
    assert progress.update("compile", bad) == 73


def test_real_task_and_byte_counts_fill_only_their_phase():
    progress = SetupProgress()
    assert progress.update("upload", 25) == 25
    assert progress.update("compile", 25) == pytest.approx(77.25)
    assert progress.update("compile", 10) == pytest.approx(77.25)
    assert progress.update("sdl", 100) == pytest.approx(77.25)


def test_unknown_and_detail_events_cannot_reset_or_finish_progress():
    progress = SetupProgress()
    progress.update("toolchain")
    assert progress.update("detail", 100) == 52
    assert progress.update("future phase", 80) == 52
    assert progress.caption("compile") == "Compiling Halo and VR support"
    assert progress.caption("future phase") == "future phase"


def test_phase_can_hold_indefinitely_without_an_estimated_timer():
    progress = SetupProgress()
    assert progress.update("dependencies") == 45
    for _ in range(1000):
        assert progress.update("dependencies") == 45
    assert progress.update("toolchain") == 52


def test_manual_result_and_a_fresh_retry_have_separate_progress():
    progress = SetupProgress()
    progress.update("complete", 100)
    assert progress.finish(pending=True) == 99
    progress.reset()
    assert progress.value == 0
    assert progress.update("connect") == 10
    assert progress.update("steam") == 96
    assert progress.finish() == 100


def test_uninstall_work_finishes_only_after_connection_closes():
    progress = SetupProgress()
    assert progress.update('connect') == 10
    assert progress.update('preflight') == 12
    assert progress.update('uninstall', 0) == 15
    assert progress.update('uninstall', 50) == pytest.approx(55.5)
    assert progress.update('uninstall', 100) == 96
    assert progress.update('disconnected') == 99
    assert progress.finish() == 100
