"""Run the actual renderer entry point with real compilers and linker choices.

Opt-in local engine/tool paths keep this suite offline. No tool, SDL archive,
retail game data, container, or headset is downloaded or accessed.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def renderer_runtime():
    location = os.environ.get("HFI_NATIVE_ENGINE_SOURCE")
    if not location:
        pytest.skip("Set HFI_NATIVE_ENGINE_SOURCE to the patched local engine for actual renderer CLI checks")
    source = Path(location).resolve(strict=True)
    script = source / "tools/test_vr_renderer_link.py"
    assert script.is_file(), "The supplied engine must contain the shipped renderer regression"
    cc = os.environ.get("HFI_RENDERER_CC") or shutil.which("clang")
    ld = os.environ.get("HFI_RENDERER_LD") or shutil.which("ld.lld")
    assert cc and ld, "Provide HFI_RENDERER_CC/HFI_RENDERER_LD with installed LLVM tools"
    cc, ld = Path(cc).resolve(strict=True), Path(ld).resolve(strict=True)
    sdl = os.environ.get("HFI_RENDERER_SDL")
    sdk = os.environ.get("HFI_RENDERER_SDK")
    if sdl:
        sdl = Path(sdl).resolve(strict=True)
        assert (sdl / "include/SDL3/SDL_opengl.h").is_file()
    elif sdk:
        sdk = Path(sdk).resolve(strict=True)
        assert (sdk / "GL/glcorearb.h").is_file()
    else:
        sdk = Path("/usr/include")
        assert (sdk / "GL/glcorearb.h").is_file(), "Provide existing local Khronos SDK or SDL source headers"
    return source, script, cc, ld, sdl, sdk


def invoke(runtime, arguments, *, env=None):
    source, script, *_ = runtime
    return subprocess.run([sys.executable, str(script), *arguments], cwd=source,
                          env=env, capture_output=True, text=True, timeout=90)


def headers(runtime):
    return ["--sdl", str(runtime[4])] if runtime[4] else ["--sdk", str(runtime[5])]


@pytest.mark.parametrize("selection", ["path-names", "absolute-paths", "relative-paths", "linker-symlink", "cc-environment"])
def test_actual_renderer_cli_resolves_tools_and_retains_real_arm_import_checks(renderer_runtime, tmp_path, selection):
    source, _, cc, ld, sdl, _ = renderer_runtime
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()
    linker_name = "ld.lld.exe" if os.name == "nt" else "ld.lld"
    alias = tool_dir / linker_name
    if selection == "linker-symlink":
        try:
            alias.symlink_to(ld)
        except OSError as error:
            pytest.skip("Creating a linker symlink is unavailable: " + str(error))
    else:
        os.link(ld, alias)
    # Keep clang in its original directory: LLVM derives its real resource
    # headers from the executable location. Only the linker alias is temporary.
    env = dict(os.environ, PATH=os.pathsep.join((str(tool_dir), str(cc.parent), os.environ.get("PATH", ""))))
    if selection in ("path-names", "cc-environment", "linker-symlink"):
        arguments = ["--cc", "clang", "--ld", "ld.lld"]
    elif selection == "absolute-paths":
        arguments = ["--cc", str(cc), "--ld", str(ld)]
    else:
        arguments = ["--cc", os.path.relpath(cc, source), "--ld", os.path.relpath(alias, source)]
    if selection == "cc-environment":
        env["CC"] = "clang"
        arguments = arguments[2:]
    arguments += headers(renderer_runtime)
    if selection == "relative-paths" and sdl:
        arguments[-1] = os.path.relpath(sdl, source)
    result = invoke(renderer_runtime, arguments, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"PASS: (\d+) renderer GL calls, real generated ARM guest imports/pointer loader, broken GL negative", result.stdout)
    assert match and int(match.group(1)) >= 90
    assert "PASS: removed unavailable weapon owner API and prototype-only negative" in result.stdout
    assert "Relocatable partial link only" in result.stdout


@pytest.mark.parametrize("failure", ["missing-compiler", "missing-linker", "compiler-directory", "linker-directory",
                                    "missing-sdk", "missing-sdl", "incomplete-sdl"])
def test_actual_renderer_cli_reports_tool_and_header_failures_without_traceback(renderer_runtime, tmp_path, failure):
    _, _, cc, ld, *_ = renderer_runtime
    arguments = ["--cc", str(cc), "--ld", str(ld), *headers(renderer_runtime)]
    if failure == "missing-compiler":
        arguments[1] = "halo-test-no-such-compiler"
        diagnostic = "C compiler was not found: halo-test-no-such-compiler"
    elif failure == "missing-linker":
        arguments[3] = "halo-test-no-such-linker"
        diagnostic = "GNU LLD linker was not found: halo-test-no-such-linker"
    elif failure in ("compiler-directory", "linker-directory"):
        arguments[1 if failure == "compiler-directory" else 3] = str(tmp_path)
        diagnostic = ("C compiler" if failure == "compiler-directory" else "GNU LLD linker") + " is not an executable file"
    else:
        arguments = arguments[:4] + ["--sdk", str(tmp_path / "no-sdk")]
        if failure == "missing-sdk":
            diagnostic = "Khronos GL headers were not found"
        else:
            arguments += ["--sdl", str(tmp_path / "no-sdl" if failure == "missing-sdl" else tmp_path)]
            diagnostic = "SDL GL declarations are unavailable"
    result = invoke(renderer_runtime, arguments)
    assert result.returncode == 2 and diagnostic in result.stderr
    assert "Traceback" not in result.stderr
    assert "PASS:" not in result.stdout
