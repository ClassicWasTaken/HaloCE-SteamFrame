"""Discover fixed native-game destinations without accepting arbitrary paths."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess

MAX_MOUNT_BYTES = 2 * 1024 * 1024
MAX_MOUNTS = 4096
MAX_SD_CANDIDATES = 8
# Btrfs can span devices and its mountinfo identity is not the SD partition's
# block-device identity. Only filesystems this check can prove are eligible.
SUPPORTED_FILESYSTEMS = frozenset(("ext4", "f2fs"))
MARKER = ".halo-frame-installer.json"
OWNER = "halo-frame-installer"


def _safe_path(path):
    path = pathlib.Path(path)
    remote_fixture = os.name == "nt" and path.anchor == "\\"
    if (not path.is_absolute() and not remote_fixture) or ".." in path.parts or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise ValueError("Storage paths must be ordinary absolute paths.")
    cursor = pathlib.Path(path.anchor)
    for component in path.parts[1:]:
        cursor /= component
        if cursor.is_symlink():
            raise ValueError("Storage paths must not contain symbolic links.")
    if not remote_fixture and path.resolve() != path:
        raise ValueError("The storage path does not resolve to its displayed location.")
    return path


def _mount_records():
    with pathlib.Path("/proc/self/mountinfo").open("rb") as stream:
        data = stream.read(MAX_MOUNT_BYTES + 1)
    if len(data) > MAX_MOUNT_BYTES:
        raise ValueError("Storage mount metadata exceeds supported bounds.")
    records = []
    for line in data.decode("utf-8", "surrogateescape").splitlines():
        fields = line.split()
        if len(records) >= MAX_MOUNTS or "-" not in fields:
            raise ValueError("Storage mount metadata cannot be safely checked.")
        separator = fields.index("-")
        if (separator < 6 or len(fields) < separator + 4 or not fields[0].isdigit()
                or not fields[1].isdigit() or not re.fullmatch(r"[0-9]+:[0-9]+", fields[2])):
            raise ValueError("Storage mount metadata cannot be safely checked.")
        decode = lambda value: re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)
        records.append({"mountId": int(fields[0]), "device": fields[2], "root": decode(fields[3]),
                        "path": pathlib.Path(decode(fields[4])), "options": set(fields[5].split(",")),
                        "filesystem": fields[separator + 1], "source": decode(fields[separator + 2]),
                        "superOptions": set(fields[separator + 3].split(","))})
    return records


def _sd_identity(record):
    """Match the mounted partition to the kernel's physical SD card identity."""
    partition = (pathlib.Path("/sys/dev/block") / record["device"]).resolve(strict=True)
    if not re.fullmatch(r"mmcblk[0-9]+p[0-9]+", partition.name):
        raise ValueError("The mounted device is not a native SD-card partition.")
    disk = partition.parent
    if (not re.fullmatch(r"mmcblk[0-9]+", disk.name)
            or (partition / "dev").read_text().strip() != record["device"]
            or not (partition / "partition").read_text().strip().isdigit()
            or (disk / "device/type").read_text().strip() != "SD"):
        raise ValueError("The mounted device does not have a matching kernel SD identity.")
    cid = (disk / "device/cid").read_text().strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", cid):
        raise ValueError("The SD card's physical identity is unavailable.")
    device = pathlib.Path("/dev") / partition.name
    details = device.stat()
    if (not stat.S_ISBLK(details.st_mode)
            or f"{os.major(details.st_rdev)}:{os.minor(details.st_rdev)}" != record["device"]):
        raise ValueError("The mounted SD partition does not match its block device.")
    uuid_result = subprocess.run(["lsblk", "--noheadings", "--nodeps", "--output", "UUID", "--", str(device)],
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
    filesystem_uuid = uuid_result.stdout.strip().lower()
    if uuid_result.returncode or not re.fullmatch(r"[a-z0-9-]{1,128}", filesystem_uuid):
        raise ValueError("The SD filesystem identity is unavailable.")
    return {"cardIdentity": hashlib.sha256(cid.encode("ascii")).hexdigest(),
            "filesystemUuid": filesystem_uuid, "blockDevice": str(device)}


def _mount_path_allowed(path, home):
    if path.parent not in (pathlib.Path("/run/media"), pathlib.Path("/run/media") / home.name):
        return False
    # Steam stores this path in its executable command. Spaces and Unicode are
    # fine; interpolation/quote/control characters must never enter that string.
    return bool(path.name) and not any(c in "$`\"'\\;|&<>:" or ord(c) < 32 or ord(c) == 127 for c in path.name)


def _installed(game):
    if not game.is_dir() or game.is_symlink():
        return False
    for name, owner in ((MARKER, OWNER), (".codex-halo-native-install.json", "codex-halo-native-frame-20261005")):
        path = game / name
        try:
            details = path.lstat()
            if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                    or (hasattr(os, "getuid") and details.st_uid != os.getuid())
                    or not 0 < details.st_size <= 64 * 1024):
                continue
            value = json.loads(path.read_text())
            if isinstance(value, dict) and value.get("owner") == owner:
                return True
        except (OSError, ValueError, UnicodeError):
            continue
    return False


