"""Fully link the shipped native ARM64 VR build without retail game data.

Run as a regular aarch64 Linux user with rootless Podman. The source pin,
container arguments, local patch and build script come from the installer.
Only a JSON build proof is exported; the temporary game binary is discarded.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MAX_BUILD_SECONDS = 45 * 60
MAX_EXECUTABLE_BYTES = 1024 ** 3


class NativeBuildError(RuntimeError):
    pass


def load_helper():
    spec = importlib.util.spec_from_file_location("native_check_remote_helper", ROOT / "resources/remote_install.py")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    if (not re.fullmatch(r"[a-f0-9]{40}", helper.SOURCE_COMMIT)
            or helper.SOURCE_URL != "https://github.com/startupfoundry/halo-ce-universal.git"):
        raise NativeBuildError("The installer source URL or exact revision is unsupported by this check.")
    return helper


def remaining(deadline, maximum=None):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise NativeBuildError("The native build check exceeded its time limit.")
    return min(seconds, maximum) if maximum is not None else seconds


def command(arguments, deadline, maximum=300):
    return subprocess.run(arguments, check=True, text=True, stdout=subprocess.PIPE,
                          timeout=remaining(deadline, maximum)).stdout.strip()


def regular_file(path, parent):
    """Refuse links or files outside this check's private build workspace."""
    path = Path(path)
    relative = path.relative_to(parent)
    if ".." in relative.parts:
        raise NativeBuildError("The native output path escapes the private workspace.")
    cursor = parent
    if parent.is_symlink() or parent.resolve() != parent:
        raise NativeBuildError("The native build workspace is not an ordinary private directory.")
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            raise NativeBuildError("A native build output path contains a symbolic link.")
    details = path.stat()
    if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
            or details.st_uid != os.getuid() or not 64 <= details.st_size <= MAX_EXECUTABLE_BYTES):
        raise NativeBuildError("The native build did not produce a private ordinary output file.")
    return details


def native_elf_proof(path, parent):
    details = regular_file(path, parent)
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(64)
        if (len(header) != 64 or header[:6] != b"\x7fELF\x02\x01"
                or struct.unpack_from("<H", header, 16)[0] not in (2, 3)
                or struct.unpack_from("<H", header, 18)[0] != 183):
            raise NativeBuildError("The output is not a little-endian ELF64 AArch64 executable/library.")
        checksum.update(header)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    if path.stat().st_size != details.st_size:
        raise NativeBuildError("The native output changed during verification.")
    return {"bytes": details.st_size, "sha256": checksum.hexdigest(),
            "elfMachine": 183, "elfClass": "ELF64", "byteOrder": "little", "architecture": "aarch64"}


