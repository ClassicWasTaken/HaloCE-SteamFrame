#!/usr/bin/env python3
"""Installer helper executed on the Frame; no host-side elevated commands."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import pathlib
import platform
import pwd
import re
import signal
import shutil
import struct
import subprocess
import sys
import time
import tomllib

OWNER = "halo-frame-installer"
SOURCE_URL = "https://github.com/startupfoundry/halo-ce-universal.git"
SOURCE_COMMIT = "88142798513ebd99fc7c6224023e8b44c05d0106"
MIN_FREE_BYTES = 12 * 1024 ** 3
EXPECTED_MAPS = frozenset("maps/" + name + ".map" for name in (
    "a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40",
    "beavercreek", "bloodgulch", "boardingaction", "carousel", "chillout", "damnation",
    "hangemhigh", "longest", "prisoner", "putput", "ratrace", "sidewinder", "ui", "wizard"))
SUPPORTED_BUILDS = frozenset(("01.01.14.2342", "01.10.12.2276", "01.08.15.1749"))
MAX_MAP_BYTES = 0x11600000
MAX_TOTAL_BYTES = 4 * 1024 ** 3
HOME = pathlib.Path("/home/steamos")
CACHE = HOME / ".cache/halo-frame-installer"
GAME = HOME / "Games/HaloCENativeVR"
MARKER = ".halo-frame-installer.json"


def progress(stage, message):
    print("HFI_PROGRESS " + json.dumps({"stage": stage, "message": message}), flush=True)


def result(value):
    print("HFI_RESULT " + json.dumps(value), flush=True)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ordinary(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected an ordinary file: " + str(path))
    return path


def beneath(path, parent):
    # Reject any symlink component, including symlinks that point back inside.
    if parent.is_symlink() or parent.resolve() != parent:
        raise ValueError("Installation parent must not be a symbolic link.")
    try:
        relative = path.relative_to(parent)
    except ValueError:
        raise ValueError("Installation path is outside its owned directory.") from None
    if ".." in relative.parts:
        raise ValueError("Parent traversal is not accepted in installation paths.")
    cursor = parent
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise ValueError("Symbolic links are not accepted in installation paths.")
    return path


def read_marker(path, owner=OWNER):
    value = json.loads(ordinary(path).read_text())
    if value.get("owner") != owner:
        raise ValueError("The existing directory belongs to another application.")
    return value


def owned(directory):
    beneath(directory, HOME)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / MARKER
    if marker.exists():
        return read_marker(marker)
    if any(directory.iterdir()):
        raise ValueError("The destination is not empty and has no installer ownership marker: " + str(directory))
    value = {"owner": OWNER, "sourceCommit": SOURCE_COMMIT}
    marker.write_text(json.dumps(value, indent=2) + "\n")
    return value


def run_id(value):
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid installation run identifier.")
    return value


def run_dir(value):
    read_marker(CACHE / MARKER)
    directory = beneath(CACHE / "runs" / run_id(value), CACHE)
    return directory


def command(argv, cwd=None, cancel_check=None, timeout=120):
    process = subprocess.Popen(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    started = time.monotonic()
    try:
        while True:
            if cancel_check is not None:
                cancel_check()
            try:
                output, _ = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started > timeout:
                    raise RuntimeError("Remote command timed out: " + argv[0])
    except BaseException:
        stop_build_process(process)
        raise
    if process.returncode:
        raise RuntimeError(output[-10000:].strip() or f"Command failed: {argv[0]}")
    return output.strip()


def elf_arm64(path):
    with ordinary(path).open("rb") as stream:
        header = stream.read(64)
    if len(header) < 64 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != 183:
        raise ValueError("The game executable is not a native little-endian ARM64 ELF.")


def game_closed():
    for item in pathlib.Path("/proc").iterdir():
        if not item.name.isdecimal():
            continue
        try:
            executable = os.readlink(item / "exe").removesuffix(" (deleted)")
            if executable == str(GAME / "halo"):
                raise ValueError("Halo is still running. Save and close the game before installing or repairing it.")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue


def installed_maps_manifest():
    path = GAME / "xbox-data-manifest.json"
    if path.exists():
        value = json.loads(ordinary(path).read_text())
    else:
        maps = beneath(GAME / "maps", GAME)
        if not maps.is_dir():
            raise ValueError("The existing game has no Xbox maps directory.")
        entries = []
        for relative in sorted(EXPECTED_MAPS):
            target = ordinary(beneath(GAME / relative, GAME))
            entries.append({"path": relative, "size": target.stat().st_size, "sha256": digest(target)})
        value = {"files": entries, "totalBytes": sum(item["size"] for item in entries)}
    verify_maps(GAME, value, allow_extra=True)
    return value


def existing_install(repair=False, adopt=False):
    beneath(GAME, HOME)
    if not GAME.exists():
        return None
    if not GAME.is_dir():
        raise ValueError("The game destination is not a directory.")
    own = GAME / MARKER
    codex = GAME / ".codex-halo-native-install.json"
    if own.exists():
        value = read_marker(own)
        source = value.get("sourceCommit")
    elif codex.exists():
        value = read_marker(codex, "codex-halo-native-frame-20261005")
        source = value.get("build", {}).get("sourceCommit", value.get("sourceCommit"))
    else:
        if not repair or not adopt:
            raise ValueError("An existing HaloCENativeVR folder has no recognized native-install marker. Use Repair installed game to explicitly adopt a verified manual native installation.")
        elf_arm64(GAME / "halo")
        elf_arm64(GAME / "libSDL3.so.0")
        installed_maps_manifest()
        value = {"owner": "manual-native-adoption", "files": {}}
        source = None
    if source != SOURCE_COMMIT and not repair:
        raise ValueError("An existing native game uses a different source revision. It was not modified.")
    if repair:
        game_closed()
    else:
        elf_arm64(GAME / "halo")
        ordinary(GAME / "libSDL3.so.0")
    if (GAME / "config.toml").exists():
        ordinary(GAME / "config.toml")
        if repair:
            merge_config((GAME / "config.toml").read_text())
    # Validate all hashes recorded by either supported installer before reusing it.
    files = value.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("The existing native ownership marker has an invalid file record.")
    if not repair and (not isinstance(files, dict) or any(not re.fullmatch("[a-f0-9]{64}", str(files.get(name, "")))
                                          for name in ("halo", "libSDL3.so.0"))):
        raise ValueError("The existing native marker lacks executable/library verification hashes.")
    issues = []
    for relative, expected in files.items():
        if isinstance(expected, str):
            path = beneath(GAME / relative, GAME)
            if not path.exists() or digest(ordinary(path)) != expected:
                # Runtime rewrites config comments/defaults, so its stored hash can differ.
                if relative != "config.toml" and not repair:
                    raise ValueError("An existing native game file failed verification: " + relative)
                issues.append(relative)
    try:
        installed_maps_manifest()
        maps_verified = True
    except (OSError, ValueError, KeyError):
        if not repair:
            raise
        maps_verified = False
    return {"gamePath": str(GAME), "reused": True, "owner": value["owner"], "sourceCommit": source,
            "mapsVerified": maps_verified, "needsImage": not maps_verified, "programIssues": issues}


def os_release():
    values = {}
    for line in pathlib.Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            values[key] = val.strip('"')
    return values


def preflight(repair=False, adopt=False):
    if pwd.getpwuid(os.getuid()).pw_name != "steamos" or pathlib.Path.home() != HOME:
        raise ValueError("Connect using the Frame's steamos account.")
    if platform.machine().lower() not in ("aarch64", "arm64"):
        raise ValueError("This is not an ARM64 Steam Frame. Desktop/Quest installs are not supported.")
    system = os_release()
    if system.get("ID") != "steamos":
        raise ValueError("This installer requires SteamOS on Steam Frame.")
    for executable in ("python3", "git", "podman", "ldd"):
        if shutil.which(executable) is None:
            raise ValueError("Required SteamOS tool is missing: " + executable + ". This installer does not modify SteamOS system packages.")
    vr_manifest = HOME / ".config/openxr/1/active_runtime.json"
    candidates = [vr_manifest, pathlib.Path("/opt/steamvr/steamxr_linuxarm64.json")]
    supported_runtime = False
    for candidate in candidates:
        if candidate.is_file():
            try:
                info = json.loads(candidate.read_text())
                library = pathlib.Path(info["runtime"]["library_path"])
                if not library.is_absolute():
                    library = candidate.resolve().parent / library
                if library.is_file() and "linuxarm64" in str(library):
                    supported_runtime = True
                    break
            except (OSError, ValueError, KeyError, TypeError):
                continue
    if not supported_runtime:
        raise ValueError("SteamVR's ARM64 OpenXR runtime was not found. Run SteamVR on the Frame once, then retry.")
    owned(CACHE)
    beneath(CACHE / "resources", CACHE).mkdir(exist_ok=True)
    beneath(CACHE / "resources/artwork", CACHE).mkdir(exist_ok=True)
    beneath(CACHE / "runs", CACHE).mkdir(exist_ok=True)
    for name in ("remote_install.py", "build-native.sh", "steam_shortcut.py", "frame-controls.patch",
                 "artwork/halo-ce-cover.jpg", "artwork/halo-ce-landscape.png"):
        candidate = beneath(CACHE / "resources" / name, CACHE)
        if candidate.exists() and (not candidate.is_file() or candidate.stat().st_nlink != 1 or candidate.stat().st_uid != os.getuid()):
            raise ValueError("An installer resource path is not a private ordinary file.")
    existing = existing_install(repair, adopt)
    free = shutil.disk_usage(HOME).free
    if (existing is None or repair) and free < MIN_FREE_BYTES:
        raise ValueError("At least 12 GiB of free space is needed for the Xbox data and isolated build. Free space and retry.")
    # Podman itself is unprivileged. Never use sudo or disable SteamOS read-only protection.
    podman = json.loads(command(["podman", "info", "--format", "json"]))
    if not podman.get("host", {}).get("security", {}).get("rootless", False):
        raise ValueError("Podman must run rootless as steamos.")
    return {"home": str(HOME), "cachePath": str(CACHE), "gamePath": str(GAME),
            "architecture": platform.machine(), "freeBytes": free, "existing": existing,
            "pcVersionDetected": (HOME / "Games/HaloCEVR").is_dir(),
            "steamOSVersion": system.get("VERSION_ID", "unknown")}


def prepare(value, use_existing_maps=False, repair=False, adopt=False):
    directory = run_dir(value)
    owned(directory)
    for relative in ("upload", "upload/maps", "stage"):
        path = beneath(directory / relative, directory)
        path.mkdir(exist_ok=True)
    metadata = read_marker(directory / MARKER)
    if use_existing_maps:
        current = existing_install(repair, adopt)
        if not current or not current["mapsVerified"]:
            raise ValueError("The existing native Xbox maps must verify before reuse.")
        manifest = installed_maps_manifest()
        (directory / "upload/xbox-data-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    metadata["mapsOrigin"] = "existing" if use_existing_maps else "upload"
    metadata["repair"] = repair
    metadata["adopt"] = adopt
    (directory / MARKER).write_text(json.dumps(metadata, indent=2) + "\n")
    return {"runPath": str(directory), "uploadPath": str(directory / "upload")}


def verify_maps(directory, manifest, check_cancelled=lambda: None, allow_extra=False):
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 24:
        raise ValueError("The Xbox data manifest must contain exactly 24 supported map files.")
    if {entry.get("path") for entry in files} != EXPECTED_MAPS:
        raise ValueError("The Xbox data manifest does not contain the 24 expected original Xbox maps.")
    map_dir = beneath(directory / "maps", directory)
    actual_paths = {"maps/" + item.name for item in map_dir.iterdir()} if map_dir.is_dir() else set()
    if not map_dir.is_dir() or (not EXPECTED_MAPS.issubset(actual_paths) if allow_extra else actual_paths != EXPECTED_MAPS):
        raise ValueError("The Xbox maps directory contains extra or missing files.")
    seen = set()
    builds = set()
    total = 0
    for entry in files:
        check_cancelled()
        relative = entry.get("path", "")
        parts = pathlib.PurePosixPath(relative)
        if parts.is_absolute() or ".." in parts.parts or str(parts) != relative or relative not in EXPECTED_MAPS or relative in seen:
            raise ValueError("Invalid or duplicate Xbox map path.")
        expected = entry.get("sha256", "")
        if not re.fullmatch("[a-f0-9]{64}", expected):
            raise ValueError("Invalid Xbox map SHA256.")
        target = beneath(directory / relative, directory)
        ordinary(target)
        if not 2048 <= target.stat().st_size <= MAX_MAP_BYTES:
            raise ValueError("Xbox cache file is outside supported bounds: " + relative)
        with target.open("rb") as stream:
            header = stream.read(2048)
        if len(header) != 2048 or header[:4] != b"daeh" or header[-4:] != b"toof" or struct.unpack_from("<I", header, 4)[0] != 5:
            raise ValueError("Xbox cache header verification failed: " + relative)
        if not 2048 <= struct.unpack_from("<I", header, 8)[0] <= MAX_MAP_BYTES:
            raise ValueError("Xbox declared cache length is outside supported bounds: " + relative)
        build_string = header[64:96].split(b"\0", 1)[0].decode("ascii")
        if build_string not in SUPPORTED_BUILDS:
            raise ValueError("Unsupported original Xbox Halo build: " + build_string)
        builds.add(build_string)
        if target.stat().st_size != entry["size"] or digest(target) != expected:
            raise ValueError("Xbox data verification failed: " + relative)
        seen.add(relative)
        total += entry["size"]
    check_cancelled()
    if len(builds) != 1:
        raise ValueError("Xbox maps mix multiple retail builds.")
    if manifest.get("totalBytes") != total or not 0 < total <= MAX_TOTAL_BYTES:
        raise ValueError("Xbox data total does not match the manifest.")
    return total


def build(value, repair=False, adopt=False):
    directory = run_dir(value)
    metadata = read_marker(directory / MARKER)
    if existing_install(repair, adopt) and not repair:
        return {"reused": True}
    upload = directory / "upload"
    def check_cancelled():
        if (directory / "cancelled").exists():
            raise RuntimeError("Build cancelled. Existing games and saves were kept.")
    check_cancelled()
    manifest = json.loads(ordinary(upload / "xbox-data-manifest.json").read_text())
    progress("verify", "Verifying the uploaded Xbox maps...")
    verify_maps(GAME if metadata.get("mapsOrigin") == "existing" else upload, manifest, check_cancelled,
                allow_extra=metadata.get("mapsOrigin") == "existing")
    source = directory / "src"
    if source.exists():
        raise ValueError("A source checkout already exists for this run. Retry with a fresh run.")
    progress("source", "Fetching the pinned native VR source from GitHub...")
    command(["git", "init", str(source)], cancel_check=check_cancelled)
    check_cancelled()
    command(["git", "-C", str(source), "remote", "add", "origin", SOURCE_URL], cancel_check=check_cancelled)
    check_cancelled()
    command(["git", "-C", str(source), "fetch", "--depth", "1", "origin", SOURCE_COMMIT], cancel_check=check_cancelled, timeout=300)
    check_cancelled()
    command(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"], cancel_check=check_cancelled)
    check_cancelled()
    if command(["git", "-C", str(source), "rev-parse", "HEAD"], cancel_check=check_cancelled) != SOURCE_COMMIT:
        raise ValueError("Source pin verification failed.")
    patch = ordinary(CACHE / "resources/frame-controls.patch")
    command(["git", "-C", str(source), "apply", "--check", str(patch)], cancel_check=check_cancelled)
    command(["git", "-C", str(source), "apply", str(patch)], cancel_check=check_cancelled)
    check_cancelled()
    script = ordinary(CACHE / "resources/build-native.sh")
    shutil.copy2(script, directory / "build-native.sh")
    container = "halo-frame-installer-" + value
    progress("build", "Preparing and compiling the native ARM64 VR game in an isolated container. This may take 10–30 minutes...")
    log = directory / "native-build.log"
    args = ["podman", "run", "--rm", "--name", container,
            "--label", "org.halo-frame-installer.owner=" + OWNER,
            "--label", "org.halo-frame-installer.run=" + value,
            "--userns=keep-id:uid=0,gid=0", "--security-opt=no-new-privileges",
            "--volume", str(directory) + ":/build:rw", "--workdir", "/build",
            "docker.io/library/ubuntu:22.04", "/bin/bash", "/build/build-native.sh"]
    with log.open("wb") as output:
        check_cancelled()
        process = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        last_status = time.monotonic()
        try:
            while process.poll() is None:
                if (directory / "cancelled").exists():
                    cancel(value)
                    stop_build_process(process)
                    raise RuntimeError("Build cancelled. Existing games and saves were kept.")
                if time.monotonic() - last_status > 15:
                    # User sees steady status; detailed dependency/compiler output stays on the Frame.
                    progress("build", "Native build is running. Detailed log: " + str(log))
                    last_status = time.monotonic()
                time.sleep(1)
        except BaseException:
            try:
                cancel(value)
            finally:
                stop_build_process(process)
            raise
    if process.returncode:
        tail = log.read_text(errors="replace")[-12000:]
        raise RuntimeError("Native build failed. The existing game was kept.\n" + tail)
    binary = source / "build/linux_arm64/halo"
    elf_arm64(binary)
    ordinary(source / "build/linux_arm64/libSDL3.so.0")
    return {"built": True, "binarySha256": digest(binary), "logPath": str(log)}


def stop_build_process(process):
    """Reap this helper's supervised Podman process, including a pre-container pull."""
    if process.poll() is not None:
        return
    # start_new_session established a private process group for this child only.
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        process.wait(timeout=10)
        return
    if group != process.pid:
        raise ValueError("Build process is no longer in its owned private process group.")
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=10)
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.getpgid(process.pid) != process.pid:
            raise ValueError("Build process group changed during cancellation.")
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def cancel(value):
    directory = run_dir(value)
    read_marker(directory / MARKER)
    (directory / "cancelled").touch()
    container = "halo-frame-installer-" + value
    check = subprocess.run(["podman", "container", "inspect", container],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
    if check.returncode == 0:
        info = json.loads(check.stdout)[0]
        labels = info.get("Config", {}).get("Labels", {})
        if labels.get("org.halo-frame-installer.owner") != OWNER or labels.get("org.halo-frame-installer.run") != value:
            raise ValueError("Refusing to stop an unowned container.")
        command(["podman", "stop", "--time", "10", container])
    return {"cancelled": True}


def merge_config(original):
    """Restore required native controls while preserving unrelated TOML settings."""
    settings = tomllib.loads(original) if original.strip() else {}
    required = {"vr": {"enabled": True, "aim": "controller", "melee_gesture": False},
                "update": {"auto": False}}
    defaults = {"refresh_rate": 72.0, "resolution_scale": 1.0, "turn": "smooth",
                "smooth_turn_speed": 90.0, "two_handed": True, "height": "seated", "depth": False}
    vr = settings.get("vr", {})
    for key, default in defaults.items():
        if key not in vr:
            required["vr"][key] = default
    lines = original.splitlines()
    for section, changes in required.items():
        headers = [(i, match.group(1).strip()) for i, line in enumerate(lines)
                   if (match := re.match(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$", line))]
        start = next((i for i, name in headers if name == section), None)
        if start is None:
            if lines and lines[-1]:
                lines.append("")
            lines.append("[" + section + "]")
            start = len(lines) - 1
        boundaries = [i for i, line in enumerate(lines) if re.match(r"^\s*\[.+\]", line)]
        end = next((i for i in boundaries if i > start), len(lines))
        remaining = dict(changes)
        for i in range(start + 1, end):
            match = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", lines[i])
            if match and match.group(1) in remaining:
                key = match.group(1)
                lines[i] = key + " = " + json.dumps(remaining.pop(key))
        lines[end:end] = [key + " = " + json.dumps(val) for key, val in remaining.items()]
    combined = "\n".join(lines) + "\n"
    updated = tomllib.loads(combined)
    if any(updated.get(section, {}).get(key) != value for section, changes in required.items() for key, value in changes.items()):
        raise ValueError("This TOML formatting cannot be safely updated automatically. Your original configuration was kept.")
    for section, value in settings.items():
        if section not in required:
            if updated.get(section) != value:
                raise ValueError("Configuration update would change unrelated settings. Your original configuration was kept.")
        else:
            for key, original_value in value.items():
                if key not in required[section] and updated[section].get(key) != original_value:
                    raise ValueError("Configuration update would change unrelated settings. Your original configuration was kept.")
    return combined


def repair_program_files(stage, directory, names, check_cancelled):
    """Back up then atomically replace each selected file; roll back on any failure."""
    game_closed()
    backup = beneath(directory / "previous-program-files", directory)
    backup.mkdir(exist_ok=False)
    (backup / ".backup-owner.json").write_text(json.dumps({"owner": OWNER, "sourceCommit": SOURCE_COMMIT}) + "\n")
    snapshot = []
    for relative in names:
        check_cancelled()
        target = beneath(GAME / relative, GAME)
        fresh = beneath(stage / relative, stage)
        ordinary(fresh)
        saved = beneath(backup / relative, backup)
        saved.parent.mkdir(parents=True, exist_ok=True)
        old_hash = None
        if target.exists():
            ordinary(target)
            old_hash = digest(target)
            shutil.copy2(target, saved)
            if digest(saved) != old_hash:
                raise ValueError("The existing game changed while backing up: " + relative)
        snapshot.append((relative, old_hash, digest(fresh)))
    applied = []
    try:
        for relative, old_hash, new_hash in snapshot:
            check_cancelled()
            game_closed()
            target = beneath(GAME / relative, GAME)
            actual = digest(ordinary(target)) if target.exists() else None
            if actual != old_hash:
                raise ValueError("The existing game changed during repair: " + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / relative, target)
            applied.append((relative, old_hash, new_hash))
        for relative, _, expected in snapshot:
            if digest(GAME / relative) != expected:
                raise ValueError("A repaired program file failed verification: " + relative)
        check_cancelled()
    except BaseException as error:
        failures = []
        for relative, old_hash, _ in reversed(applied):
            target = GAME / relative
            try:
                if old_hash is None:
                    target.unlink()
                else:
                    os.replace(backup / relative, target)
            except OSError:
                failures.append(relative)
        if failures:
            raise RuntimeError("Repair failed and some files could not be restored: " + ", ".join(failures) + ". Original files remain in " + str(backup)) from error
        raise
    return str(backup)


def finalize(value, repair=False, adopt=False):
    directory = run_dir(value)
    run_metadata = read_marker(directory / MARKER)
    def check_cancelled():
        if (directory / "cancelled").exists():
            raise ValueError("This run was cancelled. Existing games and saves were kept.")
    check_cancelled()
    existing = existing_install(repair, adopt)
    if existing and not repair:
        return existing
    source = directory / "src"
    binary = source / "build/linux_arm64/halo"
    elf_arm64(binary)
    stage = beneath(directory / "stage", directory)
    if any(stage.iterdir()):
        raise ValueError("Staging contains unfinished files. Start a fresh installation.")
    progress("install", "Staging and verifying the game before adding it to your library...")
    shutil.copy2(binary, stage / "halo")
    (stage / "halo").chmod(0o755)
    shutil.copy2(ordinary(source / "build/linux_arm64/libSDL3.so.0"), stage / "libSDL3.so.0")
    upload = directory / "upload"
    manifest = json.loads(ordinary(upload / "xbox-data-manifest.json").read_text())
    reuse_maps = run_metadata.get("mapsOrigin") == "existing"
    verify_maps(GAME if reuse_maps else upload, manifest, check_cancelled, allow_extra=reuse_maps)
    if not existing or not reuse_maps:
        (stage / "maps").mkdir()
        for entry in manifest["files"]:
            check_cancelled()
            path = beneath(upload / entry["path"], upload)
            shutil.copy2(ordinary(path), stage / entry["path"])
    shutil.copy2(upload / "xbox-data-manifest.json", stage / "xbox-data-manifest.json")
    if not existing or not reuse_maps:
        verify_maps(stage, manifest, check_cancelled)
    if not existing:
        (stage / "save").mkdir()
    config = ('[paths]\ndata = "' + str(GAME) + '"\nsaves = "' + str(GAME / "save") + '"\n\n'
              '[update]\nauto = false\n\n[network]\nonline = true\n\n'
              '[vr]\nenabled = true\nrefresh_rate = 72.0\nresolution_scale = 1.0\n'
              'aim = "controller"\nturn = "smooth"\nsmooth_turn_speed = 90.0\n'
              'melee_gesture = false\ntwo_handed = true\nheight = "seated"\ndepth = false\n')
    if existing:
        original = ordinary(GAME / "config.toml").read_text() if (GAME / "config.toml").exists() else ""
        config = merge_config(original)
    (stage / "config.toml").write_text(config)
    shutil.copy2(CACHE / "resources/frame-controls.patch", stage / "frame-controls.patch")
    notices = {
        "LICENSE.md": "UPSTREAM-LICENSE.md",
        "port/third_party/mbedtls/LICENSE": "mbedtls-LICENSE.txt",
        "port/third_party/miniupnpc/LICENSE": "miniupnpc-LICENSE.txt",
        "port/third_party/expat/COPYING": "expat-COPYING.txt",
        "port/third_party/extract-xiso/LICENSE.TXT": "extract-xiso-LICENSE.txt",
        "port/assets/fonts/Overpass-OFL.txt": "Overpass-OFL.txt",
        "build/linux_arm64/third_party/SDL3/LICENSE.txt": "SDL3-LICENSE.txt",
        "build/linux_arm64/third_party/musl-1.2.5/COPYRIGHT": "musl-COPYRIGHT.txt",
        "port/third_party/tomlc17/LICENSE": "tomlc17-LICENSE.txt",
        "port/third_party/stb/LICENSE": "stb-LICENSE.txt",
        "port/third_party/musl-math/COPYRIGHT": "musl-math-COPYRIGHT.txt",
        "port/third_party/monocypher/LICENCE.md": "monocypher-LICENCE.md",
        "port/third_party/kcp/LICENSE": "kcp-LICENSE.txt",
    }
    for relative, name in notices.items():
        notice = source / relative
        if notice.is_file():
            shutil.copy2(notice, stage / name)
    libs = command(["ldd", str(stage / "halo")])
    if "not found" in libs:
        raise ValueError("A required native runtime library is missing:\n" + libs)
    metadata = {"owner": OWNER, "version": 1, "sourceCommit": SOURCE_COMMIT,
                "sourceUrl": SOURCE_URL, "architecture": "native ARM64 ELF64 / ILP32 AArch64 guest",
                "files": {name: digest(stage / name) for name in ("halo", "libSDL3.so.0", "frame-controls.patch")},
                "maps": {"files": 24, "bytes": manifest["totalBytes"]},
                "controls": "Xbox buttons, motion aim, LB grenade change, RB flashlight",
                "buildLog": str(directory / "native-build.log")}
    (stage / MARKER).write_text(json.dumps(metadata, indent=2) + "\n")
    if existing:
        names = [item.name for item in stage.iterdir() if item.is_file() and item.name != MARKER]
        if not reuse_maps:
            names += [item["path"] for item in manifest["files"]]
        # Publish the ownership/provenance marker last; saves and all other files stay put.
        names.append(MARKER)
        backup = repair_program_files(stage, directory, names, check_cancelled)
        return {"gamePath": str(GAME), "reused": False, "repaired": True,
                "sourceCommit": SOURCE_COMMIT, "backupPath": backup, "mapsReinstalled": not reuse_maps}
    beneath(GAME.parent, HOME).mkdir(exist_ok=True)
    if GAME.exists() or GAME.is_symlink():
        raise ValueError("The game destination appeared during installation. It was not modified.")
    if stage.stat().st_dev != GAME.parent.stat().st_dev:
        raise ValueError("Game and staging must be on the same filesystem for atomic installation.")
    check_cancelled()
    rename_noreplace(stage, GAME)
    return {"gamePath": str(GAME), "reused": False, "sourceCommit": SOURCE_COMMIT}


def rename_noreplace(source, target):
    """Publish atomically without replacing even a concurrently created empty folder."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError:
        raise RuntimeError("This SteamOS libc has no renameat2; atomic no-overwrite installation is unavailable.") from None
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def shortcut(close_steam=False):
    current = existing_install()
    if current is None:
        raise ValueError("Install and verify the native game before adding it to Steam.")
    sys.path.insert(0, str(CACHE / "resources"))
    from steam_shortcut import add_native_shortcut
    return add_native_shortcut(HOME, GAME, close_steam=close_steam)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("preflight", "prepare", "build", "finalize", "cancel", "shortcut"))
    parser.add_argument("--run-id")
    parser.add_argument("--close-steam", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--adopt-existing", action="store_true")
    parser.add_argument("--use-existing-maps", action="store_true")
    args = parser.parse_args()
    if args.step in ("prepare", "build", "finalize", "cancel") and args.run_id is None:
        parser.error("--run-id is required")
    functions = {"preflight": lambda: preflight(args.repair, args.adopt_existing),
                 "prepare": lambda: prepare(args.run_id, args.use_existing_maps, args.repair, args.adopt_existing),
                 "build": lambda: build(args.run_id, args.repair, args.adopt_existing),
                 "finalize": lambda: finalize(args.run_id, args.repair, args.adopt_existing),
                 "cancel": lambda: cancel(args.run_id), "shortcut": lambda: shortcut(args.close_steam)}
    result(functions[args.step]())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print("HFI_ERROR " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
