"""Exercise the actual remote build command without fetching or compiling a game."""

import importlib.util
import json
import struct
import sys
import types
from pathlib import Path

import pytest


RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def test_build_launches_package_manager_as_container_root_with_host_isolation(tmp_path, monkeypatch):
    if not hasattr(__import__("os"), "getuid"):
        monkeypatch.setattr(__import__("os"), "getuid", lambda: 0, raising=False)
    if "pwd" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: None))
    spec = importlib.util.spec_from_file_location("build_container_remote_install", RESOURCES / "remote_install.py")
    remote = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, remote)
    spec.loader.exec_module(remote)

    remote.HOME = tmp_path / "home"
    remote.HOME.mkdir()
    remote.CACHE = remote.HOME / "cache"
    remote.GAME = remote.HOME / "Games/HaloCENativeVR"
    remote.owned(remote.CACHE)
    resources = remote.CACHE / "resources"
    resources.mkdir()
    (resources / "frame-controls.patch").write_bytes(b"synthetic patch; git is mocked")
    script = (RESOURCES / "build-native.sh").read_bytes()
    (resources / "build-native.sh").write_bytes(script)

    run_id = "e" * 32
    directory = remote.CACHE / "runs" / run_id
    remote.owned(directory)
    remote.prepare(run_id)
    upload = directory / "upload"
    header = bytearray(2048)
    header[:4] = b"daeh"
    header[-4:] = b"toof"
    struct.pack_into("<II", header, 4, 5, len(header))
    header[64:77] = b"01.10.12.2276"
    files = []
    for relative in sorted(remote.EXPECTED_MAPS):
        target = upload / relative
        target.write_bytes(header)
        files.append({"path": relative, "size": len(header), "sha256": remote.digest(target)})
    manifest = {"files": files, "totalBytes": len(header) * len(files)}
    (upload / "xbox-data-manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(remote, "existing_install", lambda *args: None)
    original_which = remote.shutil.which
    monkeypatch.setattr(remote.shutil, "which", lambda name: (
        "podman" if name == "podman" else None if name == "systemd-inhibit" else original_which(name)))

    def git_command(argv, **kwargs):
        if argv[:2] == ["podman", "ps"]:
            return "[]"
        assert argv[0] == "git"
        if argv[1] == "init":
            Path(argv[2]).mkdir()
        if argv[-2:] == ["rev-parse", "HEAD"]:
            return remote.SOURCE_COMMIT
        return ""

    monkeypatch.setattr(remote, "command", git_command)
    launched = []

    def failed_container(argv, **kwargs):
        launched.append((list(argv), kwargs))
        kwargs["stdout"].write(b"Synthetic package-manager failure\n")
        return types.SimpleNamespace(returncode=100, poll=lambda: 100)

    monkeypatch.setattr(remote.subprocess, "Popen", failed_container)
    with pytest.raises(RuntimeError, match="Native build failed"):
        remote.build(run_id)

    assert len(launched) == 1
    argv, kwargs = launched[0]
    assert argv[:3] == ["podman", "run", "--rm"]
    assert "--user=0:0" in argv
    assert "--userns=keep-id:uid=0,gid=0" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert argv[argv.index("--name") + 1] == "halo-frame-installer-" + run_id
    assert "org.halo-frame-installer.owner=" + remote.OWNER in argv
    assert "org.halo-frame-installer.run=" + run_id in argv
    assert argv.count("--volume") == 1
    assert argv[argv.index("--volume") + 1] == str(directory) + ":/build:rw"
    assert argv[argv.index("--workdir") + 1] == "/build"
    assert argv[-3:] == [remote.BUILD_CONTAINER_IMAGE, "/bin/bash", "/build/build-native.sh"]
    assert remote.BUILD_CONTAINER_IMAGE.startswith("docker.io/library/ubuntu:22.04@sha256:")
    assert kwargs["start_new_session"] is True
    assert not kwargs.get("shell", False)
    assert not any(option in argv for option in (
        "sudo", "--privileged", "--network=host", "--cap-add=ALL", "--cap-add=all",
        "--security-opt=seccomp=unconfined", "--security-opt=apparmor=unconfined",
    ))
    assert (directory / "build-native.sh").read_bytes() == script
    assert remote.verify_maps(upload, manifest) == len(header) * len(files)
    assert not remote.GAME.exists()
