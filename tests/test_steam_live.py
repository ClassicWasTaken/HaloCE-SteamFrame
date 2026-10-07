"""Exercise the exact CDP expressions against a client API, without a headset."""
import importlib.util
import base64
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest


RESOURCE = Path(__file__).resolve().parents[1] / "resources/steam_live.py"


@pytest.fixture
def live(monkeypatch, tmp_path):
    storage_spec = importlib.util.spec_from_file_location("frame_storage", RESOURCE.parent / "frame_storage.py")
    storage = importlib.util.module_from_spec(storage_spec)
    monkeypatch.setitem(sys.modules, storage_spec.name, storage)
    storage_spec.loader.exec_module(storage)
    spec = importlib.util.spec_from_file_location("steam_live_test", RESOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    home = tmp_path / "home"
    game = home / "Games/HaloCENativeVR"
    game.mkdir(parents=True)
    monkeypatch.setattr(module, "HOME", home)
    monkeypatch.setattr(module, "GAME", game)
    return module


NODE_CLIENT = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const calls = [], store = new Map(), data = new Map();
const id = 3000000001;
for (const entry of input.entries || []) {
  store.set(entry.appid, {appid:entry.appid, app_type:1073741824, display_name:entry.name,
    icon_data:input.iconData === undefined ? (input.iconUnloaded ? undefined : '') : input.iconData});
  data.set(entry.appid, {unAppID:entry.appid, strShortcutExe:entry.exe,
    strShortcutStartDir:entry.directory || input.spec.directory,
    strLaunchOptions:entry.options || '', strShortcutLaunchOptions:entry.options || '',
    bShortcutIsVR:false, strCompatToolName:''});
}
let active = false;
async function setter(method, appid, value, field) {
  if (active) throw new Error('Concurrent client setters');
  active = true; calls.push([method, appid, value]);
  await new Promise(resolve => setTimeout(resolve, 1));
  if (field) data.get(appid)[field] = value;
  if (method === 'SetShortcutName') store.get(appid).display_name = value;
  active = false;
}
globalThis.appStore = {m_mapApps:store,GetAppOverviewByAppID:appid => store.get(appid)};
globalThis.SteamClient = {Apps:{
  AddShortcut:async(name, exe, arguments_, cmdline) => {
    calls.push(['AddShortcut',name,exe,arguments_,cmdline]);
    const result = input.returnId || id;
    store.set(result,{appid:result,app_type:1073741824,display_name:'halo',icon_data:''});
    data.set(result,{unAppID:result,strShortcutExe:exe,strShortcutStartDir:input.spec.directory+'/',
      strLaunchOptions:arguments_,strShortcutLaunchOptions:arguments_,bShortcutIsVR:false,strCompatToolName:''});
    return result;
  },
  RemoveShortcut:async appid => {calls.push(['RemoveShortcut',appid]);store.delete(appid);data.delete(appid);},
  RegisterForAppDetails:(appid, callback) => {
    calls.push(['RegisterForAppDetails',appid]);
    queueMicrotask(() => callback({...data.get(appid)}));
    return {unregister:() => calls.push(['unregister',appid])};
  },
  SetShortcutName:(appid,value) => setter('SetShortcutName',appid,value),
  SetShortcutExe:(appid,value) => setter('SetShortcutExe',appid,value,'strShortcutExe'),
  SetShortcutStartDir:(appid,value) => setter('SetShortcutStartDir',appid,value,'strShortcutStartDir'),
  SetShortcutLaunchOptions:(appid,value) => setter('SetShortcutLaunchOptions',appid,value,'strShortcutLaunchOptions'),
  SetAppLaunchOptions:(appid,value) => setter('SetAppLaunchOptions',appid,value,'strLaunchOptions'),
  SpecifyCompatTool:(appid,value) => setter('SpecifyCompatTool',appid,value,'strCompatToolName'),
  SetShortcutIsVR:(appid,value) => setter('SetShortcutIsVR',appid,value,'bShortcutIsVR'),
  SetShortcutIcon:(appid,value) => setter('SetShortcutIcon',appid,value),
  RequestIconDataForApp:appid => {
    calls.push(['RequestIconDataForApp',appid]);
    if (input.loadedIconData !== undefined) store.get(appid).icon_data = input.loadedIconData;
  },
  SetCustomArtworkForApp:async(appid,base64Data,extension,assetType) => {
    calls.push(['SetCustomArtworkForApp',appid,base64Data,extension,assetType]);
    await new Promise(resolve => setTimeout(resolve,1));
  },
}};
globalThis.loginStore = {currentUser:{accountName:'active-user'}};
for (const key of input.missing || []) delete SteamClient.Apps[key];
(async() => {
  try {
    const probe = await eval(input.probe);
    const secondProbe = await eval(input.probe);
    const result = probe.supported ? await eval(input.expression) : probe;
    await new Promise(resolve => setImmediate(resolve));
    process.stdout.write(JSON.stringify({probe,secondProbe,result,calls,entries:[...store.values()],data:[...data.values()]}));
  } catch(error) {
    process.stdout.write(JSON.stringify({error:String(error),calls,entries:[...store.values()]}));
  }
})();
"""


def run_client(live, operation="add", source=None, spec_values=None, game=None, **options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the actual Steam API expression")
    spec = live.native_spec(live.HOME, live.GAME if game is None else game)
    spec["operation"] = operation
    spec.update(spec_values or {})
    body = {"spec": spec, "probe": live.expression(live.PROBE, spec),
            "expression": live.expression(source or live.LIBRARY, spec), **options}
    result = subprocess.run([node, "-e", NODE_CLIENT], input=json.dumps(body),
                            text=True, encoding="utf-8", capture_output=True, timeout=12, check=True)
    return json.loads(result.stdout)


def entry(live, appid=3000000001, **values):
    return {"appid": appid, "name": live.NAME, "exe": str(live.GAME / "halo"), **values}


def test_add_awaits_every_setter_and_verifies_settings_in_fresh_eval_scope(live):
    result = run_client(live)
    assert result["probe"] == result["secondProbe"] == {"supported": True, "missing": []}
    assert result["result"]["status"] == "added"
    verified = result["result"]["verified"]
    assert verified["launchOptions"] == verified["shortcutLaunchOptions"] == live.LAUNCH_OPTIONS
    assert verified["vr"] is True and verified["compatibilityTool"] == ""
    methods = [call[0] for call in result["calls"] if call[0].startswith("Set") or call[0] == "SpecifyCompatTool"]
    assert methods == ["SetShortcutName", "SetShortcutExe", "SetShortcutStartDir",
                       "SetShortcutLaunchOptions", "SetAppLaunchOptions", "SpecifyCompatTool", "SetShortcutIsVR"]
    assert result["result"]["created"] is True
    assert sum(call[0] == "unregister" for call in result["calls"]) == 3
    add = next(call for call in result["calls"] if call[0] == "AddShortcut")
    assert add == ["AddShortcut", live.NAME, str(live.GAME / "halo"), "", '"' + str(live.GAME / "halo") + '"']


def test_existing_native_is_repaired_without_creating_duplicate(live):
    result = run_client(live, entries=[entry(live), entry(live, appid=3000000002, name="Other game", exe="/other")])
    assert result["result"]["created"] is False
    assert not any(call[0] == "AddShortcut" for call in result["calls"])
    assert len(result["entries"]) == 2
    assert result["data"][1]["strShortcutExe"] == "/other"


@pytest.mark.parametrize("entries_kind, expected", [("foreign", "different game"), ("duplicate", "Multiple exact"), ("collision", "different game")])
def test_ambiguous_and_foreign_identity_refuses_all_mutations(live, entries_kind, expected):
    entries = {
        "foreign": [entry(live, exe="/other/game")],
        "duplicate": [entry(live), entry(live, appid=3000000002)],
        "collision": [entry(live, appid=live.native_spec(live.HOME, live.GAME, live.NAME)["candidateAppids"][0], name="Other", exe="/other")],
    }[entries_kind]
    result = run_client(live, entries=entries)
    assert expected in result["error"]
    assert all(call[0] in ("RegisterForAppDetails", "unregister") for call in result["calls"])


def test_known_crc_native_entry_is_found_even_when_user_renamed_it(live):
    appid = live.native_spec(live.HOME, live.GAME, live.NAME)["candidateAppids"][0]
    result = run_client(live, entries=[entry(live, appid=appid, name="My Halo")])
    assert result["result"]["appid"] == appid and result["result"]["created"] is False
    assert result["entries"][0]["display_name"] == live.NAME


def test_any_renamed_native_entry_is_found_by_exact_executable(live):
    result = run_client(live, entries=[entry(live, name="halo")])
    assert result["result"]["appid"] == 3000000001 and result["result"]["created"] is False
    assert not any(call[0] == "AddShortcut" for call in result["calls"])


def test_remove_renamed_native_entry_uses_exact_path(live):
    result = run_client(live, "remove", entries=[entry(live, name="Custom Halo name")])
    assert result["result"]["status"] == "removed" and result["entries"] == []


def test_remove_exact_identity_and_leave_foreign_same_name_entry(live):
    result = run_client(live, "remove", entries=[entry(live), entry(live, appid=3000000002, exe="/foreign")])
    assert result["result"] == {"ok": True, "status": "removed", "appid": 3000000001}
    assert result["entries"] == [{"appid": 3000000002, "app_type": 1073741824, "display_name": live.NAME, "icon_data": ""}]
    assert [call for call in result["calls"] if call[0] == "RemoveShortcut"] == [["RemoveShortcut", 3000000001]]


def test_remove_absent_is_idempotent_and_does_not_mutate(live):
    result = run_client(live, "remove", entries=[entry(live, exe="/foreign")])
    assert result["result"] == {"ok": True, "status": "already-absent"}
    assert all(call[0] in ("RegisterForAppDetails", "unregister") for call in result["calls"])


def test_capability_probe_is_read_only(live):
    result = run_client(live, missing=["SpecifyCompatTool"])
    assert result["result"] == {"supported": False, "missing": ["SpecifyCompatTool"]}
    assert result["calls"] == [] and result["entries"] == []


def test_python_readback_rejects_missing_compatibility_field(live, monkeypatch):
    spec = live.native_spec(live.HOME, live.GAME, live.NAME)
    value = {"ok": True, "status": "added", "appid": 3000000001, "verified": {
        "appid": 3000000001, "exe": spec["exe"], "directory": spec["directory"],
        "launchOptions": live.LAUNCH_OPTIONS, "shortcutLaunchOptions": live.LAUNCH_OPTIONS, "vr": True}}
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.evaluate.side_effect = [{"supported": True}, value]
    monkeypatch.setattr(live, "Client", lambda: client)
    with pytest.raises(live.LiveSteamError, match="readback"):
        live.add_native(live.HOME, live.GAME)


def test_missing_live_capability_never_sends_the_mutating_expression(live, monkeypatch):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.evaluate.return_value = {"supported": False, "missing": ["AddShortcut"]}
    monkeypatch.setattr(live, "Client", lambda: client)
    with pytest.raises(live.LiveSteamError, match="unavailable"):
        live.add_native(live.HOME, live.GAME)
    assert client.evaluate.call_count == 1
    assert "supported" in client.evaluate.call_args.args[0]


@pytest.mark.parametrize("targets", [[], [{"title": "SharedJSContext"}],
                                     [{"title": "SharedJSContext", "webSocketDebuggerUrl": "ws://127.0.0.1:8080/devtools/page/1"}] * 2])
def test_target_selection_requires_exactly_one_verified_context(live, monkeypatch, targets):
    monkeypatch.setattr(live, "verify_endpoint_owner", lambda: None)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock()
    response.read.return_value = json.dumps(targets).encode()
    opener = Mock()
    opener.open.return_value = response
    builder = Mock(return_value=opener)
    monkeypatch.setattr(live.urllib.request, "build_opener", builder)
    connect = Mock(side_effect=AssertionError("Unexpected WebSocket connection"))
    monkeypatch.setattr(live, "WebSocket", connect)
    with pytest.raises(live.LiveSteamError, match="unavailable or ambiguous"):
        live.Client()
    connect.assert_not_called()
    assert builder.call_args.args[0].proxies == {}
    redirect = builder.call_args.args[1]
    assert redirect.redirect_request(None, None, 302, "redirect", {}, "https://example.org") is None


def test_target_list_size_is_checked_before_json_decoding(live, monkeypatch):
    monkeypatch.setattr(live, "verify_endpoint_owner", lambda: None)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock()
    response.read.return_value = b"x" * (live.MAX_BYTES + 1)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(live.urllib.request, "build_opener", lambda *args: opener)
    with pytest.raises(live.LiveSteamError, match="bounds"):
        live.Client()
    response.read.assert_called_once_with(live.MAX_BYTES + 1)


@pytest.mark.parametrize("owners, accepted", [([1000], True), ([1000, 1000], True),
                                              ([1001], False), ([1000, 1001], False), ([], False)])
def test_loopback_endpoint_requires_current_uid_owned_listeners(live, tmp_path, monkeypatch, owners, accepted):
    monkeypatch.setattr(live.os, "getuid", lambda: 1000, raising=False)
    header = "sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
    rows = [f"{index}: 0100007F:1F90 00000000:0000 0A 0:0 00:00000000 0 {uid} 0 123\n"
            for index, uid in enumerate(owners)]
    (tmp_path / "tcp").write_text(header + "".join(rows))
    if accepted:
        live.verify_endpoint_owner(tmp_path)
    else:
        with pytest.raises(live.LiveSteamError, match="does not belong"):
            live.verify_endpoint_owner(tmp_path)


def test_foreign_endpoint_never_contacts_http(live, monkeypatch):
    monkeypatch.setattr(live, "verify_endpoint_owner", Mock(side_effect=live.LiveSteamError("foreign account")))
    opener = Mock(side_effect=AssertionError("Foreign Steam must not receive a request"))
    monkeypatch.setattr(live.urllib.request, "build_opener", opener)
    with pytest.raises(live.LiveSteamError, match="foreign account"):
        live.Client()
    opener.assert_not_called()


@pytest.mark.parametrize("url", ["ws://example.org:8080/devtools/page/1", "wss://127.0.0.1:8080/devtools/page/1",
                                      "ws://127.0.0.1:80/devtools/page/1", "ws://user@127.0.0.1:8080/devtools/page/1",
                                      "ws://127.0.0.1:8080/other", "ws://127.0.0.1:8080/devtools/page/1\n"])
def test_transport_refuses_nonverified_endpoints_before_connecting(live, monkeypatch, url):
    connect = Mock(side_effect=AssertionError("Unexpected network connection"))
    monkeypatch.setattr(live.socket, "create_connection", connect)
    with pytest.raises(live.LiveSteamError):
        live.WebSocket(url, time.monotonic() + 30)
    connect.assert_not_called()


def test_websocket_fragmented_text_and_ping_are_bounded(live):
    ws = live.WebSocket.__new__(live.WebSocket)
    ws.deadline = time.monotonic() + 30
    ws.sock = Mock()
    ws.pending = bytearray(b'\x01\x02{"\x89\x01P\x80\x05x":1}')
    sent = []
    ws.send = lambda payload, opcode=1: sent.append((payload, opcode))
    assert ws.receive_text() == '{"x":1}'
    assert sent == [(b"P", 10)]
    ws.pending = bytearray(b"\x81\x7f" + struct.pack("!Q", live.MAX_BYTES + 1))
    with pytest.raises(live.LiveSteamError, match="bounds"):
        ws.receive_text()


def test_native_spec_rejects_unmanaged_paths(live):
    with pytest.raises(live.LiveSteamError, match="restricted"):
        live.native_spec(live.HOME, live.GAME / "../foreign", live.NAME)


@pytest.fixture
def sd_game(live, tmp_path, monkeypatch):
    storage = sys.modules["frame_storage"]
    internal = storage.discover_storage(live.HOME)["destinations"][0]
    mount = tmp_path / "media" / "Halo SD Ω"
    game = mount / "Games/HaloCENativeVR"
    game.mkdir(parents=True)
    descriptor = {"id": "sd:" + "a" * 32, "kind": "sd", "label": "Halo SD Ω",
                  "mountPath": str(mount), "gamePath": str(game),
                  "cachePath": str(mount / ".cache/halo-frame-installer"),
                  "freeBytes": 32 * 1024 ** 3, "installed": False}
    monkeypatch.setattr(storage, "discover_storage", lambda home=live.HOME: {
        "home": str(home), "destinations": [internal, descriptor]})
    return game


def test_native_spec_accepts_only_discovered_sd_fixed_game_path(live, sd_game):
    spec = live.native_spec(live.HOME, sd_game)
    assert spec["exe"] == str(sd_game / "halo") and spec["directory"] == str(sd_game)
    assert spec["name"] == live.SD_NAME
    assert spec["candidateAppids"] != live.native_spec(live.HOME, live.GAME, live.NAME)["candidateAppids"]
    for foreign in (sd_game.parent / "Foreign", sd_game.parent.parent / "halo", sd_game / "../foreign"):
        with pytest.raises(live.LiveSteamError, match="restricted"):
            live.native_spec(live.HOME, foreign)


@pytest.mark.parametrize("field", ["home", "name", "launch_options"])
def test_sd_spec_retains_fixed_home_title_and_launch_options(live, sd_game, field):
    arguments = {"home": live.HOME, "game": sd_game, "name": live.SD_NAME,
                 "launch_options": live.LAUNCH_OPTIONS}
    arguments[field] = live.HOME.parent if field == "home" else "foreign"
    with pytest.raises(live.LiveSteamError, match="restricted"):
        live.native_spec(**arguments)
    with pytest.raises(live.LiveSteamError, match="restricted"):
        live.native_spec(live.HOME, sd_game, live.NAME)


def test_sd_registration_uses_exact_quoted_executable_and_working_directory(live, sd_game):
    result = run_client(live, game=sd_game)
    assert result["result"]["verified"]["exe"] == str(sd_game / "halo")
    assert result["result"]["verified"]["directory"] == str(sd_game)
    add = next(call for call in result["calls"] if call[0] == "AddShortcut")
    assert add == ["AddShortcut", live.SD_NAME, str(sd_game / "halo"), "", '"' + str(sd_game / "halo") + '"']
    assert [call for call in result["calls"] if call[0] == "SetShortcutStartDir"] == [
        ["SetShortcutStartDir", result["result"]["appid"], str(sd_game)]]
    assert result["result"]["verified"]["vr"] is True
    assert result["result"]["verified"]["compatibilityTool"] == ""


def test_sd_registration_coexists_with_existing_internal_entry(live, sd_game):
    result = run_client(live, game=sd_game, entries=[entry(live)], returnId=3000000002)
    assert result["result"]["created"] is True
    assert result["entries"][0]["display_name"] == live.NAME
    assert result["entries"][1]["display_name"] == live.SD_NAME
    assert result["data"][0]["strShortcutExe"] == str(live.GAME / "halo")
    assert not any(call[0].startswith("Set") and call[1] == 3000000001 for call in result["calls"])


def test_sd_registration_refuses_foreign_entry_with_sd_title(live, sd_game):
    result = run_client(live, game=sd_game, entries=[entry(live, name=live.SD_NAME, exe="/foreign/game")])
    assert "different game" in result["error"]
    assert all(call[0] in ("RegisterForAppDetails", "unregister") for call in result["calls"])


def test_sd_repair_keeps_existing_sd_appid_and_internal_shortcut(live, sd_game):
    result = run_client(live, game=sd_game, entries=[entry(live),
        entry(live, appid=3000000002, name="My SD Halo", exe=str(sd_game / "halo"))])
    assert result["result"]["appid"] == 3000000002 and not result["result"]["created"]
    assert not any(call[0] == "AddShortcut" for call in result["calls"])
    assert result["entries"][0]["display_name"] == live.NAME
    assert result["entries"][1]["display_name"] == live.SD_NAME


def test_sd_remove_keeps_internal_copy_and_only_removes_exact_selected_executable(live, sd_game):
    result = run_client(live, "remove", game=sd_game, entries=[
        entry(live), entry(live, appid=3000000002, name="My SD Halo", exe=str(sd_game / "halo"))])
    assert result["result"] == {"ok": True, "status": "removed", "appid": 3000000002}
    assert [item["appid"] for item in result["entries"]] == [3000000001]
    assert [call for call in result["calls"] if call[0] == "RemoveShortcut"] == [["RemoveShortcut", 3000000002]]


def test_missing_sd_is_rejected_before_any_live_client_access(live, sd_game, monkeypatch):
    monkeypatch.setattr(sys.modules["frame_storage"], "discover_storage", lambda home=live.HOME: {
        "home": str(home), "destinations": []})
    monkeypatch.setattr(live, "Client", lambda: pytest.fail("Missing SD must not open Steam's client"))
    with pytest.raises(live.LiveSteamError, match="restricted"):
        live.add_native(live.HOME, sd_game)


@pytest.fixture
def artwork_client(live, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("steam_shortcut", RESOURCE.parent / "steam_shortcut.py")
    shortcut = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "steam_shortcut", shortcut)
    spec.loader.exec_module(shortcut)
    home = tmp_path / "home"
    monkeypatch.setattr(live, "HOME", home)
    monkeypatch.setattr(live, "GAME", home / "Games/HaloCENativeVR")
    steam = home / ".local/share/Steam"
    config = steam / "config"
    config.mkdir(parents=True)
    grid = steam / "userdata/10/config/grid"
    grid.mkdir(parents=True)
    foreign = steam / "userdata/20/config/grid"
    foreign.mkdir(parents=True)
    (foreign / "unrelated.png").write_bytes(b"another account's custom art")
    login = config / "loginusers.vdf"
    login.write_text('"users" { "76561197960265738" { "AccountName" "active-user" "MostRecent" "0" } '
                     '"76561197960265748" { "AccountName" "another-user" "MostRecent" "1" } }')
    game = live.GAME
    game.mkdir(parents=True, exist_ok=True)
    program = bytearray(64)
    program[:6] = b"\x7fELF\x02\x01"
    program[18:20] = (183).to_bytes(2, "little")
    (game / "halo").write_bytes(program)
    (game / ".halo-frame-installer.json").write_text(json.dumps({
        "owner": "halo-frame-installer", "sourceCommit": shortcut.ICON_SOURCE_COMMIT,
        "files": {"halo": hashlib.sha256(program).hexdigest()}}))
    record, _ = shortcut.update_shortcut(None, str(game / "halo"), str(game))
    root = shortcut.loads(record)
    root["shortcuts"].value["0"].value["appid"].value = 3000000001
    persisted = grid.parent / "shortcuts.vdf"
    persisted.write_bytes(shortcut.dumps(root))

    class ArtworkClient:
        deadline = time.monotonic() + 30
        account = "active-user"
        writes = []
        icon_writes = []
        calls = 0
        fail_write = False
        switch_before_write = False
        corrupt_write = False
        switch_after_write = False
        icon_state = "empty"
        load_icon = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def evaluate(self, expression):
            self.calls += 1
            encoded = expression.removeprefix("(() => {const S = ").split(";\nreturn ", 1)[0]
            request = json.loads(encoded)
            if "iconPath" in request:
                self.icon_writes.append(request)
                if self.fail_write:
                    raise live.LiveSteamError("Steam shortcut icon API did not finish")
                record = shortcut.loads(persisted.read_bytes())
                matching = [item.value for item in record["shortcuts"].value.values()
                            if item.value["appid"].value == request["appid"]]
                assert len(matching) == 1
                matching[0]["icon"].value = "/custom/concurrent.png" if self.corrupt_write else request["iconPath"]
                persisted.write_bytes(shortcut.dumps(record))  # Simulate Steam's own path setter.
                if self.switch_after_write:
                    self.account = "another-user"
                return {"ok": True, "accountName": self.account, "appid": request["appid"]}
            if "base64Data" in request:
                self.writes.append(request)
                if self.fail_write:
                    raise live.LiveSteamError("Steam artwork API did not finish")
                payload = b"unexpected client image" if self.corrupt_write else base64.b64decode(request["base64Data"])
                suffix = {0: "p", 1: "_hero", 2: "_logo", 3: ""}[request["assetType"]]
                target = grid / (str(request["appid"]) + suffix + "." + request["extension"])
                target.write_bytes(payload)  # Simulate only Steam's own API filesystem write.
                if self.switch_after_write:
                    self.account = "another-user"
                return {"ok": True, "accountName": self.account, "appid": request["appid"]}
            if self.switch_before_write and self.calls >= 2:
                self.account = "another-user"
            state = self.icon_state
            requested = state == "unknown" and request.get("requestIcon") is True and self.load_icon
            if requested:
                self.icon_state = "empty"
            return {"accountName": self.account, "appid": request["appid"], "exe": request["exe"],
                    "iconState": state, "iconRequested": requested}

    client = ArtworkClient()
    monkeypatch.setattr(live, "Client", lambda: client)
    return home, live.GAME, grid, foreign, login, client, shortcut


def test_live_artwork_uses_api_types_and_active_account_not_most_recent(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    result = live._live_artwork(home, game, 3000000001)
    assert result["status"] == "added"
    assert result["installed"] == ["3000000001" + suffix + extension for suffix, extension, _, _ in shortcut.ARTWORK]
    assert [(item["extension"], item["assetType"]) for item in client.writes] == [
        (extension.lstrip("."), shortcut.ARTWORK_TYPES[suffix]) for suffix, extension, _, _ in shortcut.ARTWORK]
    for suffix, extension, filename, expected in shortcut.ARTWORK:
        assert hashlib.sha256((grid / ("3000000001" + suffix + extension)).read_bytes()).hexdigest() == expected
    assert list(foreign.iterdir()) == [foreign / "unrelated.png"]
    assert login.read_text().count('"MostRecent" "1"') == 1


def test_sd_live_artwork_uses_home_account_grid_and_sd_icon_sidecar(live, artwork_client, sd_game):
    home, internal_game, grid, foreign, login, client, shortcut = artwork_client
    assert shortcut.SD_NAME == live.SD_NAME
    for filename in ("halo", ".halo-frame-installer.json"):
        (sd_game / filename).write_bytes((internal_game / filename).read_bytes())
    persisted = grid.parent / "shortcuts.vdf"
    before = persisted.read_bytes()
    updated, appid = shortcut.update_shortcut(before, str(sd_game / "halo"), str(sd_game), live.SD_NAME)
    persisted.write_bytes(updated)
    result = live._live_artwork(home, sd_game, appid)
    icon = live._live_icon(home, sd_game, appid)
    assert result["status"] == icon["status"] == "added"
    assert icon["path"] == str(sd_game / ".installer-artwork" / shortcut.ICON_NAME)
    assert all(item["name"] == live.SD_NAME and item["exe"] == str(sd_game / "halo") for item in client.writes)
    assert all((grid / (str(appid) + suffix + extension)).is_file()
               for suffix, extension, _, _ in shortcut.ARTWORK)
    assert shortcut.loads(persisted.read_bytes())["shortcuts"].value["0"] == shortcut.loads(before)["shortcuts"].value["0"]
    assert list(foreign.iterdir()) == [foreign / "unrelated.png"]
    assert not (sd_game / ".local").exists() and not (sd_game.parent.parent / ".local").exists()


def test_live_artwork_preserves_custom_extensions_and_reuses_managed_hash(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    (grid / "3000000001p.webp").write_bytes(b"custom portrait")
    (grid / "3000000001.png").write_bytes((RESOURCE.parent / "artwork/halo-ce-landscape.png").read_bytes())
    for suffix, extension, filename, _ in shortcut.ARTWORK:
        if suffix not in ("p", ""):
            (grid / ("3000000001" + suffix + extension)).write_bytes((RESOURCE.parent / "artwork" / filename).read_bytes())
    before = {path.name: path.read_bytes() for path in grid.iterdir()}
    result = live._live_artwork(home, game, 3000000001)
    unchanged = ["3000000001" + suffix + extension for suffix, extension, _, _ in shortcut.ARTWORK if suffix != "p"]
    assert result == {"status": "preserved", "installed": [], "preserved": ["3000000001p.webp"], "unchanged": unchanged}
    assert not client.writes
    assert {path.name: path.read_bytes() for path in grid.iterdir()} == before


@pytest.mark.parametrize("profile", ["missing", "ambiguous", "duplicate-field"])
def test_artwork_unmatched_or_ambiguous_account_never_writes(live, artwork_client, profile):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    replacements = {
        "missing": '"users" {"76561197960265738" {"AccountName" "different-user"}}',
        "ambiguous": '"users" {"76561197960265738" {"AccountName" "active-user"} '
                     '"76561197960265748" {"AccountName" "active-user"}}',
        "duplicate-field": '"users" {"76561197960265738" {"AccountName" "different" "AccountName" "active-user"}}',
    }
    login.write_text(replacements[profile])
    with pytest.raises((live.LiveSteamError, ValueError)):
        live._live_artwork(home, game, 3000000001)
    assert not client.writes and not list(grid.iterdir())


def test_live_artwork_account_change_before_write_preserves_both_accounts(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.switch_before_write = True
    with pytest.raises(live.LiveSteamError, match="changed"):
        live._live_artwork(home, game, 3000000001)
    assert not client.writes and not list(grid.iterdir())
    assert (foreign / "unrelated.png").read_bytes() == b"another account's custom art"


def test_live_artwork_source_integrity_is_checked_before_any_client_request(live, artwork_client, tmp_path):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    sources = tmp_path / "corrupt-art"
    sources.mkdir()
    for _, _, name, _ in shortcut.ARTWORK:
        (sources / name).write_bytes(b"bad source")
    with pytest.raises(live.LiveSteamError, match="integrity"):
        live._live_artwork(home, game, 3000000001, sources)
    assert client.calls == 0 and not client.writes and not list(grid.iterdir())


def test_artwork_failure_keeps_verified_library_result_and_reports_manual(live, artwork_client, monkeypatch):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    monkeypatch.setattr(live, "_library", lambda *args: {"appid": 3000000001, "created": False, "name": live.NAME})
    client.fail_write = True
    result = live.add_native(home, game)
    assert result["status"] == "added" and result["libraryAdded"] is True
    assert result["artwork"]["status"] == "manual"
    assert "Steam artwork API" in result["artwork"]["reason"]
    assert not list(grid.iterdir())


def test_wrong_artwork_readback_is_not_reported_complete_or_deleted(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.corrupt_write = True
    with pytest.raises(live.LiveSteamError, match="integrity"):
        live._live_artwork(home, game, 3000000001)
    assert (grid / "3000000001p.jpg").read_bytes() == b"unexpected client image"
    assert not (grid / "3000000001.png").exists()


def test_artwork_account_change_after_api_is_not_reported_complete(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.switch_after_write = True
    with pytest.raises(live.LiveSteamError, match="could not be verified"):
        live._live_artwork(home, game, 3000000001)
    assert len(client.writes) == 1
    assert (foreign / "unrelated.png").read_bytes() == b"another account's custom art"


def test_actual_artwork_expression_awaits_api_with_confirmed_argument_order(live):
    values = {"appid": 3000000001, "accountName": "active-user", "base64Data": "aW1hZ2U=",
              "extension": "jpg", "assetType": 0}
    result = run_client(live, source=live.ART_WRITE, spec_values=values, entries=[entry(live)])
    assert result["result"] == {"ok": True, "accountName": "active-user", "appid": 3000000001}
    assert [call for call in result["calls"] if call[0] == "SetCustomArtworkForApp"] == [
        ["SetCustomArtworkForApp", 3000000001, "aW1hZ2U=", "jpg", 0]]
    assert sum(call[0] == "unregister" for call in result["calls"]) == 2


def test_actual_artwork_expression_rechecks_account_before_mutation(live):
    values = {"appid": 3000000001, "accountName": "another-user", "base64Data": "aW1hZ2U=",
              "extension": "png", "assetType": 3}
    result = run_client(live, source=live.ART_WRITE, spec_values=values, entries=[entry(live)])
    assert "account changed" in result["error"]
    assert not any(call[0] == "SetCustomArtworkForApp" for call in result["calls"])


def test_live_icon_persists_validated_game_sidecar_and_uses_path_api(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    foreign_before = {path.name: path.read_bytes() for path in foreign.iterdir()}
    result = live._live_icon(home, game, 3000000001)
    target = game / ".installer-artwork" / shortcut.ICON_NAME
    assert result == {"status": "added", "path": str(target)}
    assert hashlib.sha256(target.read_bytes()).hexdigest() == shortcut.ICON_SHA256
    assert len(client.icon_writes) == 1 and not client.writes
    assert client.icon_writes[0]["iconPath"] == str(target)
    persisted = (grid.parent / "shortcuts.vdf").read_bytes()
    _, _, selected = shortcut._shortcut_icon_field(persisted, 3000000001, str(game / "halo"))
    assert selected == str(target)
    assert {path.name: path.read_bytes() for path in foreign.iterdir()} == foreign_before
    again = live._live_icon(home, game, 3000000001)
    assert again["status"] == "unchanged" and len(client.icon_writes) == 1


def test_live_icon_preserves_existing_selection_without_publishing_sidecar(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    persisted = grid.parent / "shortcuts.vdf"
    root = shortcut.loads(persisted.read_bytes())
    root["shortcuts"].value["0"].value["icon"].value = "/my/custom/icon.png"
    before = shortcut.dumps(root)
    persisted.write_bytes(before)
    result = live._live_icon(home, game, 3000000001)
    assert result["status"] == "preserved"
    assert persisted.read_bytes() == before and not client.icon_writes
    assert not (game / ".installer-artwork").exists()


def test_live_icon_account_change_before_api_never_changes_selection(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    before = (grid.parent / "shortcuts.vdf").read_bytes()
    client.switch_before_write = True
    with pytest.raises(live.LiveSteamError, match="account changed"):
        live._live_icon(home, game, 3000000001)
    assert not client.icon_writes and (grid.parent / "shortcuts.vdf").read_bytes() == before


def test_live_icon_corrupt_source_is_rejected_before_client_requests(live, artwork_client, tmp_path):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    source = tmp_path / "corrupt-icon"
    source.mkdir()
    (source / shortcut.ICON_NAME).write_bytes(b"bad bundled icon")
    with pytest.raises(live.LiveSteamError, match="integrity"):
        live._live_icon(home, game, 3000000001, source)
    assert not client.calls and not client.icon_writes and not (game / ".installer-artwork").exists()


def test_live_icon_foreign_persisted_executable_is_never_changed(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    persisted = grid.parent / "shortcuts.vdf"
    root = shortcut.loads(persisted.read_bytes())
    root["shortcuts"].value["0"].value["Exe"].value = '"/other/game"'
    before = shortcut.dumps(root)
    persisted.write_bytes(before)
    with pytest.raises(ValueError, match="identity"):
        live._live_icon(home, game, 3000000001)
    assert persisted.read_bytes() == before and not client.icon_writes
    assert not (game / ".installer-artwork").exists()


def test_live_icon_unverified_client_selection_is_kept_and_reported_manual(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.corrupt_write = True
    with pytest.raises(live.LiveSteamError, match="persisted"):
        live._live_icon(home, game, 3000000001)
    _, _, selected = shortcut._shortcut_icon_field((grid.parent / "shortcuts.vdf").read_bytes(), 3000000001, str(game / "halo"))
    assert selected == "/custom/concurrent.png"


def test_unpersisted_icon_record_does_not_block_library_or_banner_completion(live, artwork_client, monkeypatch):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    (grid.parent / "shortcuts.vdf").unlink()
    monkeypatch.setattr(live, "_library", lambda *args: {"appid": 3000000001, "created": False, "name": live.NAME})
    result = live.add_native(home, game)
    assert result["status"] == "added" and result["libraryAdded"] is True
    assert result["artwork"]["status"] == "added"
    assert result["artwork"]["icon"]["status"] == "manual"
    assert not client.icon_writes


def test_actual_icon_expression_uses_confirmed_path_setter_without_art_type_four(live):
    values = {"appid": 3000000001, "accountName": "active-user", "iconPath": str(live.GAME / ".installer-artwork/halo-ce-icon.png")}
    result = run_client(live, source=live.ICON_WRITE, spec_values=values, entries=[entry(live)])
    assert result["result"] == {"ok": True, "accountName": "active-user", "appid": 3000000001}
    assert [call for call in result["calls"] if call[0] == "SetShortcutIcon"] == [
        ["SetShortcutIcon", 3000000001, values["iconPath"]]]
    assert not any(call[0] == "SetCustomArtworkForApp" for call in result["calls"])


def test_actual_icon_expression_requires_capability_and_checks_account(live):
    values = {"appid": 3000000001, "accountName": "another-user", "iconPath": "/owned/icon.png"}
    result = run_client(live, source=live.ICON_WRITE, spec_values=values, entries=[entry(live)])
    assert "account changed" in result["error"]
    assert not any(call[0] == "SetShortcutIcon" for call in result["calls"])
    result = run_client(live, source=live.ICON_WRITE, spec_values=values, entries=[entry(live)], missing=["SetShortcutIcon"])
    assert "unavailable" in result["error"]
    assert not any(call[0] == "SetShortcutIcon" for call in result["calls"])


@pytest.mark.parametrize("icon_data", [None, "resident-custom-icon"])
def test_actual_icon_expression_keeps_unloaded_or_resident_custom_icon(live, icon_data):
    values = {"appid": 3000000001, "accountName": "active-user", "iconPath": "/owned/icon.png"}
    result = run_client(live, source=live.ICON_WRITE, spec_values=values, entries=[entry(live)], iconData=icon_data)
    assert "confirmed empty" in result["error"]
    assert not any(call[0] == "SetShortcutIcon" for call in result["calls"])


def test_live_icon_resident_custom_icon_wins_over_stale_empty_vdf(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.icon_state = "present"
    before = (grid.parent / "shortcuts.vdf").read_bytes()
    result = live._live_icon(home, game, 3000000001)
    assert result["status"] == "preserved"
    assert not client.icon_writes and (grid.parent / "shortcuts.vdf").read_bytes() == before
    assert not (game / ".installer-artwork").exists()


def test_live_icon_unknown_resident_state_defers_without_sidecar_or_setter(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.icon_state = "unknown"
    with pytest.raises(live.LiveSteamError, match="has not loaded"):
        live._live_icon(home, game, 3000000001)
    assert not client.icon_writes and not (game / ".installer-artwork").exists()


def test_live_icon_requests_missing_data_once_and_waits_for_confirmed_empty(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    client.icon_state = "unknown"
    client.load_icon = True
    result = live._live_icon(home, game, 3000000001)
    assert result["status"] == "added" and len(client.icon_writes) == 1


def test_actual_icon_session_requests_undefined_data_without_assuming_empty(live):
    values = {"appid": 3000000001, "accountName": "active-user", "requestIcon": True}
    result = run_client(live, source=live.ICON_SESSION, spec_values=values, entries=[entry(live)], iconUnloaded=True, loadedIconData="")
    assert result["result"]["iconState"] == "unknown" and result["result"]["iconRequested"] is True
    assert [call for call in result["calls"] if call[0] == "RequestIconDataForApp"] == [["RequestIconDataForApp", 3000000001]]
    assert not any(call[0] == "SetShortcutIcon" for call in result["calls"])


def test_corrupt_icon_prevents_all_live_artwork_calls(live, artwork_client, tmp_path):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    source = tmp_path / "corrupt-icon-with-valid-art"
    source.mkdir()
    for _, _, filename, _ in shortcut.ARTWORK:
        (source / filename).write_bytes((RESOURCE.parent / "artwork" / filename).read_bytes())
    (source / shortcut.ICON_NAME).write_bytes(b"corrupt final icon")
    with pytest.raises(live.LiveSteamError, match="icon.*integrity"):
        live._live_artwork(home, game, 3000000001, source)
    assert not client.calls and not client.writes and not list(grid.iterdir())
