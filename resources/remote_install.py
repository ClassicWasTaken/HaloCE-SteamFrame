#!/usr/bin/env python3
"""Installer helper executed on the Frame; no host-side elevated commands."""
from __future__ import annotations

import argparse
import codecs
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
import stat
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
MAX_MANIFEST_BYTES = 64 * 1024
MAX_RETRY_RUNS = 32
MAX_RETRY_ENTRIES = 256
HOME = pathlib.Path("/home/steamos")
CACHE = HOME / ".cache/halo-frame-installer"
GAME = HOME / "Games/HaloCENativeVR"
MARKER = ".halo-frame-installer.json"


def progress(stage, message, percent=None):
    value = {"stage": stage, "message": message}
    if percent is not None:
        if type(percent) not in (int, float) or not 0 <= percent <= 100:
            raise ValueError("Build progress must be a percentage between 0 and 100.")
        value["percent"] = percent
    print("HFI_PROGRESS " + json.dumps(value), flush=True)


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


def game_closed(extra_executables=()):
    executables = {str(GAME / "halo"), *(str(path) for path in extra_executables)}
    for item in pathlib.Path("/proc").iterdir():
        if not item.name.isdecimal():
            continue
        try:
            executable = os.readlink(item / "exe").removesuffix(" (deleted)")
            if executable in executables:
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
    for name in ("remote_install.py", "build-native.sh", "steam_shortcut.py", "steam_live.py", "steam_notes.py", "frame-controls.patch",
                 "artwork/halo-ce-cover.jpg", "artwork/halo-ce-landscape.png", "artwork/halo-ce-hero.jpg",
                 "artwork/halo-ce-logo.png", "artwork/halo-ce-icon.png"):
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
            "retainedUploadReuse": True,
            "pcVersionDetected": (HOME / "Games/HaloCEVR").is_dir(),
            "steamOSVersion": system.get("VERSION_ID", "unknown")}


def preflight_uninstall():
    """Uninstall needs an authenticated Frame, not a healthy game or build tools."""
    if pwd.getpwuid(os.getuid()).pw_name != "steamos" or pathlib.Path.home() != HOME:
        raise ValueError("Connect using the Frame's steamos account.")
    if platform.machine().lower() not in ("aarch64", "arm64") or os_release().get("ID") != "steamos":
        raise ValueError("Uninstall supports the native game on ARM64 SteamOS Steam Frame only.")
    if GAME != HOME / "Games/HaloCENativeVR":
        raise ValueError("Uninstall is restricted to the standard native Halo game folder.")
    owned(CACHE)
    for relative in ("resources", "resources/artwork", "runs"):
        directory = beneath(CACHE / relative, CACHE)
        directory.mkdir(exist_ok=True)
        if not directory.is_dir() or directory.stat().st_uid != os.getuid():
            raise ValueError("An installer resource directory is not owned by this account.")
    for relative in ("remote_install.py", "steam_shortcut.py", "steam_live.py", "steam_notes.py", "artwork/halo-ce-cover.jpg", "artwork/halo-ce-landscape.png",
                     "artwork/halo-ce-hero.jpg", "artwork/halo-ce-logo.png", "artwork/halo-ce-icon.png"):
        path = beneath(CACHE / "resources" / relative, CACHE)
        if path.exists():
            details = ordinary(path).stat()
            if details.st_uid != os.getuid() or details.st_nlink != 1:
                raise ValueError("An uninstall helper resource is not a private ordinary file.")
    return {"home": str(HOME), "cachePath": str(CACHE), "gamePath": str(GAME), "uninstallSupported": True}


def preflight_library():
    """Library updates need the verified game, without compiler prerequisites."""
    info = preflight_uninstall()
    current = existing_install()
    if current is None:
        raise ValueError("Install and verify native Halo VR before updating its Steam information.")
    info.pop("uninstallSupported", None)
    info["existing"] = current
    return info


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


