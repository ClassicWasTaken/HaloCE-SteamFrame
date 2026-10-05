"""Retry previously uploaded maps without trusting unfinished native builds."""
import importlib.util
import json
import os
import struct
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from halo_frame_installer.install import EXPECTED_MAPS, Installer
from halo_frame_installer.ssh import Settings, SSHError

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
OLD_RUN = "a" * 32
NEW_RUN = "b" * 32


@pytest.fixture
def remote(tmp_path, monkeypatch):
    if "pwd" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: None))
    if not hasattr(os, "getuid"):
        monkeypatch.setattr(os, "getuid", lambda: tmp_path.stat().st_uid, raising=False)
    spec = importlib.util.spec_from_file_location("retry_remote_install", RESOURCES / "remote_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HOME = tmp_path / "home"
    module.HOME.mkdir()
    module.CACHE = module.HOME / "cache"
    module.GAME = module.HOME / "Games/HaloCENativeVR"
    monkeypatch.setattr(module, "game_closed", lambda: None)
    module.owned(module.CACHE)
    (module.CACHE / "runs").mkdir()
    return module


def make_maps(directory, remote):
    (directory / "maps").mkdir(parents=True, exist_ok=True)
    header = bytearray(2048)
    header[:4], header[-4:] = b"daeh", b"toof"
    struct.pack_into("<II", header, 4, 5, 2048)
    header[64:77] = b"01.10.12.2276"
    files = []
    for relative in sorted(remote.EXPECTED_MAPS):
        target = directory / relative
        target.write_bytes(header)
        files.append({"path": relative, "size": len(header), "sha256": remote.digest(target)})
    manifest = {"files": files, "totalBytes": len(header) * len(files)}
    (directory / "xbox-data-manifest.json").write_text(json.dumps(manifest))
    return manifest


def prepare_retry(remote):
    remote.prepare(OLD_RUN)
    older = remote.run_dir(OLD_RUN)
    manifest = make_maps(older / "upload", remote)
    (older / "native-build.log").write_text("Previous isolated compiler setup failed.")
    remote.prepare(NEW_RUN)
    current = remote.run_dir(NEW_RUN)
    (current / "upload/xbox-data-manifest.json").write_text(json.dumps(manifest))
    return older, current, manifest


def test_owned_failed_upload_is_reused_without_changing_old_files_or_saves(remote):
    older, current, manifest = prepare_retry(remote)
    before = {str(path.relative_to(older)): path.read_bytes() for path in older.rglob("*") if path.is_file()}
    saves = remote.HOME / "unrelated/save"
    saves.parent.mkdir()
    saves.write_bytes(b"campaign progress")
    assert remote.reuse_upload(NEW_RUN) == {"reusedUpload": True, "mapsRun": OLD_RUN}
    metadata = remote.read_marker(current / remote.MARKER)
    assert metadata["mapsOrigin"] == "retained"
    assert remote.maps_source(current, metadata, manifest) == older / "upload"
    assert list((current / "upload/maps").iterdir()) == []
    assert before == {str(path.relative_to(older)): path.read_bytes() for path in older.rglob("*") if path.is_file()}
    assert saves.read_bytes() == b"campaign progress"


@pytest.mark.parametrize("problem", ["owner", "source", "reference", "mismatch", "corrupt", "extra", "oversize", "malformed"])
def test_invalid_retained_upload_falls_back_without_modifying_candidate(remote, problem):
    older, current, manifest = prepare_retry(remote)
    marker = older / remote.MARKER
    if problem in ("owner", "source", "reference"):
        value = json.loads(marker.read_text())
        value[{"owner": "owner", "source": "sourceCommit", "reference": "mapsOrigin"}[problem]] = "unrecognized"
        marker.write_text(json.dumps(value))
    elif problem == "mismatch":
        manifest["files"][0]["sha256"] = "0" * 64
        (older / "upload/xbox-data-manifest.json").write_text(json.dumps(manifest))
    elif problem == "corrupt":
        (older / "upload/maps/a10.map").write_bytes(b"damaged")
    elif problem == "extra":
        (older / "upload/maps/custom.map").write_bytes(b"unrelated")
    elif problem == "oversize":
        (older / "upload/xbox-data-manifest.json").write_bytes(b" " * (remote.MAX_MANIFEST_BYTES + 1))
    else:
        (older / "upload/xbox-data-manifest.json").write_text('{"files": [null]}')
    before = {str(path.relative_to(older)): path.read_bytes() for path in older.rglob("*") if path.is_file()}
    assert remote.reuse_upload(NEW_RUN) == {"reusedUpload": False}
    assert remote.read_marker(current / remote.MARKER)["mapsOrigin"] == "upload"
    assert before == {str(path.relative_to(older)): path.read_bytes() for path in older.rglob("*") if path.is_file()}


@pytest.mark.parametrize("link", ["symbolic", "hard"])
def test_linked_retained_map_is_not_reused(remote, link):
    older, _, _ = prepare_retry(remote)
    target = older / "upload/maps/a10.map"
    original = target.read_bytes()
    alternate = remote.HOME / "other.map"
    alternate.write_bytes(original)
    target.unlink()
    try:
        if link == "symbolic":
            target.symlink_to(alternate)
        else:
            os.link(alternate, target)
    except OSError:
        pytest.skip("This host cannot create the requested filesystem link.")
    assert remote.reuse_upload(NEW_RUN) == {"reusedUpload": False}
    assert alternate.read_bytes() == original


def test_retained_run_path_cannot_escape_owned_runs(remote):
    _, current, manifest = prepare_retry(remote)
    metadata = remote.read_marker(current / remote.MARKER)
    metadata.update(mapsOrigin="retained", mapsRun="../outside")
    with pytest.raises(ValueError, match="identifier"):
        remote.maps_source(current, metadata, manifest)


def test_retry_candidate_count_is_bounded(remote, monkeypatch):
    older, current, _ = prepare_retry(remote)
    monkeypatch.setattr(remote, "MAX_RETRY_RUNS", 1)
    newest = remote.run_dir("c" * 32)
    remote.prepare("c" * 32)
    os.utime(newest, ns=(older.stat().st_atime_ns + 10_000_000_000, older.stat().st_mtime_ns + 10_000_000_000))
    # The newest incomplete run consumes the one permitted candidate lookup;
    # the older complete upload remains untouched and a normal upload follows.
    assert remote.reuse_upload(NEW_RUN) == {"reusedUpload": False}
    assert remote.read_marker(current / remote.MARKER)["mapsOrigin"] == "upload"


def test_cancellation_during_retained_hashing_is_not_swallowed(remote, monkeypatch):
    _, current, _ = prepare_retry(remote)
    digest = remote.digest
    def cancel_after_hash(path):
        result = digest(path)
        (current / "cancelled").touch()
        return result
    monkeypatch.setattr(remote, "digest", cancel_after_hash)
    with pytest.raises(RuntimeError, match="cancelled"):
        remote.reuse_upload(NEW_RUN)
    assert remote.read_marker(current / remote.MARKER)["mapsOrigin"] == "upload"


def test_build_rechecks_retained_hashes_before_fetching_source(remote, monkeypatch):
    older, _, _ = prepare_retry(remote)
    assert remote.reuse_upload(NEW_RUN)["reusedUpload"] is True
    target = older / "upload/maps/a10.map"
    changed = bytearray(target.read_bytes())
    changed[100] = 1
    target.write_bytes(changed)
    command = Mock()
    monkeypatch.setattr(remote, "command", command)
    with pytest.raises(ValueError, match="verification failed"):
        remote.build(NEW_RUN)
    command.assert_not_called()


def test_finalize_rechecks_retained_hashes_before_publishing(remote, monkeypatch):
    older, current, _ = prepare_retry(remote)
    assert remote.reuse_upload(NEW_RUN)["reusedUpload"] is True
    build = current / "src/build/linux_arm64"
    build.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    (build / "halo").write_bytes(header)
    (build / "libSDL3.so.0").write_bytes(header)
    changed = bytearray((older / "upload/maps/a10.map").read_bytes())
    changed[100] = 1
    (older / "upload/maps/a10.map").write_bytes(changed)
    with pytest.raises(ValueError, match="verification failed"):
        remote.finalize(NEW_RUN)
    assert not remote.GAME.exists()


def test_finalize_copies_only_verified_retained_maps_and_keeps_old_upload(remote, monkeypatch):
    older, current, manifest = prepare_retry(remote)
    (older / "src").mkdir()
    (older / "src/unfinished-build").write_bytes(b"do not resume this old build")
    assert remote.reuse_upload(NEW_RUN)["reusedUpload"] is True
    assert not (current / "src").exists()
    build = current / "src/build/linux_arm64"
    build.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    (build / "halo").write_bytes(header)
    (build / "libSDL3.so.0").write_bytes(header)
    resources = remote.CACHE / "resources"
    resources.mkdir()
    (resources / "frame-controls.patch").write_bytes(b"verified native controls")
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "libraries resolved")
    def publish(source, target):
        assert not target.exists()
        source.rename(target)
    monkeypatch.setattr(remote, "rename_noreplace", publish)
    response = remote.finalize(NEW_RUN)
    assert response["gamePath"] == str(remote.GAME)
    assert remote.verify_maps(remote.GAME, manifest) == manifest["totalBytes"]
    assert remote.verify_maps(older / "upload", manifest) == manifest["totalBytes"]
    assert (older / "src/unfinished-build").read_bytes() == b"do not resume this old build"
    assert not (remote.GAME / "unfinished-build").exists()
    assert list((remote.GAME / "save").iterdir()) == []


