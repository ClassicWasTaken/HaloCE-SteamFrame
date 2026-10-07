"""Execute the shipped configure recipe's command flow without package installs.

The canonical engine integration check validates real source files and build
dependencies. This harness checks the shell command list, missing-file failure,
and fail-fast ordering using only temporary files and an offline receiver.
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "resources/build-native.sh"
PATCH = ROOT / "resources/frame-controls.patch"


def shipped_tests():
    return set(re.findall(r"^diff --git a/(tools/test_[^ ]+\.py) b/\1$",
                          PATCH.read_text(encoding="utf-8"), re.M))


def recipe_commands(text):
    return [shlex.split(line, comments=True) for line in text.splitlines()
            if line.startswith("python3 ")]


def audit_recipe(text):
    commands = recipe_commands(text)
    assert commands and commands[-1] == ["python3", "configure.py", "--release", "--vr", "--linux-arm64-cc", "clang"]
    tests = commands[:-1]
    assert tests[0] == ["python3", "tools/test_build_sources.py"]
    names = [command[1] for command in tests]
    assert len(names) == len(set(names)), "A native regression was duplicated"
    assert set(names) == shipped_tests(), "Recipe checks do not match the tests shipped in the engine patch"
    for command in tests[1:]:
        if command[1] == "tools/test_vr_renderer_link.py":
            assert command[2:] == ["--cc", "clang", "--ld", "ld.lld", "--sdk", "/usr/include"]
        else:
            assert command[2:] == ["--cc", "clang"]
    assert "set -euo pipefail" in text
    return commands


def test_shipped_recipe_runs_every_current_engine_regression_once_before_configuration():
    commands = audit_recipe(RECIPE.read_text(encoding="utf-8"))
    assert len(commands) > 20  # An accidental empty/partial patch cannot weaken this check.


@pytest.mark.parametrize("removed", ["tools/test_vr_scope.py", "tools/test_vr_scope_render.py",
                                     "tools/test_vr_scope_backend.py", "tools/test_vr_scope_hud.py",
                                     "tools/test_vr_scope_link.py"])
def test_recipe_audit_rejects_removed_scope_tests_even_when_other_checks_remain(removed):
    text = RECIPE.read_text(encoding="utf-8").replace(
        "python3 tools/test_vr_stock_zoom_hud.py --cc clang\n",
        "python3 " + removed + " --cc clang\n")
    with pytest.raises(AssertionError, match="match the tests shipped"):
        audit_recipe(text)


@pytest.fixture
def shell_recipe(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        bash = str(candidate) if candidate.is_file() else None
    if not bash:
        pytest.skip("Bash is required for the offline native recipe command-flow check")
    source = tmp_path / "source"
    source.mkdir()
    # Only scripts from the actual patch are available. A deleted scope script
    # is therefore a real missing path in this shell command-flow fixture.
    for name in [*shipped_tests(), "configure.py"]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Offline command-flow fixture; engine execution is checked separately.\n")
    receiver = tmp_path / "receive-command.py"
    receiver.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "arguments=sys.argv[1:]\n"
        "print('HFI_RECIPE_COMMAND '+json.dumps(arguments),flush=True)\n"
        "if not Path(arguments[0]).is_file():\n"
        " print('Missing native regression: '+arguments[0],file=sys.stderr,flush=True)\n"
        " raise SystemExit(2)\n"
        "if arguments[0]==os.environ.get('HFI_FAIL_SCRIPT'):\n"
        " print('Synthetic regression failure',file=sys.stderr,flush=True)\n"
        " raise SystemExit(41)\n", encoding="utf-8")

    def run(text, fail=None):
        # Execute the exact configure commands between the source check and
        # package inventory. No apt/curl/compiler/Frame command is invoked.
        start = text.index("phase configure 'Verifying")
        end = text.index("# Record signed-package versions.")
        command = ("set -euo pipefail\n"
                   "cd \"$HFI_RECIPE_SOURCE\"\n"
                   "phase() { printf 'HFI_BUILD_PHASE %s %s\\n' \"$1\" \"$2\"; }\n"
                   "python3() { \"$HFI_RECIPE_PYTHON\" \"$HFI_RECIPE_RECEIVER\" \"$@\"; }\n"
                   + text[start:end])
        env = dict(os.environ, HFI_RECIPE_SOURCE=source.as_posix(),
                   HFI_RECIPE_PYTHON=Path(sys.executable).as_posix(),
                   HFI_RECIPE_RECEIVER=receiver.as_posix(), HFI_FAIL_SCRIPT=fail or "",
                   MSYS2_ARG_CONV_EXCL="*")
        result = subprocess.run([bash, "--noprofile", "--norc", "-c", command],
                                env=env, text=True, capture_output=True, timeout=15)
        calls = [json.loads(line.removeprefix("HFI_RECIPE_COMMAND "))
                 for line in result.stdout.splitlines() if line.startswith("HFI_RECIPE_COMMAND ")]
        return result, calls

    def precheck(text, missing=None):
        if missing is not None:
            (source / missing).unlink()
        staged = tmp_path / "build-native.sh"
        # Rebind only the two absolute build paths used before apt. The complete
        # script remains on disk, and BASH_SOURCE reads its actual command list.
        staged_text = text.replace("cd /build\n", "cd \"$HFI_RECIPE_BUILD\"\n", 1).replace(
            '"/build/src/$_hfi_test_script"', '"$HFI_RECIPE_SOURCE/$_hfi_test_script"', 1)
        staged.write_text(staged_text, encoding="utf-8", newline="\n")
        command = ("apt-get() { printf 'HFI_PRECHECK_ACTIVITY apt-get %s\\n' \"$*\"; exit 87; }\n"
                   "curl() { printf 'HFI_PRECHECK_ACTIVITY curl %s\\n' \"$*\"; exit 88; }\n"
                   "source \"$HFI_RECIPE_SCRIPT\"\n")
        env = dict(os.environ, HFI_RECIPE_BUILD=tmp_path.as_posix(),
                   HFI_RECIPE_SOURCE=source.as_posix(), HFI_RECIPE_SCRIPT=staged.as_posix(),
                   MSYS2_ARG_CONV_EXCL="*")
        return subprocess.run([bash, "--noprofile", "--norc", "-c", command],
                              env=env, text=True, capture_output=True, timeout=15)

    run.precheck = precheck
    return run


def test_actual_bash_precheck_reaches_first_package_step_with_all_shipped_tests(shell_recipe):
    result = shell_recipe.precheck(RECIPE.read_text(encoding="utf-8"))
    # The intercepted package command exits immediately; no apt/curl operation runs.
    assert result.returncode == 87, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "HFI_PRECHECK_ACTIVITY apt-get update"
    assert "Missing native build test" not in result.stderr
    phases = [line for line in result.stdout.splitlines() if line.startswith("HFI_BUILD_PHASE ")]
    assert len(phases) == 2 and all(line.startswith("HFI_BUILD_PHASE dependencies ") for line in phases)
    assert "Checking bundled native build tests" in phases[0]
    assert "Installing isolated ARM64 build dependencies" in phases[1]


@pytest.mark.parametrize("cause", ["missing-current-test", "stale-scope-command"])
def test_actual_bash_precheck_rejects_missing_test_before_any_package_or_download_step(shell_recipe, cause):
    text = RECIPE.read_text(encoding="utf-8")
    if cause == "missing-current-test":
        missing = "tools/test_vr_framebuffer.py"
        result = shell_recipe.precheck(text, missing=missing)
    else:
        missing = "tools/test_vr_scope.py"
        result = shell_recipe.precheck(text.replace("tools/test_vr_stock_zoom_hud.py", missing))
    assert result.returncode == 1
    assert result.stderr.strip() == "Missing native build test: " + missing
    assert "HFI_PRECHECK_ACTIVITY" not in result.stdout
    assert "Installing isolated ARM64 build dependencies" not in result.stdout
    assert "HFI_BUILD_PHASE configure" not in result.stdout


def test_actual_bash_configure_recipe_reaches_native_configuration_after_every_check(shell_recipe):
    text = RECIPE.read_text(encoding="utf-8")
    result, calls = shell_recipe(text)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [command[1:] for command in audit_recipe(text)]
    assert calls[-1] == ["configure.py", "--release", "--vr", "--linux-arm64-cc", "clang"]
    assert "HFI_BUILD_PHASE configure Configuring the native ARM64 OpenXR game" in result.stdout


def test_actual_bash_recipe_stops_on_missing_test_before_native_configuration(shell_recipe):
    text = RECIPE.read_text(encoding="utf-8").replace(
        "tools/test_vr_stock_zoom_hud.py", "tools/test_vr_scope.py")
    result, calls = shell_recipe(text)
    assert result.returncode == 2 and "Missing native regression: tools/test_vr_scope.py" in result.stderr
    assert calls[-1] == ["tools/test_vr_scope.py", "--cc", "clang"]
    assert not any(command[0] == "configure.py" for command in calls)
    assert not any(command[0] == "tools/test_vr_driving.py" for command in calls)


def test_actual_bash_recipe_preserves_real_check_failure_before_native_configuration(shell_recipe):
    result, calls = shell_recipe(RECIPE.read_text(encoding="utf-8"), "tools/test_vr_driving.py")
    assert result.returncode == 41 and "Synthetic regression failure" in result.stderr
    assert calls[-1] == ["tools/test_vr_driving.py", "--cc", "clang"]
    assert not any(command[0] == "configure.py" for command in calls)
    assert not any(command[0] == "tools/test_vr_driving_game.py" for command in calls)
