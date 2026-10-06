"""Coordinate an owned, atomic Steam Frame native VR installation."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable

from .ssh import CancelledError, RemoteTimeoutError, Settings, SSHConnection, SSHError

SOURCE_COMMIT = "2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4"
EXPECTED_MAPS = frozenset(name + ".map" for name in (
    "a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40",
    "beavercreek", "bloodgulch", "boardingaction", "carousel", "chillout", "damnation",
    "hangemhigh", "longest", "prisoner", "putput", "ratrace", "sidewinder", "ui", "wizard"))
ProgressCallback = Callable[[str, str, float | None], None]


def resources_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "resources"
    return Path(__file__).resolve().parents[2] / "resources"


def storage_arguments(settings: Settings) -> list[str]:
    return [] if settings.storage_id == "internal" else ["--storage-id", settings.storage_id]


def run_remote_source(connection, source: str, arguments=(), **kwargs) -> str:
    """Send bundled Python through stdin, keeping the SSH command bounded.

    Linux limits each argument, including SSH's shell command, to roughly
    128 KiB. The combined installer helper can exceed that limit. Check the
    complete payload before executing it so a dropped connection cannot run
    a syntactically valid but truncated source file.
    """
    payload = source.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    bootstrap = (
        "import sys,hashlib\n"
        f"_hfi_source=sys.stdin.buffer.read({len(payload) + 1})\n"
        f"if len(_hfi_source)!={len(payload)} or hashlib.sha256(_hfi_source).hexdigest()!={digest!r}:\n"
        " raise SystemExit('HFI_ERROR Setup helper transfer was incomplete. Reconnect and retry.')\n"
        "exec(compile(_hfi_source,'<bundled setup helper>','exec'),globals())\n")
    return connection.run(["python3", "-c", bootstrap, *arguments],
                          input_data=payload, **kwargs)


def validate_sd_identity(value: dict, mount: str) -> dict:
    """Require the card, filesystem and live kernel mount checked by preflight."""
    if (not isinstance(value, dict) or value.get("kind") != "sd" or value.get("mountPath") != mount
            or any(type(value.get(key)) is not int or value[key] <= 0
                   for key in ("mountId", "rootDevice", "rootInode"))
            or not isinstance(value.get("device"), str) or not re.fullmatch(r"[0-9]+:[0-9]+", value["device"])
            or value.get("filesystem") not in ("ext4", "f2fs")
            or not isinstance(value.get("cardIdentity"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["cardIdentity"])
            or not isinstance(value.get("filesystemUuid"), str) or not re.fullmatch(r"[a-z0-9-]{1,128}", value["filesystemUuid"])):
        raise SSHError("The Frame returned an invalid SD card identity. Refresh storage before retrying.")
    # Preserve and compare all live identity fields, including the block-device
    # name supplied by the bundled validator. Metadata must remain bounded.
    if (len(value) > 16 or any(not isinstance(key, str) or not 0 < len(key) <= 64
                              or (type(item) is not int and not isinstance(item, str))
                              or (isinstance(item, str) and (len(item) > 512
                                  or any(ord(c) < 32 or ord(c) == 127 for c in item)))
                              for key, item in value.items())
            or ("blockDevice" in value and (not isinstance(value["blockDevice"], str)
                or not re.fullmatch(r"/dev/mmcblk[0-9]+p[0-9]+", value["blockDevice"])))):
        raise SSHError("The Frame returned an invalid SD card identity. Refresh storage before retrying.")
    return dict(value)


def validate_storage_destination(value: dict, selected_id: str | None = None) -> dict:
    """Bound remote paths to the fixed leaves of one detected storage volume."""
    if not isinstance(value, dict):
        raise SSHError("The Frame returned an invalid storage location.")
    identifier = value.get("id")
    if (not isinstance(identifier, str) or not re.fullmatch(r"internal|sd:[a-f0-9]{32}", identifier)
            or (selected_id is not None and identifier != selected_id)):
        raise SSHError("The Frame returned an unexpected storage selection.")
    mount = value.get("mountPath")
    if (not isinstance(mount, str) or len(mount) > 400
            or any(ord(c) < 32 or ord(c) == 127 or c in "\"'`$\\;|&<>:" for c in mount)
            or str(PurePosixPath(mount)) != mount or ".." in PurePosixPath(mount).parts):
        raise SSHError("The Frame returned an invalid storage mount path.")
    if identifier == "internal":
        if mount != "/home/steamos" or value.get("kind") != "internal":
            raise SSHError("The Frame returned an unexpected internal storage location.")
        cache = mount + "/.cache/halo-frame-installer"
    else:
        if (value.get("kind") != "sd"
                or not re.fullmatch(r"/run/media/(?:steamos/)?[^/]+", mount)
                or mount == "/run/media/steamos"):
            raise SSHError("The Frame returned an unexpected SD card location.")
        cache = mount + "/.halo-frame-installer"
    if value.get("gamePath") != mount + "/Games/HaloCENativeVR" or value.get("cachePath") != cache:
        raise SSHError("The Frame returned an unexpected installation location.")
    if (type(value.get("freeBytes")) is not int or value["freeBytes"] < 0
            or not isinstance(value.get("label"), str) or not 0 < len(value["label"]) <= 512
            or any(ord(c) < 32 or ord(c) == 127 for c in value["label"])
            or type(value.get("installed")) is not bool):
        raise SSHError("The Frame returned invalid storage details.")
    destination = dict(value)
    if identifier != "internal":
        destination["identity"] = validate_sd_identity(value.get("identity"), mount)
    return destination


def validate_preflight_location(info: dict, settings: Settings) -> dict:
    if info.get("home") != "/home/steamos":
        raise SSHError("The Frame reported an unexpected installation account.")
    storage = info.get("storage")
    if storage is None and settings.storage_id == "internal":
        # The fixed internal location is also used by existing integration fixtures.
        storage = {"id": "internal", "kind": "internal", "mountPath": "/home/steamos",
                   "gamePath": "/home/steamos/Games/HaloCENativeVR",
                   "cachePath": "/home/steamos/.cache/halo-frame-installer",
                   "freeBytes": 0, "label": "Internal storage", "installed": False}
    destination = validate_storage_destination(storage, settings.storage_id)
    if any(info.get(key) != destination[key] for key in ("gamePath", "cachePath")):
        raise SSHError("The Frame reported an unexpected installation location.")
    existing = info.get("existing")
    if existing is not None and (not isinstance(existing, dict) or existing.get("gamePath") != destination["gamePath"]):
        raise SSHError("The Frame reported an unexpected existing game location.")
    return destination


def map_manifest(maps_dir: Path) -> tuple[Path, dict]:
    maps_dir = Path(maps_dir)
    if (maps_dir / "maps").is_dir():
        maps_dir = maps_dir / "maps"
    if maps_dir.is_symlink() or not maps_dir.is_dir():
        raise ValueError("Select a directory containing the extracted Xbox maps.")
    actual = list(maps_dir.iterdir())
    if {path.name for path in actual} != EXPECTED_MAPS:
        raise ValueError("Extraction must contain the 24 original Xbox Halo map files.")
    files = []
    for path in sorted(actual):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Only ordinary map files may be uploaded.")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        files.append({"path": "maps/" + path.name, "size": path.stat().st_size,
                      "sha256": h.hexdigest()})
    return maps_dir, {"files": files, "totalBytes": sum(item["size"] for item in files),
                      "format": "original Xbox Halo maps; user-provided data"}


def validated_steam(steam) -> dict:
    """The shortcut step's device-authored payload must stay plain strings and dicts."""
    if not isinstance(steam, dict) or not isinstance(steam.get("status"), str):
        raise SSHError("The Frame returned an invalid Steam registration response.")
    for key in ("reason", "instructions", "launchOptions"):
        if key in steam and not isinstance(steam[key], str):
            raise SSHError("The Frame returned an invalid Steam registration response.")
    for key in ("artwork", "notes"):
        if key in steam and not isinstance(steam[key], dict):
            raise SSHError("The Frame returned an invalid Steam registration response.")
    return steam


