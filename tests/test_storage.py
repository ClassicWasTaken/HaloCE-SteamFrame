"""Synthetic mounted-card identities; no device, game disc or SSH is used."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import types

import pytest

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def resource(name):
    spec = importlib.util.spec_from_file_location(name, RESOURCES / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def storage(tmp_path, monkeypatch):
    module = resource("frame_storage")
    monkeypatch.setitem(sys.modules, "frame_storage", module)
    home, card = tmp_path / "home", tmp_path / "card"
    home.mkdir()
    card.mkdir()
    module.TEST_HOME, module.TEST_CARD = home, card
    if not hasattr(os, "getuid"):
        monkeypatch.setattr(os, "getuid", lambda: home.stat().st_uid, raising=False)
    return module


def card_descriptor(storage, *, mount_id=10, device="179:1", cid="a" * 64):
    root = storage.TEST_CARD
    identity = {"kind": "sd", "mountPath": str(root), "mountId": mount_id, "device": device,
                "filesystem": "ext4", "rootDevice": root.stat().st_dev, "rootInode": root.stat().st_ino,
                "cardIdentity": cid, "filesystemUuid": "filesystem-123", "blockDevice": "/dev/mmcblk0p1"}
    ownership = storage.ownership_identity(identity)
    identifier = "sd:" + hashlib.sha256(json.dumps(ownership, sort_keys=True).encode()).hexdigest()[:32]
    return storage._descriptor(identifier, "sd", root, identity, storage.TEST_HOME)


@pytest.fixture
def sd_remote(storage, monkeypatch):
    if "pwd" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_name="steamos")))
    spec = importlib.util.spec_from_file_location("storage_remote_test", RESOURCES / "remote_install.py")
    remote = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(remote)
    remote.HOME = storage.TEST_HOME
    state = {"card": card_descriptor(storage)}
    internal = storage._descriptor("internal", "internal", remote.HOME, {"kind": "internal", "root": str(remote.HOME)}, remote.HOME)
    monkeypatch.setattr(storage, "discover_storage", lambda home=remote.HOME: {"home": str(home), "destinations": [internal, state["card"]]})
    remote.select_storage(state["card"]["id"])
    remote.owned(remote.CACHE)
    (remote.CACHE / "runs").mkdir()
    monkeypatch.setattr(remote, "game_closed", lambda *args: None)
    monkeypatch.setattr(remote, "uninstall_mounts", lambda: [])
    return remote, state


def test_internal_destination_and_exact_game_path(storage):
    inventory = storage.discover_storage(storage.TEST_HOME)
    internal = inventory["destinations"][0]
    assert internal["id"] == "internal"
    assert internal["gamePath"] == str(storage.TEST_HOME / "Games/HaloCENativeVR")
    validated = storage.validate_game_path(storage.TEST_HOME, Path(internal["gamePath"]))
    assert validated["id"] == internal["id"]
    assert validated["gamePath"] == internal["gamePath"]
    assert validated["ownershipIdentity"] == internal["ownershipIdentity"]
    for invalid in (storage.TEST_HOME / "Games/AnotherGame", storage.TEST_HOME / "Games/HaloCENativeVR/../Other", storage.TEST_HOME):
        with pytest.raises(ValueError):
            storage.validate_game_path(storage.TEST_HOME, invalid)


def test_sd_validation_uses_only_current_discovered_fixed_leaf(storage, monkeypatch):
    descriptor = card_descriptor(storage)
    monkeypatch.setattr(storage, "discover_storage", lambda home: {"destinations": [descriptor]})
    assert storage.validate_game_path(storage.TEST_HOME, Path(descriptor["gamePath"])) == descriptor
    with pytest.raises(ValueError):
        storage.validate_game_path(storage.TEST_HOME, storage.TEST_CARD / "Games/Other")
    with pytest.raises(ValueError):
        storage.resolve_storage("sd:" + "f" * 32, storage.TEST_HOME)
    with pytest.raises(ValueError):
        storage.resolve_storage(str(storage.TEST_CARD), storage.TEST_HOME)


@pytest.mark.parametrize("name", ["bad$label", "bad`label", 'bad"label', "bad'label", "bad\\label", "bad:label", "bad\nlabel", "bad;label"])
def test_unsafe_mount_labels_are_rejected(storage, name):
    assert not storage._mount_path_allowed(Path("/run/media/steamos") / name, Path("/home/steamos"))


def test_spaces_unicode_and_legacy_mount_layout_are_supported(storage):
    assert storage._mount_path_allowed(Path("/run/media/steamos/My SD_日本"), Path("/home/steamos"))
    assert storage._mount_path_allowed(Path("/run/media/mmcblk0p1"), Path("/home/steamos"))
    assert not storage._mount_path_allowed(Path("/tmp/card"), Path("/home/steamos"))


def mounted_record(storage):
    return {"mountId": 20, "device": "0:0", "root": "/", "path": storage.TEST_CARD,
            "options": {"rw"}, "superOptions": {"rw"}, "filesystem": "ext4", "source": "/dev/mmcblk0p1"}


def discovery_fixture(storage, monkeypatch, records):
    monkeypatch.setattr(storage.platform, "system", lambda: "Linux")
    monkeypatch.setattr(storage, "_mount_records", lambda: records)
    monkeypatch.setattr(storage, "_mount_path_allowed", lambda path, home: path == storage.TEST_CARD)
    monkeypatch.setattr(storage.os, "major", lambda dev: 0, raising=False)
    monkeypatch.setattr(storage.os, "minor", lambda dev: 0, raising=False)
    monkeypatch.setattr(storage, "_sd_identity", lambda record: {"cardIdentity": "a" * 64, "filesystemUuid": "uuid-123", "blockDevice": "/dev/mmcblk0p1"})


def test_discovery_card_id_survives_remount_but_live_identity_changes(storage, monkeypatch):
    record = mounted_record(storage)
    discovery_fixture(storage, monkeypatch, [record])
    first = storage.discover_storage(storage.TEST_HOME)["destinations"][1]
    record["mountId"] = 99
    second = storage.discover_storage(storage.TEST_HOME)["destinations"][1]
    assert first["id"] == second["id"]
    assert first["ownershipIdentity"] == second["ownershipIdentity"]
    assert first["identity"] != second["identity"]


@pytest.mark.parametrize("problem", ["read-only", "noexec", "unsupported-fs", "bind-root", "descendant-bind", "duplicate-device", "wrong-card"])
def test_ineligible_mounts_are_not_destinations(storage, monkeypatch, problem):
    record = mounted_record(storage)
    records = [record]
    if problem == "read-only":
        record["options"] = {"ro"}
    elif problem == "noexec":
        record["options"].add("noexec")
    elif problem == "unsupported-fs":
        record["filesystem"] = "exfat"
    elif problem == "bind-root":
        record["root"] = "/subdirectory"
    elif problem == "descendant-bind":
        records.append({**record, "path": storage.TEST_CARD / "Games", "device": "1:1"})
    elif problem == "duplicate-device":
        records.append({**record, "path": storage.TEST_HOME / "other-mount"})
    discovery_fixture(storage, monkeypatch, records)
    if problem == "wrong-card":
        def not_sd(record):
            raise ValueError("Kernel card type is MMC, not SD")
        monkeypatch.setattr(storage, "_sd_identity", not_sd)
    inventory = storage.discover_storage(storage.TEST_HOME)
    assert len(inventory["destinations"]) == 1
    assert inventory["unavailable"]


def test_unrecognized_sd_mount_layout_is_reported_without_authorizing_it(storage, monkeypatch):
    record = mounted_record(storage)
    discovery_fixture(storage, monkeypatch, [record])
    monkeypatch.setattr(storage, "_mount_path_allowed", lambda path, home: False)
    inventory = storage.discover_storage(storage.TEST_HOME)
    assert len(inventory["destinations"]) == 1
    assert inventory["unavailable"][0]["mountPath"] == str(storage.TEST_CARD)
    assert "mount locations" in inventory["unavailable"][0]["reason"]


def test_discovery_cli_reports_wrong_system_without_traceback():
    result = subprocess.run([sys.executable, str(RESOURCES / "frame_storage.py")],
                            text=True, capture_output=True, timeout=10)
    # Unit/CI runners are never the Frame's privileged hardware fixture.
    assert result.returncode == 1
    assert result.stdout.startswith("HFI_ERROR ")
    assert "Traceback" not in result.stdout + result.stderr


def test_sd_cache_and_game_use_selected_filesystem_without_internal_migration(sd_remote):
    remote, _ = sd_remote
    internal = remote.HOME / "Games/HaloCENativeVR"
    internal.mkdir(parents=True)
    (internal / "save.txt").write_bytes(b"internal progress")
    response = remote.prepare("a" * 32)
    assert remote.GAME == remote.storage_root() / "Games/HaloCENativeVR"
    assert remote.CACHE == remote.storage_root() / ".halo-frame-installer"
    assert Path(response["uploadPath"]).is_relative_to(remote.CACHE)
    assert (internal / "save.txt").read_bytes() == b"internal progress"
    assert not remote.GAME.exists()


def test_same_card_after_reboot_reuses_cache_but_old_active_run_is_refused(sd_remote):
    remote, state = sd_remote
    identifier = "b" * 32
    remote.prepare(identifier)
    previous = remote.read_marker(remote.run_dir(identifier) / remote.MARKER)
    state["card"] = card_descriptor(remote.storage_module(), mount_id=90, device="179:33")
    remote.select_storage(state["card"]["id"])
    remote.owned(remote.CACHE)
    remote.check_storage_record(previous)
    with pytest.raises(ValueError, match="earlier SD mount"):
        remote.build(identifier)
    with pytest.raises(ValueError, match="earlier SD mount"):
        remote.prepare(identifier)
    fresh = remote.prepare("c" * 32)
    assert Path(fresh["uploadPath"]).is_relative_to(remote.CACHE)


def test_free_space_and_installed_status_are_not_ownership_identity(sd_remote):
    remote, state = sd_remote
    before = remote.read_marker(remote.CACHE / remote.MARKER)
    state["card"]["freeBytes"] = 1
    state["card"]["installed"] = True
    remote.select_storage(state["card"]["id"])
    remote.check_storage_record(before)


def test_different_card_cannot_adopt_copied_cache_or_operation_journal(sd_remote):
    remote, state = sd_remote
    remote.prepare("d" * 32)
    old = remote.read_marker(remote.run_dir("d" * 32) / remote.MARKER)
    state["card"] = card_descriptor(remote.storage_module(), cid="f" * 64)
    remote.select_storage(state["card"]["id"])
    with pytest.raises(ValueError, match="another storage"):
        remote.owned(remote.CACHE)
    with pytest.raises(ValueError, match="another storage"):
        remote.check_storage_record(old)


def test_active_card_remount_is_detected_before_more_file_operations(sd_remote):
    remote, state = sd_remote
    state["card"] = card_descriptor(remote.storage_module(), mount_id=100)
    with pytest.raises(ValueError, match="SD card changed"):
        remote.assert_storage_active(force=True)


def test_uninstall_sd_preserves_saves_and_other_internal_and_card_games(sd_remote, monkeypatch):
    remote, _ = sd_remote
    remote.owned(remote.GAME)
    (remote.GAME / "halo").write_bytes(b"native program")
    (remote.GAME / "save-v1.4").mkdir()
    (remote.GAME / "save-v1.4/checkpoint").write_bytes(b"my campaign")
    other = remote.GAME.parent / "OtherGame"
    other.mkdir()
    (other / "keep").write_bytes(b"another game")
    internal = remote.HOME / "Games/HaloCENativeVR"
    internal.mkdir(parents=True)
    (internal / "keep").write_bytes(b"internal game")
    monkeypatch.setattr(remote, "preflight_uninstall", lambda: {})
    monkeypatch.setattr(remote, "no_active_build", lambda: None)
    monkeypatch.setitem(sys.modules, "steam_shortcut", types.SimpleNamespace(remove_native_shortcut=lambda *args, **kwargs: {"status": "removed"}))
    def rename(source, target):
        assert not target.exists()
        source.rename(target)
    monkeypatch.setattr(remote, "rename_noreplace", rename)
    result = remote.uninstall("e" * 32, keep_saves=True)
    assert result["uninstalled"] and not remote.GAME.exists()
    assert (Path(result["savedBackupPath"]) / "save-v1.4/checkpoint").read_bytes() == b"my campaign"
    assert (other / "keep").read_bytes() == b"another game"
    assert (internal / "keep").read_bytes() == b"internal game"


def test_same_card_recovery_keeps_inode_guard_across_new_device_number(sd_remote):
    remote, _ = sd_remote
    remote.GAME.mkdir(parents=True)
    expected = remote.uninstall_root_identity(remote.GAME)
    expected["device"] += 1
    with pytest.raises(ValueError, match="another storage"):
        remote.same_uninstall_root(expected, remote.GAME)
    remote.same_uninstall_root(expected, remote.GAME, remote.storage_fields())
    expected["inode"] += 1
    with pytest.raises(ValueError, match="identity"):
        remote.same_uninstall_root(expected, remote.GAME, remote.storage_fields())


def native_build_fixture(remote, identifier, payload=b"fixture executable"):
    directory = remote.run_dir(identifier)
    build = directory / "src/build/linux_arm64"
    build.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    (build / "halo").write_bytes(header + payload)
    (build / "libSDL3.so.0").write_bytes(header)
    (build / "brokers.txt").write_text("broker.example.org:1883\n")
    resources = remote.CACHE / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "frame-controls.patch").write_bytes(b"verified controls")
    return directory


def maps_fixture(remote, directory):
    header = bytearray(2048)
    header[:4], header[-4:] = b"daeh", b"toof"
    struct.pack_into("<II", header, 4, 5, 2048)
    header[64:77] = b"01.10.12.2276"
    files = []
    for relative in sorted(remote.EXPECTED_MAPS):
        path = directory / relative
        path.write_bytes(header)
        files.append({"path": relative, "size": len(header), "sha256": remote.digest(path)})
    manifest = {"files": files, "totalBytes": len(header) * len(files)}
    (directory / "xbox-data-manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_sd_install_then_repair_after_reboot_preserves_saves_and_internal_copy(sd_remote, monkeypatch):
    remote, state = sd_remote
    internal = remote.HOME / "Games/HaloCENativeVR"
    internal.mkdir(parents=True)
    (internal / "keep").write_bytes(b"internal game")
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: "libraries resolved")
    def publish(source, destination):
        assert source.is_relative_to(remote.CACHE) and destination == remote.GAME
        assert source.stat().st_dev == destination.parent.stat().st_dev
        assert not destination.exists()
        source.rename(destination)
    monkeypatch.setattr(remote, "rename_noreplace", publish)
    first = "1" * 32
    remote.prepare(first)
    directory = native_build_fixture(remote, first)
    manifest = maps_fixture(remote, directory / "upload")
    assert remote.finalize(first)["gamePath"] == str(remote.GAME)
    assert remote.verify_maps(remote.GAME, manifest) == manifest["totalBytes"]
    (remote.save_root() / "checkpoint").write_bytes(b"campaign progress")
    config = remote.GAME / "config.toml"
    config.write_text(config.read_text().replace("resolution_scale = 1.0", "resolution_scale = 0.65"))
    old_program = (remote.GAME / "halo").read_bytes()
    state["card"] = card_descriptor(remote.storage_module(), mount_id=88, device="179:33")
    remote.select_storage(state["card"]["id"])
    second = "2" * 32
    remote.prepare(second, use_existing_maps=True, repair=True)
    native_build_fixture(remote, second, b"repaired executable")
    response = remote.finalize(second, repair=True)
    assert response["repaired"] and not response["mapsReinstalled"]
    assert (remote.GAME / "halo").read_bytes() != old_program
    assert remote.verify_maps(remote.GAME, manifest) == manifest["totalBytes"]
    assert (remote.save_root() / "checkpoint").read_bytes() == b"campaign progress"
    assert "resolution_scale = 0.65" in config.read_text()
    assert (internal / "keep").read_bytes() == b"internal game"
    metadata = remote.read_marker(remote.GAME / remote.MARKER)
    assert metadata["storageIdentity"] == state["card"]["identity"]


def test_interrupted_sd_uninstall_recovers_after_same_card_remount(sd_remote, monkeypatch):
    remote, state = sd_remote
    remote.owned(remote.GAME)
    (remote.GAME / "halo").write_bytes(b"native program")
    monkeypatch.setattr(remote, "preflight_uninstall", lambda: {})
    monkeypatch.setattr(remote, "no_active_build", lambda: None)
    monkeypatch.setitem(sys.modules, "steam_shortcut", types.SimpleNamespace(remove_native_shortcut=lambda *args, **kwargs: {"status": "removed"}))
    monkeypatch.setattr(remote, "rename_noreplace", lambda source, target: source.rename(target))
    remove = remote.remove_uninstall_tree
    def interrupted(directory, inventory, completed, total):
        (directory / "halo").unlink()
        completed[0] += 1
        raise RuntimeError("simulated device shutdown")
    monkeypatch.setattr(remote, "remove_uninstall_tree", interrupted)
    identifier = "3" * 32
    with pytest.raises(RuntimeError, match="Remaining native files"):
        remote.uninstall(identifier)
    directory = remote.run_dir(identifier)
    journal = remote.read_marker(directory / remote.MARKER)
    quarantine = Path(journal["quarantinePath"])
    assert quarantine.exists() and not remote.GAME.exists()
    # The real filesystem is unchanged in this fixture; record the old kernel
    # device number to exercise reboot recovery without mounting any device.
    journal["quarantineRoot"]["device"] += 100
    (directory / remote.MARKER).write_text(json.dumps(journal))
    state["card"] = card_descriptor(remote.storage_module(), mount_id=101, device="179:33")
    remote.select_storage(state["card"]["id"])
    monkeypatch.setattr(remote, "remove_uninstall_tree", remove)
    recovery = remote.recover_interrupted_uninstall()
    assert recovery["removed"] == 1 and not recovery["retained"]
    assert not quarantine.exists()
    assert remote.read_marker(directory / remote.MARKER)["state"] == "complete"


def test_live_sd_build_detects_remount_and_stops_labeled_container_without_card_writes(sd_remote, monkeypatch):
    remote, state = sd_remote
    identifier = "4" * 32
    remote.prepare(identifier)
    directory = remote.run_dir(identifier)
    maps_fixture(remote, directory / "upload")
    resources = remote.CACHE / "resources"
    resources.mkdir()
    (resources / "frame-controls.patch").write_bytes(b"controls")
    (resources / "build-native.sh").write_bytes(b"synthetic script")
    commands, stopped = [], []
    def command(argv, **kwargs):
        commands.append(argv)
        if argv[:2] == ["git", "init"]:
            Path(argv[2]).mkdir()
        return remote.SOURCE_COMMIT if "rev-parse" in argv else ""
    monkeypatch.setattr(remote, "command", command)
    def launch(argv, **kwargs):
        def poll():
            state["card"] = card_descriptor(remote.storage_module(), mount_id=202)
            remote._LAST_STORAGE_CHECK = 0
            return None
        return types.SimpleNamespace(returncode=None, poll=poll)
    monkeypatch.setattr(remote.subprocess, "Popen", launch)
    labels = {"org.halo-frame-installer.owner": remote.OWNER, "org.halo-frame-installer.run": identifier}
    monkeypatch.setattr(remote.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=json.dumps([{"Config": {"Labels": labels}}])))
    monkeypatch.setattr(remote, "stop_build_process", lambda process: stopped.append(process))
    with pytest.raises(ValueError, match="SD card changed"):
        remote.build(identifier)
    assert ["podman", "stop", "--time", "10", "halo-frame-installer-" + identifier] in commands
    assert len(stopped) == 1
    assert not (directory / "cancelled").exists()
    assert not remote.GAME.exists()


@pytest.mark.parametrize("wrong_label", ["owner", "run"])
def test_filesystem_independent_container_stop_rejects_foreign_labels(sd_remote, monkeypatch, wrong_label):
    remote, _ = sd_remote
    identifier = "5" * 32
    labels = {"org.halo-frame-installer.owner": remote.OWNER, "org.halo-frame-installer.run": identifier}
    labels["org.halo-frame-installer." + wrong_label] = "another application"
    monkeypatch.setattr(remote.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=json.dumps([{"Config": {"Labels": labels}}])))
    commands = []
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: commands.append(argv))
    with pytest.raises(ValueError, match="unowned container"):
        remote.stop_owned_container(identifier)
    assert not commands


@pytest.mark.parametrize("response", ["[]", "{}", '[{"Config": []}]', "[null]", "x" * (64 * 1024 + 1)],
                         ids=["empty", "object", "config", "null", "oversize"])
def test_container_cleanup_rejects_malformed_ownership_response(sd_remote, monkeypatch, response):
    remote, _ = sd_remote
    monkeypatch.setattr(remote.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=response))
    commands = []
    monkeypatch.setattr(remote, "command", lambda argv, **kwargs: commands.append(argv))
    with pytest.raises(ValueError):
        remote.stop_owned_container("7" * 32)
    assert not commands


def test_uninstall_removal_checks_live_mount_between_file_operations(sd_remote, monkeypatch):
    remote, state = sd_remote
    remote.owned(remote.GAME)
    (remote.GAME / "halo").write_bytes(b"program")
    inventory = remote.uninstall_inventory(remote.GAME)
    original = remote.assert_storage_active
    checks = 0
    def card_change(force=False):
        nonlocal checks
        checks += 1
        if checks == 3:
            state["card"] = card_descriptor(remote.storage_module(), mount_id=203)
            remote._LAST_STORAGE_CHECK = 0
        original(force=force)
    monkeypatch.setattr(remote, "assert_storage_active", card_change)
    completed = [0]
    with pytest.raises(ValueError, match="SD card changed"):
        remote.remove_uninstall_tree(remote.GAME, inventory, completed, 0)
    assert completed == [1]
    assert remote.GAME.exists() and (remote.GAME / remote.MARKER).exists()
    assert not (remote.GAME / "halo").exists()


def test_repair_does_not_restore_into_changed_sd_mount(sd_remote, monkeypatch):
    remote, state = sd_remote
    remote.owned(remote.GAME)
    (remote.GAME / "halo").write_bytes(b"old program")
    identifier = "6" * 32
    remote.prepare(identifier)
    directory = remote.run_dir(identifier)
    stage = directory / "stage"
    (stage / "halo").write_bytes(b"new program")
    checks = 0
    def check_cancelled():
        nonlocal checks
        checks += 1
        if checks == 3:
            state["card"] = card_descriptor(remote.storage_module(), mount_id=204)
        remote.assert_storage_active(force=True)
    replacements = []
    replace = remote.os.replace
    def record_replace(source, target):
        replacements.append((source, target))
        replace(source, target)
    monkeypatch.setattr(remote.os, "replace", record_replace)
    with pytest.raises(RuntimeError, match="Restoration was not attempted"):
        remote.repair_program_files(stage, directory, ["halo"], check_cancelled)
    assert len(replacements) == 1
    assert (directory / "previous-program-files/halo").read_bytes() == b"old program"


def test_uninstall_save_copy_checks_card_after_source_open_before_target_creation(sd_remote, monkeypatch):
    remote, state = sd_remote
    remote.owned(remote.GAME)
    source = remote.GAME / "save-v1.4/checkpoint"
    source.parent.mkdir()
    source.write_bytes(b"original campaign")
    signature = remote.uninstall_signature(source.stat())
    target = remote.GAME.parent / "backup/save-v1.4/checkpoint"
    original = remote.assert_storage_active
    checks = 0
    def card_change(force=False):
        nonlocal checks
        checks += 1
        if checks == 2:
            state["card"] = card_descriptor(remote.storage_module(), mount_id=205)
        original(force=force)
    monkeypatch.setattr(remote, "assert_storage_active", card_change)
    with pytest.raises(ValueError, match="SD card changed"):
        remote.copy_uninstall_save("save-v1.4/checkpoint", target, signature)
    assert source.read_bytes() == b"original campaign"
    assert not target.parent.exists()


@pytest.mark.parametrize("repair", [False, True])
def test_interrupted_sd_upgrade_recovery_survives_remount_and_repeated_retry(sd_remote, monkeypatch, repair):
    from test_install import built_run, interrupted_native_upgrade, interrupt_upgrade_retry
    remote, state = sd_remote
    internal = remote.HOME / "Games/HaloCENativeVR"
    internal.mkdir(parents=True)
    (internal / "keep").write_bytes(b"internal game and saves")
    manifest, previous, first = interrupted_native_upgrade(remote, save_path=remote.GAME / "profiles/custom")
    state["card"] = card_descriptor(remote.storage_module(), mount_id=301, device="179:33")
    remote.select_storage(state["card"]["id"])
    verified = remote.existing_install(repair=repair)
    assert verified["needsUpgrade"] and verified["previousSavePaths"] == [str(previous)]
    assert verified["upgradeRecovery"]["originPath"] == str(first / "previous-program-files")
    second = interrupt_upgrade_retry(remote, manifest)
    journal = remote.private_json(second / "previous-program-files/.upgrade-recovery.json", second)
    assert journal["storageOwnership"] == state["card"]["ownershipIdentity"]
    assert journal["storageIdentity"] == state["card"]["identity"]
    state["card"] = card_descriptor(remote.storage_module(), mount_id=302, device="179:65")
    remote.select_storage(state["card"]["id"])
    assert remote.existing_install(repair=repair)["previousSavePaths"] == [str(previous)]
    monkeypatch.setattr(remote, "command", lambda *args, **kwargs: "native libraries resolved")
    built_run(remote, manifest, "3" * 32)
    result = remote.finalize("3" * 32, repair=True)
    assert result["repaired"] and result["previousSavePaths"] == [str(previous)]
    assert (previous / "checkpoint").read_bytes() == b"incompatible previous checkpoint"
    assert (remote.save_root() / "checkpoint").read_bytes() == b"played after the interrupted upgrade"
    assert (internal / "keep").read_bytes() == b"internal game and saves"


@pytest.mark.parametrize("record", ["cache", "run", "backup", "stage", "carried"])
def test_sd_upgrade_recovery_refuses_other_card_provenance_without_writes(sd_remote, record):
    from test_install import interrupted_native_upgrade, interrupt_upgrade_retry
    remote, _ = sd_remote
    manifest, previous, first = interrupted_native_upgrade(remote, save_path=remote.GAME / "profiles/custom")
    directory = interrupt_upgrade_retry(remote, manifest) if record == "carried" else first
    path = {"cache": remote.CACHE / remote.MARKER, "run": directory / remote.MARKER,
            "backup": directory / "previous-program-files/.backup-owner.json",
            "stage": directory / "stage" / remote.MARKER,
            "carried": directory / "previous-program-files/.upgrade-recovery.json"}[record]
    metadata = remote.private_json(path, remote.CACHE)
    metadata["storageOwnership"]["cardIdentity"] = "f" * 64
    path.write_text(json.dumps(metadata))
    before = {item.relative_to(remote.GAME): item.read_bytes() for item in remote.GAME.rglob("*") if item.is_file()}
    for repair in (False, True):
        with pytest.raises(ValueError, match="interrupted upgrade could not be verified"):
            remote.existing_install(repair=repair)
    assert before == {item.relative_to(remote.GAME): item.read_bytes() for item in remote.GAME.rglob("*") if item.is_file()}
    assert (previous / "checkpoint").read_bytes() == b"incompatible previous checkpoint"


def test_interrupted_upgrade_accepts_internal_backup_with_new_storage_fields(sd_remote):
    from test_install import interrupted_native_upgrade
    remote, _ = sd_remote
    remote.select_storage("internal")
    remote.owned(remote.CACHE)
    (remote.CACHE / "runs").mkdir()
    _, previous, directory = interrupted_native_upgrade(remote)
    backup_owner = remote.private_json(directory / "previous-program-files/.backup-owner.json", directory)
    assert backup_owner["storageId"] == "internal"
    assert remote.existing_install()["previousSavePaths"] == [str(previous)]
