"""Coordinate an owned, atomic Steam Frame native VR installation."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ssh import CancelledError, Settings, SSHConnection, SSHError

SOURCE_COMMIT = "88142798513ebd99fc7c6224023e8b44c05d0106"
EXPECTED_MAPS = frozenset(name + ".map" for name in (
    "a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40",
    "beavercreek", "bloodgulch", "boardingaction", "carousel", "chillout", "damnation",
    "hangemhigh", "longest", "prisoner", "putput", "ratrace", "sidewinder", "ui", "wizard"))
ProgressCallback = Callable[[str, str, float | None], None]


def resources_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "resources"
    return Path(__file__).resolve().parents[2] / "resources"


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


def parse_result(output: str) -> dict:
    lines = [line[len("HFI_RESULT "):] for line in output.splitlines() if line.startswith("HFI_RESULT ")]
    if len(lines) != 1:
        raise SSHError("The Frame returned an unexpected installer response.")
    result = json.loads(lines[0])
    if not isinstance(result, dict):
        raise SSHError("The Frame returned an invalid installer result.")
    return result


@dataclass(frozen=True)
class InstallResult:
    game_path: str
    reused: bool
    steam: dict
    host_fingerprint: str | None
    source_commit: str = SOURCE_COMMIT
    repaired: bool = False
    backup_path: str | None = None

    @property
    def steam_appid(self) -> int | None:
        return self.steam.get("appid")

    @property
    def requires_manual_steam_step(self) -> bool:
        return self.steam.get("status") != "added"


class Installer:
    def __init__(self, connection_factory=SSHConnection, resource_dir: Path | None = None):
        self.connection_factory = connection_factory
        self.resource_dir = resource_dir or resources_path()

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

        def check_cancel():
            if cancel_event.is_set():
                raise CancelledError("Installation cancelled. Existing games and saves were kept.")

        def remote_progress(line):
            if line.startswith("HFI_PROGRESS "):
                data = json.loads(line[len("HFI_PROGRESS "):])
                progress(data["stage"], data["message"], None)

        def cancel_remote():
            if remote_helper is not None and prepared:
                connection.run(["python3", remote_helper, "cancel", "--run-id", run_identifier], timeout=45)

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
            if name == "shortcut" and settings.close_steam_for_shortcut:
                argv.append("--close-steam")
            return parse_result(connection.run(argv, progress=remote_progress,
                                cancel_event=cancel_event, timeout=timeout,
                                on_cancel=cancel_remote if prepared else None))

        try:
            check_cancel()
            progress("connect", "Connecting securely to your Steam Frame...", None)
            connection.connect()
            check_cancel()
            progress("preflight", "Checking ARM64 SteamOS, SteamVR, Podman and free space...", None)
            source = (self.resource_dir / "remote_install.py").read_text(encoding="utf-8")
            preflight_args = ["python3", "-c", source, "preflight"]
            if repair:
                preflight_args.append("--repair")
            if repair and settings.adopt_existing_native:
                preflight_args.append("--adopt-existing")
            info = parse_result(connection.run(preflight_args,
                                               progress=remote_progress, cancel_event=cancel_event, timeout=90))
            if info.get("home") != "/home/steamos" or info.get("cachePath") != "/home/steamos/.cache/halo-frame-installer" or info.get("gamePath") != "/home/steamos/Games/HaloCENativeVR":
                raise SSHError("The Frame reported an unexpected installation location.")
            if info.get("pcVersionDetected"):
                progress("detect", "Found an older Halo PC installation. The native VR build requires original Xbox maps.", None)
            remote_resources = info["cachePath"] + "/resources"
            for name in ("remote_install.py", "build-native.sh", "steam_shortcut.py", "frame-controls.patch"):
                check_cancel()
                connection.put(self.resource_dir / name, remote_resources + "/" + name, cancel_event=cancel_event)
            # Artwork ships inside the one-file installer; no metadata service or
            # account API key is needed, including an Add to Steam again retry.
            for name in ("halo-ce-cover.jpg", "halo-ce-landscape.png"):
                check_cancel()
                connection.put(self.resource_dir / "artwork" / name,
                               remote_resources + "/artwork/" + name, cancel_event=cancel_event)
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
                        connection.put(manifest_path, expected_upload + "/xbox-data-manifest.json", cancel_event=cancel_event)
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
                            connection.put(path, expected_upload + "/" + entry["path"],
                                           callback=uploaded, cancel_event=cancel_event)
                            transferred += entry["size"]
                step("build", run_id=True, timeout=7200)
                check_cancel()
                installed = step("finalize", run_id=True, timeout=600)
            check_cancel()
            progress("steam", "Adding the native VR game and Halo box art to your Steam account while Steam is closed...", None)
            steam = step("shortcut", timeout=90)
            progress("complete", "Native VR game is ready. Start Steam and launch Halo: Combat Evolved VR (Native)." if steam.get("status") == "added" else "Native VR game is installed. One Steam library step remains.", 100)
            return InstallResult(installed["gamePath"], bool(installed.get("reused")),
                                 steam, connection.host_fingerprint, repaired=bool(installed.get("repaired")),
                                 backup_path=installed.get("backupPath"))
        except CancelledError:
            try:
                cancel_remote()
            except (SSHError, OSError):
                pass
            raise
        finally:
            connection.close()

    def add_to_steam(self, settings: Settings, progress_callback: ProgressCallback | None = None,
                     cancel_event: threading.Event | None = None) -> InstallResult:
        """Retry library registration without extraction, upload or rebuilding."""
        return self.run(settings, None, progress_callback, cancel_event, registration_only=True)


def run(settings: Settings, maps_dir: Path | None, progress_callback=None,
        cancel_event: threading.Event | None = None) -> InstallResult:
    return Installer().run(settings, maps_dir, progress_callback, cancel_event)