class RetryConnection:
    def __init__(self, settings, reused):
        self.settings, self.reused = settings, reused
        self.commands, self.uploads = [], []
        self.host_fingerprint = "SHA256:public"
        self.closed = False
    def connect(self):
        pass
    def close(self):
        self.closed = True
    def put(self, local, remote, **kwargs):
        self.uploads.append(remote)
    def run(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[1] == "-c":
            response = {"home": "/home/steamos", "cachePath": "/home/steamos/.cache/halo-frame-installer",
                        "gamePath": "/home/steamos/Games/HaloCENativeVR", "existing": None,
                        "retainedUploadReuse": True}
        elif argv[2] == "prepare":
            value = argv[argv.index("--run-id") + 1]
            response = {"uploadPath": "/home/steamos/.cache/halo-frame-installer/runs/" + value + "/upload"}
        elif argv[2] == "reuse-upload":
            response = {"reusedUpload": self.reused, "mapsRun": OLD_RUN}
        elif argv[2] == "build":
            raise SSHError("Simulated subsequent build failure.")
        else:
            raise AssertionError(argv)
        return "HFI_RESULT " + json.dumps(response)


@pytest.mark.parametrize("reused", [True, False])
def test_host_skips_map_transfer_only_after_verified_retained_upload(tmp_path, reused):
    maps = tmp_path / "maps"
    maps.mkdir()
    for name in EXPECTED_MAPS:
        (maps / name).write_bytes(b"local test data".ljust(2048, b"\0"))
    connection = RetryConnection(Settings("frame", "private"), reused)
    with pytest.raises(SSHError, match="subsequent build failure"):
        Installer(lambda settings: connection, RESOURCES).run(connection.settings, maps)
    assert sum(path.endswith(".map") for path in connection.uploads) == (0 if reused else 24)
    assert sum(path.endswith("/xbox-data-manifest.json") for path in connection.uploads) == 1
    assert any(command[2] == "reuse-upload" for command in connection.commands if command[1] != "-c")
    assert connection.closed
    assert not any(command[2] in ("finalize", "shortcut") for command in connection.commands if command[1] != "-c")


@pytest.mark.parametrize("response", [{"reusedUpload": "yes"}, {"reusedUpload": True, "mapsRun": "../outside"}])
def test_host_rejects_malformed_retained_reuse_response(tmp_path, response):
    maps = tmp_path / "maps"
    maps.mkdir()
    for name in EXPECTED_MAPS:
        (maps / name).write_bytes(b"local test data".ljust(2048, b"\0"))
    class MalformedConnection(RetryConnection):
        def run(self, argv, **kwargs):
            if len(argv) > 2 and argv[2] == "reuse-upload":
                self.commands.append(argv)
                return "HFI_RESULT " + json.dumps(response)
            return super().run(argv, **kwargs)
    connection = MalformedConnection(Settings("frame", "private"), True)
    with pytest.raises(SSHError, match="invalid retained upload response"):
        Installer(lambda settings: connection, RESOURCES).run(connection.settings, maps)
    assert not any(path.endswith(".map") for path in connection.uploads)
    assert not any(command[2] == "build" for command in connection.commands if command[1] != "-c")
    assert connection.closed