def private_json(path, parent):
    """Read bounded metadata from an ordinary file owned by this account."""
    target = ordinary(beneath(path, parent))
    details = target.stat()
    if details.st_uid != os.getuid() or details.st_nlink != 1 or not 0 < details.st_size <= MAX_MANIFEST_BYTES:
        raise ValueError("Retained upload metadata is not a private bounded ordinary file.")
    with target.open("rb") as stream:
        encoded = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("Retained upload metadata exceeds supported bounds.")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("Retained upload metadata must be an object.")
    return decoded


def map_identity(manifest):
    """Compare selected data by its exact bounded paths, lengths and hashes."""
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != len(EXPECTED_MAPS):
        raise ValueError("The Xbox data manifest must contain exactly 24 supported map files.")
    identity = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid retained Xbox data manifest entry.")
        relative, size, checksum = entry.get("path"), entry.get("size"), entry.get("sha256")
        if (not isinstance(relative, str) or relative not in EXPECTED_MAPS or relative in identity
                or type(size) is not int or not 2048 <= size <= MAX_MAP_BYTES
                or not isinstance(checksum, str) or not re.fullmatch("[a-f0-9]{64}", checksum)):
            raise ValueError("Invalid retained Xbox map identity.")
        identity[relative] = (size, checksum)
    total = sum(size for size, _ in identity.values())
    if (set(identity) != EXPECTED_MAPS or type(manifest.get("totalBytes")) is not int
            or manifest["totalBytes"] != total or not 0 < total <= MAX_TOTAL_BYTES):
        raise ValueError("Retained Xbox data total does not match the manifest.")
    return identity


def retained_upload(value):
    """Resolve one original upload without following cross-run references."""
    directory = run_dir(value)
    if not directory.is_dir() or directory.stat().st_uid != os.getuid():
        raise ValueError("The retained upload run is not an owned directory.")
    marker = private_json(directory / MARKER, directory)
    if (marker.get("owner") != OWNER or marker.get("sourceCommit") != SOURCE_COMMIT
            or marker.get("mapsOrigin") != "upload"):
        raise ValueError("The retained upload has no recognized original-upload marker.")
    upload = beneath(directory / "upload", directory)
    if not upload.is_dir() or upload.stat().st_uid != os.getuid():
        raise ValueError("The retained upload is not an owned directory.")
    manifest = private_json(upload / "xbox-data-manifest.json", upload)
    map_identity(manifest)
    # Reject hard links and files belonging to another account before hashing.
    for relative in EXPECTED_MAPS:
        details = ordinary(beneath(upload / relative, upload)).stat()
        if details.st_uid != os.getuid() or details.st_nlink != 1:
            raise ValueError("A retained Xbox map is not a private ordinary file.")
    return upload, manifest


def maps_source(directory, metadata, manifest):
    """Recheck retained data provenance each time a build or publish reads it."""
    origin = metadata.get("mapsOrigin")
    if origin == "existing":
        return GAME
    if origin == "retained":
        old_run = metadata.get("mapsRun")
        if not isinstance(old_run, str) or old_run == directory.name:
            raise ValueError("Invalid retained upload run reference.")
        upload, previous = retained_upload(old_run)
        if map_identity(previous) != map_identity(manifest):
            raise ValueError("The retained Xbox maps no longer match the selected data.")
        return upload
    if origin != "upload":
        raise ValueError("Unrecognized Xbox map source for this installation run.")
    return beneath(directory / "upload", directory)