def parse_result(output: str) -> dict:
    lines = [line[len("HFI_RESULT "):] for line in output.splitlines() if line.startswith("HFI_RESULT ")]
    if len(lines) != 1:
        raise SSHError("The Frame returned an unexpected installer response.")
    result = json.loads(lines[0])
    if not isinstance(result, dict):
        raise SSHError("The Frame returned an invalid installer result.")
    return result


def parse_activity(line: str) -> tuple[str, str, float | None] | None:
    """Decode a phase update or an activity-only build line from the Frame."""
    prefix = next((value for value in ("HFI_PROGRESS ", "HFI_LOG ")
                   if line.startswith(value)), None)
    if prefix is None:
        return None
    try:
        data = json.loads(line[len(prefix):])
        if not isinstance(data, dict):
            raise ValueError
        stage, message = data.get("stage"), data.get("message")
        if (not isinstance(stage, str) or not stage or len(stage) > 64
                or not isinstance(message, str) or len(message) > 4096):
            raise ValueError
    except (ValueError, TypeError):
        raise SSHError("The Frame returned an invalid setup activity update.") from None
    if prefix == "HFI_LOG ":
        return "detail", f"{stage}: {message}", None
    percent = data.get("percent")
    # A missing or unusable count holds at the current milestone. It never
    # invents a percentage or stops the installation for a display-only value.
    if (type(percent) not in (int, float) or not 0 <= percent <= 100
            or not math.isfinite(percent)):
        percent = None
    return stage, message, percent