def _descriptor(storage_id, kind, root, identity, home):
    root = _safe_path(root)
    game = _safe_path(root / "Games/HaloCENativeVR")
    cache = _safe_path(home / ".cache/halo-frame-installer" if kind == "internal" else root / ".halo-frame-installer")
    return {"id": storage_id, "kind": kind, "label": "Internal storage" if kind == "internal" else "SD card · " + root.name,
            "mountPath": str(root), "gamePath": str(game), "cachePath": str(cache),
            "freeBytes": shutil.disk_usage(root).free, "installed": _installed(game), "identity": identity,
            "ownershipIdentity": ownership_identity(identity)}


def ownership_identity(identity):
    if identity.get("kind") == "internal":
        return {"kind": "internal", "root": identity["root"]}
    return {key: identity[key] for key in ("kind", "mountPath", "cardIdentity", "filesystemUuid", "filesystem")}


def discover_storage(home=pathlib.Path("/home/steamos")):
    home = _safe_path(home)
    internal = _descriptor("internal", "internal", home, {"kind": "internal", "root": str(home)}, home)
    destinations, unavailable = [internal], []
    if platform.system() != "Linux":
        return {"home": str(home), "destinations": destinations, "unavailable": unavailable}
    records = _mount_records()
    checked = 0
    for record in records:
        root = record["path"]
        allowed_path = _mount_path_allowed(root, home)
        native_card_source = re.fullmatch(r"/dev/mmcblk[0-9]+p[0-9]+", record["source"])
        if not allowed_path and not native_card_source:
            continue
        checked += 1
        if checked > MAX_SD_CANDIDATES:
            break
        if not allowed_path:
            try:
                _sd_identity(record)
            except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
                continue
            unavailable.append({"mountPath": str(root), "reason": "The mounted SD card path is outside the supported SteamOS mount locations or contains unsupported launch-command characters."})
            continue
        try:
            root = _safe_path(root)
            flags = record["options"] | record["superOptions"]
            if (record["root"] != "/" or record["filesystem"] not in SUPPORTED_FILESYSTEMS
                    or "ro" in flags or "noexec" in flags or "rw" not in record["options"]
                    or not os.access(root, os.W_OK | os.X_OK)):
                raise ValueError("The SD card needs a writable, executable Linux filesystem mounted by SteamOS.")
            if any(other is not record and (other["device"] == record["device"]
                       or other["path"] == root or other["path"].is_relative_to(root)) for other in records):
                raise ValueError("The SD card has another mount or a mounted directory within it.")
            details = root.stat()
            if not stat.S_ISDIR(details.st_mode) or f"{os.major(details.st_dev)}:{os.minor(details.st_dev)}" != record["device"]:
                raise ValueError("The SD mount no longer matches its mounted filesystem.")
            identity = {"kind": "sd", "mountPath": str(root), "mountId": record["mountId"],
                        "device": record["device"], "filesystem": record["filesystem"],
                        "rootDevice": details.st_dev, "rootInode": details.st_ino, **_sd_identity(record)}
            storage_id = "sd:" + hashlib.sha256(json.dumps(ownership_identity(identity), sort_keys=True).encode("utf-8")).hexdigest()[:32]
            destinations.append(_descriptor(storage_id, "sd", root, identity, home))
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as error:
            unavailable.append({"mountPath": str(root), "reason": str(error)[:300]})
    return {"home": str(home), "destinations": destinations, "unavailable": unavailable}


def resolve_storage(storage_id, home=pathlib.Path("/home/steamos")):
    if storage_id != "internal" and not (isinstance(storage_id, str) and re.fullmatch(r"sd:[a-f0-9]{32}", storage_id)):
        raise ValueError("Choose internal storage or one detected SD card.")
    inventory = discover_storage(home)
    for descriptor in inventory["destinations"]:
        if descriptor["id"] == storage_id:
            return descriptor
    raise ValueError("The selected SD card is missing or its mount identity changed. Refresh storage and choose it again.")


def validate_game_path(home, game):
    home, game = _safe_path(home), _safe_path(game)
    for descriptor in discover_storage(home)["destinations"]:
        if descriptor.get("gamePath") == str(game):
            root = _safe_path(descriptor["mountPath"])
            if game != root / "Games/HaloCENativeVR":
                break
            if descriptor.get("kind") == "internal" and root == home and descriptor.get("id") == "internal":
                return descriptor
            if (descriptor.get("kind") == "sd" and re.fullmatch(r"sd:[a-f0-9]{32}", str(descriptor.get("id", "")))
                    and root != home):
                return descriptor
    raise ValueError("Steam integration is restricted to a validated fixed native Halo installation path.")


def main():
    home = pathlib.Path("/home/steamos")
    if platform.system() != "Linux":
        raise ValueError("Storage discovery supports SteamOS Steam Frame only.")
    import pwd
    if (os.getuid() == 0 or pwd.getpwuid(os.getuid()).pw_name != "steamos" or pathlib.Path.home() != home
            or platform.machine().lower() not in ("aarch64", "arm64")):
        raise ValueError("Connect to an ARM64 Steam Frame using its steamos account.")
    system = pathlib.Path("/etc/os-release").read_text()
    if not re.search(r'^ID=(?:"steamos"|steamos)$', system, re.M):
        raise ValueError("Storage discovery supports SteamOS Steam Frame only.")
    print("HFI_RESULT " + json.dumps(discover_storage(home)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as error:
        print("HFI_ERROR " + str(error).replace("\n", " ")[:600], flush=True)
        raise SystemExit(1)