def reuse_upload(value):
    """Reuse verified local data from an older attempt, without changing it."""
    directory = run_dir(value)
    metadata = read_marker(directory / MARKER)
    if metadata.get("mapsOrigin") != "upload":
        raise ValueError("Only a fresh upload run can select retained Xbox data.")
    upload = beneath(directory / "upload", directory)
    map_directory = beneath(upload / "maps", upload)
    if any(map_directory.iterdir()):
        raise ValueError("Retained data must be selected before uploading new maps.")
    manifest = private_json(upload / "xbox-data-manifest.json", upload)
    selected = map_identity(manifest)
    def check_cancelled():
        if (directory / "cancelled").exists():
            raise RuntimeError("Installation cancelled. Existing games and saves were kept.")
    check_cancelled()
    runs = beneath(CACHE / "runs", CACHE)
    # Only inspect a bounded number of recognized run names. No prior run is
    # removed, resumed or changed, even if its upload is incomplete or invalid.
    candidates = []
    with os.scandir(runs) as entries:
        for count, entry in enumerate(entries):
            check_cancelled()
            if count >= MAX_RETRY_ENTRIES:
                break
            try:
                if (entry.name != value and re.fullmatch("[a-f0-9]{32}", entry.name)
                        and entry.is_dir(follow_symlinks=False)):
                    candidates.append((entry.stat(follow_symlinks=False).st_mtime_ns, entry.name))
            except OSError:
                continue
    for _, candidate in sorted(candidates, reverse=True)[:MAX_RETRY_RUNS]:
        check_cancelled()
        try:
            old_upload, previous = retained_upload(candidate)
            if map_identity(previous) != selected:
                continue
            progress("reuse", "Checking Xbox maps retained from an earlier installation attempt...")
            verify_maps(old_upload, manifest, check_cancelled)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            continue
        check_cancelled()
        metadata["mapsOrigin"] = "retained"
        metadata["mapsRun"] = candidate
        (directory / MARKER).write_text(json.dumps(metadata, indent=2) + "\n")
        return {"reusedUpload": True, "mapsRun": candidate}
    return {"reusedUpload": False}


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


def build_container_args(value, directory, payload=None):
    # keep-id alone maps steamos to UID 0 but Podman omits effective root
    # capabilities unless the container user is explicit. apt needs those
    # capabilities to switch to _apt and change package-file ownership.
    return ["podman", "run", "--rm", "--name", "halo-frame-installer-" + value,
            "--label", "org.halo-frame-installer.owner=" + OWNER,
            "--label", "org.halo-frame-installer.run=" + value,
            "--userns=keep-id:uid=0,gid=0", "--user=0:0",
            "--security-opt=no-new-privileges",
            "--volume", str(directory) + ":/build:rw", "--workdir", "/build",
            "docker.io/library/ubuntu:22.04",
            *(payload or ["/bin/bash", "/build/build-native.sh"])]


BUILD_PHASES = {
    "build": "Starting the isolated build container",
    "dependencies": "Installing build dependencies",
    "toolchain": "Installing the LLVM 22 compiler",
    "configure": "Configuring the native VR build",
    "sdl": "Configuring and compiling SDL3",
    "compile": "Compiling the native VR game",
    "build-check": "Checking the native build",
}
BUILD_PHASE_ORDER = {stage: index for index, stage in enumerate(BUILD_PHASES)}
MAX_LOG_MESSAGE = 1024
MAX_RAW_LOG_LINE = 8192
LOG_READ_BYTES = 64 * 1024
BUILD_HEARTBEAT_SECONDS = 15
ANSI_ESCAPE = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
    r"|(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)"
    r"|\x1b[@-Z\\-_]|(?:\x1b\[|\x9b)[0-?]*[ -/]*$|(?:\x1b\]|\x9d).*$")
NINJA_COUNTS = re.compile(r"^\[(\d{1,10})/(\d{1,10})\]\s*(.*)$")
BUILD_PHASE_MARKER = re.compile(r"^HFI_BUILD_PHASE ([a-z-]+) (.+)$")


def clean_build_line(value, truncated=False):
    """Keep terminal escape sequences and control characters out of the UI."""
    value = ANSI_ESCAPE.sub("", value).replace("\t", " ")
    value = "".join(character for character in value if character.isprintable()).strip()
    suffix = " ... [line truncated]" if truncated or len(value) > MAX_LOG_MESSAGE else ""
    return value[:MAX_LOG_MESSAGE - len(suffix)] + suffix


def open_build_log(path, directory):
    """Read only private, ordinary generated files beneath this owned run."""
    ordinary(beneath(path, directory))
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        details = os.fstat(descriptor)
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
                or details.st_nlink != 1):
            raise ValueError("A build log is not a private ordinary file owned by this account.")
        return os.fdopen(descriptor, "rb"), details
    except BaseException:
        os.close(descriptor)
        raise