@dataclass(frozen=True)
class StorageResult:
    destinations: tuple[dict, ...]
    host_fingerprint: str | None
    cleanup_warning: str | None = None
    unavailable: tuple[dict, ...] = ()


@dataclass(frozen=True)
class InstallResult:
    game_path: str
    reused: bool
    steam: dict
    host_fingerprint: str | None
    source_commit: str = SOURCE_COMMIT
    repaired: bool = False
    backup_path: str | None = None
    cleanup_warning: str | None = None
    storage_id: str = "internal"

    @property
    def connection_cleanup_pending(self) -> bool:
        return bool(self.cleanup_warning)

    @property
    def steam_appid(self) -> int | None:
        return self.steam.get("appid")

    @property
    def requires_manual_steam_step(self) -> bool:
        return self.steam.get("status") != "added"


@dataclass(frozen=True)
class UninstallResult:
    game_path: str
    uninstalled: bool
    already_absent: bool
    saved_backup_path: str | None
    steam: dict
    host_fingerprint: str | None
    cleanup_warning: str | None = None
    removal_pending: bool = False
    removal_warning: str | None = None
    recovered_save_backup_paths: tuple[str, ...] = ()
    retained_quarantine_paths: tuple[str, ...] = ()
    storage_id: str = "internal"

    @property
    def connection_cleanup_pending(self) -> bool:
        return bool(self.cleanup_warning)

    @property
    def requires_manual_steam_step(self) -> bool:
        return self.steam.get("status") not in ("removed", "already-absent")


def cleanup_activity(progress: ProgressCallback, message: str) -> None:
    try:
        progress("detail", message, None)
    except Exception:
        pass  # A display callback cannot replace the operation outcome.


def close_connection(connection, progress: ProgressCallback) -> str | None:
    """Preserve the operation result, while keeping required cleanup visible."""
    try:
        connection.close()
    except Exception as error:
        settings = getattr(connection, "settings", None)
        warning = (str(error)[:4000] if isinstance(error, SSHError) else
                   "Setup could not verify that its connection finished closing.")
        password = getattr(settings, "password", "")
        if password:
            warning = warning.replace(password, "[redacted]")
        action = ("Unplug the USB cable to end setup's temporary connection before retrying."
                  if getattr(settings, "transport", None) == "usb" else
                  "Close this installer before retrying the connection.")
        warning = warning + "\n" + action
        cleanup_activity(progress, warning)
        return warning
    return None