def stop_owned_container(helper, identifier):
    """Stop only this invocation's labeled container, never shared containers."""
    name = "halo-frame-installer-" + identifier
    inspected = subprocess.run(["podman", "container", "inspect", name], text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    if inspected.returncode:
        # --rm may already have removed it, or the image pull never created it.
        return
    records = json.loads(inspected.stdout)
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise NativeBuildError("Cannot verify the native check container before cleanup.")
    record = records[0]
    config = record.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    container_id = record.get("Id")
    if (not isinstance(labels, dict) or labels.get("org.halo-frame-installer.owner") != helper.OWNER
            or labels.get("org.halo-frame-installer.run") != identifier
            or not isinstance(container_id, str) or not re.fullmatch(r"[a-f0-9]{64}", container_id)):
        raise NativeBuildError("Refusing to stop a container without this check's exact ownership labels.")
    # The immutable inspected ID avoids a name being reassigned during cleanup.
    subprocess.run(["podman", "stop", "--time", "10", container_id],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    subprocess.run(["podman", "rm", "--force", container_id],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def build_container(helper, identifier, directory, deadline):
    args = helper.build_container_args(identifier, directory)
    process = subprocess.Popen(args, start_new_session=True)
    try:
        status = process.wait(timeout=remaining(deadline))
        if status:
            raise NativeBuildError(f"The shipped native ARM64 VR build failed (exit {status}).")
    except BaseException:
        try:
            stop_owned_container(helper, identifier)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print("Owned container cleanup: " + str(error), file=sys.stderr, flush=True)
        finally:
            # Includes a still-running image pull before a container exists.
            helper.stop_build_process(process)
        raise


def write_proof(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "native-build-proof.json")
    parser.add_argument("--timeout-seconds", type=int, default=MAX_BUILD_SECONDS)
    options = parser.parse_args(argv)
    if not 1 <= options.timeout_seconds <= MAX_BUILD_SECONDS:
        parser.error("--timeout-seconds must be between 1 and 2700 (45 minutes)")
    if sys.platform != "linux" or os.getuid() == 0:
        raise NativeBuildError("Run this check as a regular Linux user with rootless Podman.")
    if platform.machine().lower() not in ("aarch64", "arm64"):
        raise NativeBuildError("This full native build check requires an AArch64 Linux runner.")
    if any(shutil.which(tool) is None for tool in ("git", "podman")):
        raise NativeBuildError("The native build check requires Git and rootless Podman.")
    report = options.report.absolute()
    if report.suffix.lower() != ".json" or report.exists() or report.is_symlink():
        raise NativeBuildError("Choose a new JSON proof path so a stale report cannot imply build success.")
    started = time.monotonic()
    deadline = started + options.timeout_seconds
    helper = load_helper()
    info = json.loads(command(["podman", "info", "--format", "json"], deadline, 60))
    if not info.get("host", {}).get("security", {}).get("rootless", False):
        raise NativeBuildError("This check requires rootless Podman.")
    patch = ROOT / "resources/frame-controls.patch"
    script = ROOT / "resources/build-native.sh"
    patch_bytes, script_bytes = patch.read_bytes(), script.read_bytes()
    helper_sha = hashlib.sha256((ROOT / "resources/remote_install.py").read_bytes()).hexdigest()
    identifier = uuid.uuid4().hex
    print("Full native ARM64 VR link check: " + helper.SOURCE_COMMIT, flush=True)
    with tempfile.TemporaryDirectory(prefix="halo-native-link-check-") as scratch:
        directory = Path(scratch).resolve()
        source = directory / "src"
        command(["git", "init", str(source)], deadline, 30)
        command(["git", "-C", str(source), "remote", "add", "origin", helper.SOURCE_URL], deadline, 30)
        command(["git", "-C", str(source), "fetch", "--depth", "1", "origin", helper.SOURCE_COMMIT], deadline)
        command(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"], deadline, 30)
        if command(["git", "-C", str(source), "rev-parse", "HEAD"], deadline, 30) != helper.SOURCE_COMMIT:
            raise NativeBuildError("The fetched native engine does not match the shipped source pin.")
        staged_patch = directory / "frame-controls.patch"
        staged_patch.write_bytes(patch_bytes)
        command(["git", "-C", str(source), "apply", "--check", str(staged_patch)], deadline, 30)
        command(["git", "-C", str(source), "apply", str(staged_patch)], deadline, 30)
        (directory / "build-native.sh").write_bytes(script_bytes)
        build_container(helper, identifier, directory, deadline)
        binary = native_elf_proof(source / "build/linux_arm64/halo", directory)
        library = native_elf_proof(source / "build/linux_arm64/libSDL3.so.0", directory)
        proof = {"schemaVersion": 1, "result": "passed", "sourceUrl": helper.SOURCE_URL,
                 "sourceCommit": helper.SOURCE_COMMIT,
                 "buildContainerImage": helper.BUILD_CONTAINER_IMAGE,
                 "patchSha256": hashlib.sha256(patch_bytes).hexdigest(),
                 "buildScriptSha256": hashlib.sha256(script_bytes).hexdigest(),
                 "remoteHelperSha256": helper_sha, "target": "linux_arm64", "vrEnabled": True,
                 "releaseBuild": True, "fullNativeLink": True, "rootless": True,
                 "hostArchitecture": platform.machine(), "nativeExecutable": binary,
                 "sdlLibrary": library, "elapsedSeconds": round(time.monotonic() - started, 1),
                 "hardwareValidated": False, "retailGameDataUsed": False}
        write_proof(report, proof)
    print(json.dumps(proof, separators=(",", ":")), flush=True)
    return 0


def interrupted(signum, frame):
    raise NativeBuildError("The native build check was interrupted; stopping its owned container.")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except (NativeBuildError, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print("Native build check failed: " + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