class BuildLogTail:
    """Bounded incremental UTF-8/CR reader; stdout remains a file, never a pipe."""

    def __init__(self, path, directory, callback):
        self.path, self.directory, self.callback = path, directory, callback
        self.identity = None
        self.offset = 0
        self._reset_line()

    def _reset_line(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending = ""
        self.truncated = False

    def _feed(self, encoded, final=False):
        for part in re.split(r"([\r\n])", self.decoder.decode(encoded, final=final)):
            if part in ("\r", "\n"):
                self._emit_line()
            elif part:
                room = MAX_RAW_LOG_LINE - len(self.pending)
                self.pending += part[:room]
                if len(part) > room:
                    self.truncated = True

    def _emit_line(self):
        message = clean_build_line(self.pending, self.truncated)
        self.pending, self.truncated = "", False
        if message:
            self.callback(message)

    def read(self):
        # These three exact paths may not exist until their build phase starts.
        if not self.path.exists() and not self.path.is_symlink():
            return 0
        stream, details = open_build_log(self.path, self.directory)
        with stream:
            identity = (details.st_dev, details.st_ino)
            if identity != self.identity or details.st_size < self.offset:
                self.identity, self.offset = identity, 0
                self._reset_line()
            stream.seek(self.offset)
            encoded = stream.read(LOG_READ_BYTES)
        self.offset += len(encoded)
        self._feed(encoded)
        return len(encoded)

    def finish(self):
        self._feed(b"", final=True)
        self._emit_line()


def build_elapsed(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


class BuildLogMonitor:
    """Report phases and real Ninja completion counts from the three build logs."""

    def __init__(self, directory):
        self.directory = directory
        self.stage = "build"
        self.percent = None
        self.counts = None
        self.sdl_seen = False
        now = time.monotonic()
        self.phase_started = self.last_output = self.last_status = now
        paths = {
            "main": directory / "native-build.log",
            "sdl-configure": directory / "src/build/linux_arm64/sdl3-configure.log",
            "sdl-build": directory / "src/build/linux_arm64/sdl3-build.log",
        }
        self.tails = [BuildLogTail(path, directory, lambda line, name=name: self.line(name, line))
                      for name, path in paths.items()]

    def phase(self, stage, message, percent=None, counts=None):
        # SDL logs can be read after the outer Ninja command has already moved on.
        # Their detail remains visible, but must not move the current phase back.
        if stage not in BUILD_PHASES or BUILD_PHASE_ORDER[stage] < BUILD_PHASE_ORDER[self.stage]:
            return
        changed = stage != self.stage
        if changed:
            self.stage, self.percent, self.counts = stage, None, None
            self.phase_started = time.monotonic()
        if counts is not None:
            self.counts = counts
        if percent is None or changed or percent != self.percent:
            if percent is not None:
                self.percent = percent
            progress(self.stage, message, self.percent)

    def line(self, name, message):
        marker = BUILD_PHASE_MARKER.fullmatch(message) if name == "main" else None
        if marker and marker[1] in BUILD_PHASES:
            self.phase(marker[1], marker[2])
            return
        match = NINJA_COUNTS.fullmatch(message)
        counts = None
        if match:
            completed, total = int(match[1]), int(match[2])
            if 0 <= completed <= total and total:
                counts = (completed, total)
        if name.startswith("sdl-"):
            stage = "sdl"
            if counts:
                completed, total = counts
                self.phase(stage, f"Compiling SDL3: {completed:,} of {total:,} build steps.",
                           completed * 100 // total, counts)
            elif BUILD_PHASE_ORDER[self.stage] < BUILD_PHASE_ORDER[stage]:
                self.phase(stage, BUILD_PHASES[stage] + "...")
        elif match and re.match(r"LINUX ARM64 SDL3\b", match[3]):
            stage = "sdl"
            self.sdl_seen = True
            self.phase(stage, BUILD_PHASES[stage] + "...")
        elif match and counts:
            stage = "compile"
            # Outer Ninja may start guest jobs before its SDL console job. Wait
            # for that job rather than advancing the overall UI prematurely.
            if self.sdl_seen or self.stage == stage:
                completed, total = counts
                self.phase(stage, f"Compiling native game: {completed:,} of {total:,} build steps.",
                           completed * 100 // total, counts)
        else:
            stage = self.stage
        print("HFI_LOG " + json.dumps({"stage": stage, "message": message}), flush=True)

    def poll(self):
        count = sum(tail.read() for tail in self.tails)
        if count:
            self.last_output = time.monotonic()
        return count

    def heartbeat(self):
        now = time.monotonic()
        if now - self.last_status < BUILD_HEARTBEAT_SECONDS:
            return
        counts = f" Last count: {self.counts[0]:,}/{self.counts[1]:,} build steps." if self.counts else ""
        message = (f"{BUILD_PHASES[self.stage]}: phase elapsed {build_elapsed(now - self.phase_started)}; "
                   f"no new build output for {build_elapsed(now - self.last_output)}.{counts} "
                   f"Full log: {self.directory / 'native-build.log'}")
        progress(self.stage, message, self.percent)
        self.last_status = now

    def drain(self):
        # Include buffered last lines even when the child exited before a poll.
        while self.poll():
            pass
        for tail in self.tails:
            tail.finish()


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
    verify_maps(maps_source(directory, metadata, manifest), manifest, check_cancelled,
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
    progress("build", "Starting the isolated ARM64 build container; downloading its image if needed...")
    log = directory / "native-build.log"
    args = build_container_args(value, directory)
    with log.open("wb") as output:
        check_cancelled()
        process = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        monitor = BuildLogMonitor(directory)
        try:
            while process.poll() is None:
                monitor.poll()
                if (directory / "cancelled").exists():
                    cancel(value)
                    stop_build_process(process)
                    raise RuntimeError("Build cancelled. Existing games and saves were kept.")
                monitor.heartbeat()
                time.sleep(0.25)
        except BaseException:
            try:
                cancel(value)
            finally:
                stop_build_process(process)
            raise
        finally:
            output.flush()
            monitor.drain()
    if process.returncode:
        stream, details = open_build_log(log, directory)
        with stream:
            stream.seek(max(0, details.st_size - 12000))
            tail = stream.read(12000).decode("utf-8", errors="replace")
        raise RuntimeError("Native build failed. The existing game was kept.\n" + tail)
    binary = source / "build/linux_arm64/halo"
    progress("build-check", "Verifying the native ARM64 executable and SDL3 library...")
    elf_arm64(binary)
    ordinary(source / "build/linux_arm64/libSDL3.so.0")
    progress("build-check", "Native ARM64 VR build verified.", 100)
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
    map_directory = maps_source(directory, run_metadata, manifest)
    verify_maps(map_directory, manifest, check_cancelled, allow_extra=reuse_maps)
    if not existing or not reuse_maps:
        (stage / "maps").mkdir()
        for entry in manifest["files"]:
            check_cancelled()
            path = beneath(map_directory / entry["path"], map_directory)
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
    response = add_native_shortcut(HOME, GAME, close_steam=close_steam)
    if response.get("status") == "added":
        from steam_notes import add_notes
        response["notes"] = add_notes(HOME, GAME, response["appid"])
    return response


def no_active_build():
    if shutil.which("podman") is None:
        raise ValueError("Podman is unavailable, so an active installer build cannot be checked. The game was kept.")
    try:
        containers = json.loads(command(["podman", "ps", "--filter",
                                         "label=org.halo-frame-installer.owner=" + OWNER,
                                         "--format", "json"], timeout=30))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise ValueError("Could not safely check for an active installer build. The game was kept. " + str(error)) from error
    if not isinstance(containers, list):
        raise ValueError("Podman returned unsupported build status. The game was kept.")
    if containers:
        raise ValueError("An installer build is still running on the Frame. Finish or cancel that build before uninstalling Halo.")


def uninstall_identity():
    beneath(GAME, HOME)
    if not GAME.exists():
        return None
    if not GAME.is_dir() or GAME.stat().st_uid != os.getuid():
        raise ValueError("The native game folder is not an ordinary directory owned by this account.")
    for name, owner in ((MARKER, OWNER), (".codex-halo-native-install.json", "codex-halo-native-frame-20261005")):
        path = GAME / name
        if path.exists() or path.is_symlink():
            metadata = private_json(path, GAME)
            if metadata.get("owner") != owner:
                raise ValueError("The native game folder belongs to another application. It was kept.")
            return metadata
    raise ValueError("The native game folder has no recognized installer ownership marker. It was kept.")


def uninstall_signature(details):
    return details.st_dev, details.st_ino, details.st_mode, details.st_uid, details.st_size, details.st_mtime_ns


def uninstall_mounts():
    if not sys.platform.startswith("linux"):
        return []
    # /proc/self/mountinfo also exposes bind mounts with unchanged st_dev.
    with pathlib.Path("/proc/self/mountinfo").open("rb") as stream:
        data = stream.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Mount metadata exceeds uninstall's safety bounds.")
    points = []
    for line in data.decode("utf-8", "surrogateescape").splitlines():
        fields = line.split()
        if len(fields) < 7:
            raise ValueError("Mount metadata could not be safely checked.")
        point = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
        points.append(pathlib.Path(point))
    return points


def uninstall_inventory(directory):
    """Validate the whole owned tree before deletion; never follow a link or mount."""
    beneath(directory, HOME)
    root = directory.lstat()
    if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.getuid() or os.path.ismount(directory):
        raise ValueError("Uninstall requires an ordinary owned folder, not a link or mount.")
    if root.st_dev != directory.parent.stat().st_dev:
        raise ValueError("The native game is on a mounted filesystem and cannot be safely quarantined.")
    if any(point == directory or point.is_relative_to(directory) for point in uninstall_mounts()):
        raise ValueError("Uninstall cannot remove a mounted game folder or a mount within it.")
    inventory, pending = {}, [directory]
    while pending:
        parent = pending.pop()
        for path in parent.iterdir():
            beneath(path, directory)
            details = path.lstat()
            if details.st_uid != os.getuid() or details.st_dev != root.st_dev:
                raise ValueError("Uninstall found a foreign file or mounted directory. Game files were kept.")
            relative = str(path.relative_to(directory))
            if stat.S_ISDIR(details.st_mode):
                if os.path.ismount(path):
                    raise ValueError("Uninstall cannot remove mounted directories.")
                kind = "directory"
                pending.append(path)
            elif stat.S_ISREG(details.st_mode) and details.st_nlink == 1:
                kind = "file"
            else:
                raise ValueError("Uninstall found a symbolic link, hard link or unsupported file. Game files were kept.")
            inventory[relative] = (kind, uninstall_signature(details))
            if len(inventory) > 200000:
                raise ValueError("The native game folder exceeds uninstall's safe file-count limit.")
    return inventory


def uninstall_save_files(inventory):
    roots, external = [GAME / "save"], []
    config = GAME / "config.toml"
    if "config.toml" in inventory:
        if config.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("The game configuration is too large to locate saves safely. Game files were kept.")
        try:
            descriptor = os.open(ordinary(beneath(config, GAME)), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as stream:
                if uninstall_signature(os.fstat(stream.fileno())) != inventory["config.toml"][1]:
                    raise ValueError("The game configuration changed while locating saves.")
                encoded = stream.read(MAX_MANIFEST_BYTES + 1)
            if len(encoded) > MAX_MANIFEST_BYTES:
                raise ValueError("The game configuration exceeds the supported size.")
            paths = tomllib.loads(encoded.decode("utf-8")).get("paths", {})
        except (ValueError, UnicodeError) as error:
            raise ValueError("The game configuration is damaged, so its save location could not be verified. Game files were kept.") from error
        if not isinstance(paths, dict):
            raise ValueError("The game configuration has an unsupported save location. Game files were kept.")
        location = paths.get("saves")
        if location is not None:
            if not isinstance(location, str) or not location:
                raise ValueError("The configured save location is invalid. Game files were kept.")
            selected = pathlib.Path(location)
            selected = pathlib.Path(os.path.normpath(selected if selected.is_absolute() else GAME / selected))
            if selected == GAME:
                raise ValueError("The save location points at the entire game folder. Game files were kept.")
            if selected.is_relative_to(GAME):
                roots.append(beneath(selected, GAME))
            else:
                # No external path is opened, copied, renamed or removed.
                external.append(str(selected))
    selected = []
    for relative, (kind, _) in inventory.items():
        path = GAME / relative
        if kind == "file" and (relative == "config.toml" or any(path == root or path.is_relative_to(root) for root in roots)):
            selected.append(relative)
    return sorted(selected), external


def copy_uninstall_save(relative, target, signature):
    source = ordinary(beneath(GAME / relative, GAME))
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if details.st_nlink != 1 or uninstall_signature(details) != signature:
            raise ValueError("A save file changed while preparing its backup. Game files were kept.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            shutil.copyfileobj(stream, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if target.stat().st_size != details.st_size or uninstall_signature(os.fstat(stream.fileno())) != signature:
            raise ValueError("A save backup could not be verified. Game files were kept.")
        target.chmod(details.st_mode & 0o777)
        os.utime(target, ns=(details.st_atime_ns, details.st_mtime_ns))


def remove_uninstall_tree(directory, inventory, completed, total):
    """Unlink only validated paths, counting actual removal work for the UI."""
    files = [relative for relative, (kind, _) in inventory.items() if kind == "file"]
    files.sort(key=lambda relative: (relative in (MARKER, ".codex-halo-native-install.json"), relative))
    directories = sorted((relative for relative, (kind, _) in inventory.items() if kind == "directory"),
                         key=lambda relative: len(pathlib.Path(relative).parts), reverse=True)
    for relative in files + directories:
        path = beneath(directory / relative, directory)
        details = path.lstat()
        kind, signature = inventory[relative]
        if kind == "file":
            if details.st_nlink != 1 or uninstall_signature(details) != signature:
                raise ValueError("A native game file changed during removal.")
            path.unlink()
        else:
            if not stat.S_ISDIR(details.st_mode) or (details.st_dev, details.st_ino, details.st_uid) != (signature[0], signature[1], signature[3]):
                raise ValueError("A native game directory changed during removal.")
            path.rmdir()
        completed[0] += 1
        if total:
            progress("uninstall", f"Uninstalling native Halo: {completed[0]:,} of {total:,} file tasks.",
                     completed[0] * 100 // total)
    directory.rmdir()
    completed[0] += 1


def uninstall(value, close_steam=False, keep_saves=False):
    preflight_uninstall()
    directory = run_dir(value)
    if directory.exists():
        metadata = private_json(directory / MARKER, directory)
        if metadata.get("operation") != "uninstall":
            raise ValueError("Use a fresh run identifier for uninstall.")
    else:
        metadata = owned(directory)
        metadata["operation"] = "uninstall"
        (directory / MARKER).write_text(json.dumps(metadata) + "\n")
    identity = uninstall_identity()
    game_closed()
    no_active_build()
    inventory = uninstall_inventory(GAME) if identity else {}
    save_files, external = uninstall_save_files(inventory) if identity and keep_saves else ([], [])
    quarantine = beneath(GAME.parent / (".HaloCENativeVR-uninstall-" + value), HOME)
    saved = beneath(GAME.parent / ("HaloCENativeVR-saves-" + value), HOME)
    staging = beneath(GAME.parent / (".HaloCENativeVR-saves-" + value + ".tmp"), HOME)
    for path in (quarantine, staging):
        if path.exists() or path.is_symlink():
            raise ValueError("An unfinished uninstall folder already exists: " + str(path))
    if save_files and (saved.exists() or saved.is_symlink()):
        raise ValueError("The selected save backup already exists. Use a fresh uninstall run.")
    total = len(save_files) + len(inventory) + (1 if identity else 0)
    completed = [0]
    staged, saved_path, renamed = False, None, False
    progress("uninstall", "Preparing to remove the managed native game and its Steam shortcut...", 0)
    try:
        if save_files:
            needed = sum(inventory[relative][1][4] for relative in save_files)
            if shutil.disk_usage(GAME.parent).free < needed + 1024 * 1024:
                raise ValueError("There is not enough space to keep the selected save files. Game files were kept.")
            staging.mkdir(mode=0o700, exist_ok=False)
            staged = True
            (staging / MARKER).write_text(json.dumps({"owner": OWNER + "-save-backup", "gamePath": str(GAME),
                                                     "externalSavePathsPreserved": external}) + "\n")
            for relative in save_files:
                copy_uninstall_save(relative, beneath(staging / relative, staging), inventory[relative][1])
                completed[0] += 1
                progress("uninstall", f"Keeping campaign saves and configuration: {completed[0]:,} files copied.",
                         completed[0] * 100 // total)
        sys.path.insert(0, str(CACHE / "resources"))
        from steam_shortcut import remove_native_shortcut
        steam = remove_native_shortcut(HOME, GAME, close_steam=close_steam)
        if steam.get("status") not in ("removed", "already-absent"):
            return {"gamePath": str(GAME), "uninstalled": False, "savedBackupPath": None, "steam": steam}
        if not identity:
            return {"gamePath": str(GAME), "uninstalled": True, "alreadyAbsent": True,
                    "savedBackupPath": metadata.get("savedBackupPath"), "steam": steam}
        game_closed()
        no_active_build()
        if uninstall_inventory(GAME) != inventory:
            raise ValueError("The native game folder changed during uninstall. Its files were kept.")
        if staged:
            rename_noreplace(staging, saved)
            staged, saved_path = False, str(saved)
        rename_noreplace(GAME, quarantine)
        renamed = True
        metadata.update({"quarantinePath": str(quarantine), "savedBackupPath": saved_path, "state": "removing"})
        (directory / MARKER).write_text(json.dumps(metadata) + "\n")
        game_closed((quarantine / "halo",))
        remove_uninstall_tree(quarantine, inventory, completed, total)
        renamed = False
        metadata["state"] = "complete"
        warning = None
        try:
            (directory / MARKER).write_text(json.dumps(metadata) + "\n")
        except OSError:
            # Bookkeeping failure after deletion cannot undo a completed removal.
            warning = "Halo was removed, but the installer operation record could not be updated."
        progress("uninstall", "Native Halo and its Steam shortcut were removed.", 100)
        response = {"gamePath": str(GAME), "uninstalled": True, "savedBackupPath": saved_path,
                    "externalSavePathsPreserved": external, "steam": steam}
        if warning:
            response["warning"] = warning
        return response
    except BaseException as error:
        if renamed and quarantine.exists():
            removals = completed[0] - len(save_files)
            if removals == 0:
                try:
                    rename_noreplace(quarantine, GAME)
                    renamed = False
                except (OSError, ValueError, RuntimeError):
                    pass
            if renamed:
                message = (f"Uninstall stopped after {max(0, removals):,} removal tasks. Remaining native files are in "
                           f"{quarantine}. The Steam shortcut may already be removed.")
                if saved_path:
                    message += " Campaign saves and configuration were kept in " + saved_path + "."
                raise RuntimeError(message) from error
        raise
    finally:
        if staged and staging.exists():
            # This contains only files copied by this operation; never the game.
            remove_uninstall_tree(staging, uninstall_inventory(staging), [0], 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("preflight", "preflight-uninstall", "preflight-library", "prepare", "reuse-upload", "build", "finalize", "cancel", "shortcut", "uninstall"))
    parser.add_argument("--run-id")
    parser.add_argument("--close-steam", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--adopt-existing", action="store_true")
    parser.add_argument("--use-existing-maps", action="store_true")
    parser.add_argument("--keep-saves", action="store_true")
    args = parser.parse_args()
    if args.step in ("prepare", "reuse-upload", "build", "finalize", "cancel", "uninstall") and args.run_id is None:
        parser.error("--run-id is required")
    functions = {"preflight": lambda: preflight(args.repair, args.adopt_existing),
                 "preflight-uninstall": preflight_uninstall,
                 "preflight-library": preflight_library,
                 "prepare": lambda: prepare(args.run_id, args.use_existing_maps, args.repair, args.adopt_existing),
                 "reuse-upload": lambda: reuse_upload(args.run_id),
                 "build": lambda: build(args.run_id, args.repair, args.adopt_existing),
                 "finalize": lambda: finalize(args.run_id, args.repair, args.adopt_existing),
                 "cancel": lambda: cancel(args.run_id), "shortcut": lambda: shortcut(args.close_steam),
                 "uninstall": lambda: uninstall(args.run_id, args.close_steam, args.keep_saves)}
    result(functions[args.step]())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print("HFI_ERROR " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