def uninstall_history(data: dict, game_path="/home/steamos/Games/HaloCENativeVR") -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Validate direct owned-path references before showing remote recovery history."""
    root = str(PurePosixPath(game_path).parent) + "/"
    backups, retained = [], []
    for key, target in (("recoveredSaveBackupPaths", backups),
                        ("retainedQuarantinePaths", retained)):
        values = data.get(key, [])
        if not isinstance(values, list) or len(values) > 64:
            raise SSHError("The Frame returned an invalid uninstall recovery history.")
        for value in values:
            if (not isinstance(value, str) or len(value) > max(512, len(root) + 255)
                    or len(value.rsplit("/", 1)[-1]) > 255 or value in target):
                raise SSHError("The Frame returned an invalid uninstall recovery history.")
            if key == "recoveredSaveBackupPaths":
                valid = re.fullmatch(re.escape(root) + r"HaloCENativeVR-saves-[a-f0-9]{32}", value)
            else:
                prefix = root + ".HaloCENativeVR-uninstall-"
                suffix = value[len(prefix):] if value.startswith(prefix) else ""
                valid = suffix and not any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in suffix)
            if not valid:
                raise SSHError("The Frame returned an invalid uninstall recovery history.")
            target.append(value)
    warning = data.get("warning")
    if warning is not None and (not isinstance(warning, str) or not 0 < len(warning) <= 4096):
        raise SSHError("The Frame returned an invalid uninstall warning.")
    return tuple(backups), tuple(retained), warning


class Installer:
    def __init__(self, connection_factory=SSHConnection, resource_dir: Path | None = None):
        self.connection_factory = connection_factory
        self.resource_dir = resource_dir or resources_path()

    def remote_source(self) -> str:
        """Bootstrap the bundled storage validator before the installer helper."""
        storage = (self.resource_dir / "frame_storage.py").read_text(encoding="utf-8")
        helper = (self.resource_dir / "remote_install.py").read_text(encoding="utf-8")
        # exec handles future-import declarations in each source independently.
        bootstrap = ("import sys,types\n"
                     "_hfi_storage=types.ModuleType('frame_storage')\n"
                     "_hfi_storage.__file__='<bundled frame_storage>'\n"
                     "sys.modules['frame_storage']=_hfi_storage\n"
                     "exec(" + repr(storage) + ",_hfi_storage.__dict__)\n"
                     "exec(" + repr(helper) + ",globals())\n")
        return bootstrap

    def guarded_upload(self, connection, settings: Settings, destination: dict,
                       cancel_event: threading.Event):
        """Pin direct SFTP writes to the original live SD mount identity."""
        if settings.storage_id == "internal":
            def upload(local, remote, *, callback=None):
                options = {"callback": callback} if callback is not None else {}
                connection.put(local, remote, cancel_event=cancel_event, **options)
            return upload

        original = validate_storage_destination(destination, settings.storage_id)
        source = (self.resource_dir / "frame_storage.py").read_text(encoding="utf-8")
        # Run our bundled read-only validator even before frame_storage.py itself
        # is uploaded. No user map data or preflight snapshot is sent in the check.
        inline = ("import sys,types,json,subprocess\n"
                  "_hfi_storage=types.ModuleType('frame_storage')\n"
                  "_hfi_storage.__file__='<bundled frame_storage>'\n"
                  "exec(" + repr(source) + ",_hfi_storage.__dict__)\n"
                  "try:\n"
                  " print('HFI_RESULT '+json.dumps(_hfi_storage.resolve_storage(sys.argv[-1])),flush=True)\n"
                  "except (OSError,ValueError,UnicodeError,subprocess.SubprocessError) as error:\n"
                  " print('HFI_ERROR '+str(error).replace('\\n',' ')[:600],flush=True)\n"
                  " raise SystemExit(1)\n")
        arguments = storage_arguments(settings)

        def verify():
            if cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.")
            current = validate_storage_destination(parse_result(run_remote_source(
                connection, inline, arguments, cancel_event=cancel_event, timeout=90)), settings.storage_id)
            if (current["identity"] != original["identity"]
                    or any(current[key] != original[key] for key in ("mountPath", "gamePath", "cachePath"))):
                raise SSHError("The selected SD card changed during transfer. Setup stopped without updating the Steam library. Refresh storage and choose the card again.")
            if cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.")

        def upload(local, remote, *, callback=None):
            verify()
            checked_at = time.monotonic()

            def update(done, total):
                nonlocal checked_at
                if cancel_event.is_set():
                    raise CancelledError("Installation cancelled. Existing games and saves were kept.")
                if time.monotonic() - checked_at >= 1.0:
                    verify()
                    checked_at = time.monotonic()
                if callback is not None:
                    callback(done, total)

            connection.put(local, remote, callback=update, cancel_event=cancel_event)
            verify()

        return upload

    def discover_storage(self, settings: Settings,
                         cancel_event: threading.Event | None = None) -> StorageResult:
        """Inspect mounted storage without changing the game or mounting/formatting a card."""
        connection = self.connection_factory(settings)
        cancel_event = cancel_event or threading.Event()
        cleanup_attempted = False
        try:
            if cancel_event.is_set():
                raise CancelledError("Storage check cancelled.")
            connection.connect()
            source = (self.resource_dir / "frame_storage.py").read_text(encoding="utf-8")
            inventory = parse_result(run_remote_source(connection, source,
                                    cancel_event=cancel_event, timeout=90))
            values = inventory.get("destinations")
            if (inventory.get("home") != "/home/steamos" or not isinstance(values, list)
                    or not 1 <= len(values) <= 16):
                raise SSHError("The Frame returned an invalid storage inventory.")
            destinations = tuple(validate_storage_destination(value) for value in values)
            identifiers = [item["id"] for item in destinations]
            if identifiers.count("internal") != 1 or len(set(identifiers)) != len(identifiers):
                raise SSHError("The Frame returned duplicate or missing storage locations.")
            unavailable = inventory.get("unavailable", [])
            if not isinstance(unavailable, list) or len(unavailable) > 16:
                raise SSHError("The Frame returned invalid storage diagnostics.")
            for item in unavailable:
                if (not isinstance(item, dict)
                        or not isinstance(item.get("mountPath"), str) or not 0 < len(item["mountPath"]) <= 512
                        or not isinstance(item.get("reason"), str) or not 0 < len(item["reason"]) <= 512
                        or any(ord(c) < 32 or ord(c) == 127 for c in item["mountPath"] + item["reason"])):
                    raise SSHError("The Frame returned invalid storage diagnostics.")
            fingerprint = connection.host_fingerprint
            warning = close_connection(connection, lambda *args: None)
            cleanup_attempted = True
            return StorageResult(destinations, fingerprint, warning, tuple(dict(item) for item in unavailable))
        finally:
            if not cleanup_attempted:
                warning = close_connection(connection, lambda *args: None)
                if warning and sys.exc_info()[1] is not None:
                    error = sys.exc_info()[1]
                    if isinstance(error, CancelledError):
                        error.requires_attention = True
                    error.args = (str(error) + "\n\n" + warning,)

    def run(self, settings: Settings, maps_dir: Path | None,
            progress_callback: ProgressCallback | None = None,
            cancel_event: threading.Event | None = None, *, registration_only=False) -> InstallResult:
        """Install or reuse the pinned native game, then safely add its Steam shortcut."""
        progress = progress_callback or (lambda stage, message, percent=None: None)
        cancel_event = cancel_event or threading.Event()
        connection = self.connection_factory(settings)
        run_identifier = uuid.uuid4().hex
        remote_helper: str | None = None
        prepared = False
        cleanup_attempted = False
        cancel_attempted = False
        cancellation_warning = None
        cancellation_unconfirmed = False

        def check_cancel():
            if cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.")

        def remote_progress(line):
            activity = parse_activity(line)
            if activity is not None:
                progress(*activity)

        def cancel_remote():
            nonlocal cancel_attempted, cancellation_warning, cancellation_unconfirmed
            if remote_helper is None or not prepared or cancel_attempted:
                return
            cancel_attempted = True
            argv = ["python3", remote_helper, "cancel", "--run-id", run_identifier] + storage_arguments(settings)

            def request(target):
                response = parse_result(target.run(argv, timeout=45))
                if response.get("cancelled") is not True:
                    raise SSHError("The Frame did not confirm this installer run's cancellation.")

            try:
                active = getattr(connection, "is_active", lambda: True)()
                if active:
                    request(connection)
                    cleanup_activity(progress, "Remote build cancellation confirmed.")
                    return
            except Exception:
                pass
            recovery = recovery_settings = None
            try:
                approved = (connection.host_fingerprint or settings.known_host_fingerprint
                            or settings.known_host_fingerprints.get(settings.host_identity))
                if not isinstance(approved, str) or not approved.startswith("SHA256:"):
                    raise SSHError("No approved host fingerprint is available for recovery.")
                recovery_settings = replace(settings, known_host_fingerprint=approved,
                                            known_host_fingerprints={}, accept_host_key=None)
                recovery = self.connection_factory(recovery_settings)
                if recovery is connection:
                    recovery = None
                    raise SSHError("A fresh recovery connection could not be created.")
                cleanup_activity(progress, "Reconnecting once to stop this installer run, using the approved SSH host key...")
                recovery.connect(timeout=10)
                request(recovery)
                cleanup_activity(progress, "Remote build cancellation confirmed.")
            except Exception:
                cancellation_unconfirmed = True
                cancellation_warning = (
                    "Remote stopping could not be confirmed. The installer build may still be running on the Frame. "
                    "Restore the connection and stop this run before retrying installation or uninstalling.\n"
                    "In the Frame's terminal, run: " + " ".join(argv))
                cleanup_activity(progress, cancellation_warning)
            finally:
                if recovery is not None:
                    warning = close_connection(recovery, progress)
                    if warning:
                        cancellation_warning = (cancellation_warning + "\n\n" if cancellation_warning else "") + warning
                if recovery_settings is not None:
                    recovery_settings.password = ""

        repair = settings.reinstall_existing and not registration_only

        def step(name, *, run_id=False, timeout=3600, extras=()):
            argv = ["python3", remote_helper, name]
            if run_id:
                argv += ["--run-id", run_identifier]
            if repair:
                argv.append("--repair")
            if repair and settings.adopt_existing_native:
                argv.append("--adopt-existing")
            argv += list(extras)
            argv += storage_arguments(settings)
            return parse_result(connection.run(argv, progress=remote_progress,
                                cancel_event=cancel_event, timeout=timeout,
                                on_cancel=cancel_remote if prepared else None))

        try:
            check_cancel()
            progress("connect", "Connecting securely to your Steam Frame...", None)
            connection.connect()
            check_cancel()
            progress("preflight", "Checking the installed native game and Steam account..." if registration_only
                     else "Checking ARM64 SteamOS, SteamVR, Podman and free space...", None)
            source = self.remote_source()
            preflight_args = ["preflight-library" if registration_only else "preflight"]
            if repair:
                preflight_args.append("--repair")
            if repair and settings.adopt_existing_native:
                preflight_args.append("--adopt-existing")
            preflight_args += storage_arguments(settings)
            info = parse_result(run_remote_source(connection, source, preflight_args,
                                               progress=remote_progress, cancel_event=cancel_event, timeout=90))
            destination = validate_preflight_location(info, settings)
            upload = self.guarded_upload(connection, settings, destination, cancel_event)
            cleanup_activity(progress, "Selected " + destination["label"] + ": " + destination["gamePath"])
            if registration_only and info.get("existing") is None:
                raise SSHError("Install and verify native Halo VR before updating its Steam information.")
            if (info.get("existing") or {}).get("needsUpgrade"):
                if registration_only:
                    raise SSHError("Use Install to upgrade the existing native game to version 1.4 before updating its Steam information.")
                repair = True
                progress("upgrade", "Upgrading the existing native game to version 1.4. Previous checkpoints stay in place; new saves use save-v1.4...", None)
            if info.get("pcVersionDetected"):
                progress("detect", "Found an older Halo PC installation. The native VR build requires original Xbox maps.", None)
            remote_resources = info["cachePath"] + "/resources"
            helpers = ("frame_storage.py", "remote_install.py", "steam_shortcut.py", "steam_live.py", "steam_notes.py")
            if not registration_only:
                helpers += ("build-native.sh", "frame-controls.patch")
            for name in helpers:
                check_cancel()
                upload(self.resource_dir / name, remote_resources + "/" + name)
            # Artwork ships inside the one-file installer; no metadata service or
            # account API key is needed, including an Add to Steam again retry.
            for name in ("halo-ce-cover.jpg", "halo-ce-landscape.png", "halo-ce-hero.jpg", "halo-ce-logo.png", "halo-ce-icon.png"):
                check_cancel()
                upload(self.resource_dir / "artwork" / name,
                       remote_resources + "/artwork/" + name)
            remote_helper = remote_resources + "/remote_install.py"
            existing = info.get("existing")
            if existing is not None and not repair:
                progress("reuse", "Verified the existing native game. Keeping its files, settings and saves...", 95)
                installed = existing
            else:
                use_existing = maps_dir is None and existing is not None and existing.get("mapsVerified", False)
                if maps_dir is None and not use_existing:
                    raise ValueError("The existing Xbox maps are missing or damaged. Select your legally obtained original Xbox Halo disc image to reinstall them." if existing else "Select your legally obtained original Xbox Halo disc image first.")
                if use_existing:
                    progress("repair", "Reinstalling the native program and controls while keeping your verified Xbox maps and saves...", None)
                else:
                    progress("verify", "Checking the extracted Xbox map files...", None)
                    maps, manifest = map_manifest(Path(maps_dir))
                prepared_info = step("prepare", run_id=True, timeout=120,
                                     extras=("--use-existing-maps",) if use_existing else ())
                prepared = True
                expected_upload = info["cachePath"] + "/runs/" + run_identifier + "/upload"
                if prepared_info.get("uploadPath") != expected_upload:
                    raise SSHError("The Frame returned an unexpected upload path.")
                if not use_existing:
                    with tempfile.TemporaryDirectory(prefix="halo-frame-manifest-") as scratch:
                        manifest_path = Path(scratch) / "xbox-data-manifest.json"
                        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                        upload(manifest_path, expected_upload + "/xbox-data-manifest.json")
                    reused_upload = False
                    if info.get("retainedUploadReuse") is True:
                        progress("reuse", "Looking for verified Xbox maps from an earlier installation attempt...", None)
                        cached = step("reuse-upload", run_id=True, timeout=900)
                        reused_upload = cached.get("reusedUpload")
                        if (type(reused_upload) is not bool or (reused_upload and
                                (not isinstance(cached.get("mapsRun"), str)
                                 or not re.fullmatch("[a-f0-9]{32}", cached["mapsRun"])
                                 or cached["mapsRun"] == run_identifier))):
                            raise SSHError("The Frame returned an invalid retained upload response.")
                    if reused_upload:
                        progress("reuse", "Verified the Xbox maps already on the Frame. Skipping their upload...", 100)
                    else:
                        transferred = 0
                        total = manifest["totalBytes"]
                        progress("upload", "Sending your Xbox maps to the Frame over encrypted SSH...", 0)
                        for entry in manifest["files"]:
                            check_cancel()
                            path = maps / Path(entry["path"]).name
                            def uploaded(done, file_total):
                                percent = 100 * (transferred + done) / total if total else 100
                                progress("upload", "Uploading " + path.name, percent)
                            upload(path, expected_upload + "/" + entry["path"], callback=uploaded)
                            transferred += entry["size"]
                step("build", run_id=True, timeout=7200)
                check_cancel()
                installed = step("finalize", run_id=True, timeout=600)
            if not isinstance(installed, dict) or installed.get("gamePath") != destination["gamePath"]:
                raise SSHError("The Frame returned an unexpected installed game location.")
            check_cancel()
            progress("steam", "Updating Halo's Steam entry, artwork and game Notes while keeping Steam Home running...", None)
            steam = validated_steam(step("shortcut", timeout=150))
            # Keep the result's public fingerprint before releasing the client.
            host_fingerprint = connection.host_fingerprint
            progress("disconnect", "Closing the setup SSH connection...", None)
            cleanup_warning = close_connection(connection, progress)
            cleanup_attempted = True
            if cleanup_warning:
                progress("cleanup-pending", "Native Halo VR is installed; setup's connection cleanup needs attention.", 99)
            else:
                progress("disconnected", "Setup has disconnected from your Frame.", None)
                progress("complete", "Native VR game is ready. Launch Halo: Combat Evolved VR (Native) from your Steam library." if steam.get("status") == "added" else "Native VR game is installed. One Steam library step remains.", 100)
            return InstallResult(installed["gamePath"], bool(installed.get("reused")),
                                 steam, host_fingerprint, repaired=bool(installed.get("repaired")),
                                 backup_path=installed.get("backupPath"), cleanup_warning=cleanup_warning,
                                 storage_id=settings.storage_id)
        except (CancelledError, RemoteTimeoutError, SSHError) as error:
            cancel_remote()
            if cancellation_warning:
                if isinstance(error, CancelledError):
                    error.requires_attention = True
                message = str(error)
                if cancellation_unconfirmed:
                    first, separator, rest = message.partition("\n")
                    message = first + " Remote stopping could not be confirmed; the build may still be running on the Frame." + (separator + rest if separator else "")
                error.args = (message + "\n\n" + cancellation_warning,)
            raise
        finally:
            if not cleanup_attempted:
                cleanup_activity(progress, "Closing the setup SSH connection...")
                warning = close_connection(connection, progress)
                if warning is None:
                    cleanup_activity(progress, "Setup has disconnected from your Frame.")
                elif sys.exc_info()[1] is not None:
                    error = sys.exc_info()[1]
                    if isinstance(error, CancelledError):
                        error.requires_attention = True
                    error.args = (str(error) + "\n\n" + warning,)

    def add_to_steam(self, settings: Settings, progress_callback: ProgressCallback | None = None,
                     cancel_event: threading.Event | None = None) -> InstallResult:
        """Retry library registration without extraction, upload or rebuilding."""
        return self.run(settings, None, progress_callback, cancel_event, registration_only=True)

    def uninstall(self, settings: Settings, progress_callback: ProgressCallback | None = None,
                  cancel_event: threading.Event | None = None, *, keep_saves=True) -> UninstallResult:
        """Remove the recognized native game and its shortcut, without map input."""
        progress = progress_callback or (lambda stage, message, percent=None: None)
        cancel_event = cancel_event or threading.Event()
        connection = self.connection_factory(settings)
        run_identifier = uuid.uuid4().hex
        cleanup_attempted = False

        def check_cancel():
            if cancel_event.is_set():
                raise CancelledError("Uninstall cancelled before removal. The game and saves were kept.")

        def remote_progress(line):
            activity = parse_activity(line)
            if activity is not None:
                progress(*activity)

        try:
            check_cancel()
            progress("connect", "Connecting securely to your Steam Frame...", None)
            connection.connect()
            check_cancel()
            progress("preflight", "Checking the native game location and safe uninstall support...", None)
            helper_source = self.remote_source()
            info = parse_result(run_remote_source(connection, helper_source, ["preflight-uninstall"] + storage_arguments(settings),
                progress=remote_progress, cancel_event=cancel_event, timeout=90))
            destination = validate_preflight_location(info, settings)
            upload = self.guarded_upload(connection, settings, destination, cancel_event)
            if info.get("uninstallSupported") is not True:
                raise SSHError("The Frame returned an unexpected uninstall location or capability.")
            remote_resources = info["cachePath"] + "/resources"
            for name in ("frame_storage.py", "remote_install.py", "steam_shortcut.py", "steam_live.py"):
                check_cancel()
                upload(self.resource_dir / name, remote_resources + "/" + name)
            check_cancel()
            progress("uninstall", "Removing the native game and its Steam entry. Please wait for removal to finish...", None)
            argv = ["python3", remote_resources + "/remote_install.py", "uninstall", "--run-id", run_identifier]
            argv += storage_arguments(settings)
            if keep_saves:
                argv.append("--keep-saves")
            # Once removal starts, finish the owned transaction rather than
            # abandoning it mid-delete. The GUI disables Cancel for this phase.
            data = parse_result(connection.run(argv, progress=remote_progress, timeout=600,
                timeout_message="Uninstall timed out before completion could be verified. Removal may be incomplete; reconnect and check the native game folder, save backup, and activity log before retrying."))
            steam = data.get("steam")
            if not isinstance(steam, dict):
                raise SSHError("The Frame returned an invalid uninstall result.")
            recovered, retained, warning = uninstall_history(data, destination["gamePath"])
            for text in ([warning] if warning else []) + ["Recovered campaign save backup: " + path for path in recovered] + ["Preserved uninstall folder: " + path for path in retained]:
                progress("detail", text, None)
            if steam.get("status") == "manual":
                diagnostic = steam.get("reason", "Steam could not close safely; the game was kept.") + "\n" + steam.get("instructions", "Use Steam's own interface to remove the native Halo shortcut, then retry when its library can be safely updated.")
                if warning:
                    diagnostic += "\n\n" + warning
                if recovered:
                    diagnostic += "\n\nRecovered campaign save backups:\n" + "\n".join(recovered)
                if retained:
                    diagnostic += "\n\nPreserved uninstall folders:\n" + "\n".join(retained)
                raise SSHError(diagnostic)
            uninstalled, absent = data.get("uninstalled"), data.get("alreadyAbsent", False)
            pending = data.get("removalPending", False)
            saved = data.get("savedBackupPath")
            if (data.get("gamePath") != info["gamePath"] or type(uninstalled) is not bool
                    or type(absent) is not bool or type(pending) is not bool
                    or (pending and (uninstalled or absent))
                    or (not pending and not (uninstalled or absent))
                    or (retained and not pending)
                    or steam.get("status") not in ("removed", "already-absent")
                    or (saved is not None and saved != str(PurePosixPath(destination["gamePath"]).parent) + "/HaloCENativeVR-saves-" + run_identifier)):
                raise SSHError("The Frame returned an invalid uninstall result.")
            host_fingerprint = connection.host_fingerprint
            progress("disconnect", "Closing the setup SSH connection...", None)
            cleanup_warning = close_connection(connection, progress)
            cleanup_attempted = True
            if cleanup_warning:
                progress("cleanup-pending", "Uninstall results were saved; setup's connection cleanup needs attention.", 99)
            else:
                progress("disconnected", "Setup has disconnected from your Frame.", None)
            if pending:
                progress("removal-pending", "Uninstall preserved folders that need attention. See the setup activity and recovery paths.", 99)
            elif not cleanup_warning:
                progress("complete", "Native Halo VR has been uninstalled." if uninstalled else "Native Halo VR was already absent; its Steam entry has been checked.", 100)
            return UninstallResult(info["gamePath"], uninstalled, absent, saved, steam, host_fingerprint,
                                   cleanup_warning=cleanup_warning, removal_pending=pending,
                                   removal_warning=warning, recovered_save_backup_paths=recovered,
                                   retained_quarantine_paths=retained, storage_id=settings.storage_id)
        finally:
            if not cleanup_attempted:
                cleanup_activity(progress, "Closing the setup SSH connection...")
                warning = close_connection(connection, progress)
                if warning is None:
                    cleanup_activity(progress, "Setup has disconnected from your Frame.")
                elif sys.exc_info()[1] is not None:
                    error = sys.exc_info()[1]
                    if isinstance(error, CancelledError):
                        error.requires_attention = True
                    error.args = (str(error) + "\n\n" + warning,)


def run(settings: Settings, maps_dir: Path | None, progress_callback=None,
        cancel_event: threading.Event | None = None) -> InstallResult:
    return Installer().run(settings, maps_dir, progress_callback, cancel_event)
