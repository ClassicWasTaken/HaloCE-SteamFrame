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
def live(monkeypatch):
    spec = importlib.util.spec_from_file_location("steam_live_test", RESOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


NODE_CLIENT = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const calls = [], store = new Map(), data = new Map();
const id = 3000000001;
for (const entry of input.entries || []) {
  store.set(entry.appid, {appid:entry.appid, app_type:1073741824, display_name:entry.name});
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
globalThis.appStore = {m_mapApps:store};
globalThis.SteamClient = {Apps:{
  AddShortcut:async(name, exe, arguments_, cmdline) => {
    calls.push(['AddShortcut',name,exe,arguments_,cmdline]);
    const result = input.returnId || id;
    store.set(result,{appid:result,app_type:1073741824,display_name:'halo'});
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


def run_client(live, operation="add", source=None, spec_values=None, **options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the actual Steam API expression")
    spec = live.native_spec(live.HOME, live.GAME, live.NAME)
    spec["operation"] = operation
    spec.update(spec_values or {})
    body = {"spec": spec, "probe": live.expression(live.PROBE, spec),
            "expression": live.expression(source or live.LIBRARY, spec), **options}
    result = subprocess.run([node, "-e", NODE_CLIENT], input=json.dumps(body),
                            text=True, capture_output=True, timeout=12, check=True)
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
    assert result["entries"] == [{"appid": 3000000002, "app_type": 1073741824, "display_name": live.NAME}]
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

    class ArtworkClient:
        deadline = time.monotonic() + 30
        account = "active-user"
        writes = []
        calls = 0
        fail_write = False
        switch_before_write = False
        corrupt_write = False
        switch_after_write = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def evaluate(self, expression):
            self.calls += 1
            encoded = expression.removeprefix("(() => {const S = ").split(";\nreturn ", 1)[0]
            request = json.loads(encoded)
            if "base64Data" in request:
                self.writes.append(request)
                if self.fail_write:
                    raise live.LiveSteamError("Steam artwork API did not finish")
                payload = b"unexpected client image" if self.corrupt_write else base64.b64decode(request["base64Data"])
                suffix = "p" if request["assetType"] == 0 else ""
                target = grid / (str(request["appid"]) + suffix + "." + request["extension"])
                target.write_bytes(payload)  # Simulate only Steam's own API filesystem write.
                if self.switch_after_write:
                    self.account = "another-user"
                return {"ok": True, "accountName": self.account, "appid": request["appid"]}
            if self.switch_before_write and self.calls >= 2:
                self.account = "another-user"
            return {"accountName": self.account, "appid": request["appid"], "exe": request["exe"]}

    client = ArtworkClient()
    monkeypatch.setattr(live, "Client", lambda: client)
    return home, live.GAME, grid, foreign, login, client, shortcut


def test_live_artwork_uses_api_types_and_active_account_not_most_recent(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    result = live._live_artwork(home, game, 3000000001)
    assert result["status"] == "added"
    assert result["installed"] == ["3000000001p.jpg", "3000000001.png"]
    assert [(item["extension"], item["assetType"]) for item in client.writes] == [("jpg", 0), ("png", 3)]
    for suffix, extension, filename, expected in shortcut.ARTWORK:
        assert hashlib.sha256((grid / ("3000000001" + suffix + extension)).read_bytes()).hexdigest() == expected
    assert list(foreign.iterdir()) == [foreign / "unrelated.png"]
    assert login.read_text().count('"MostRecent" "1"') == 1


def test_live_artwork_preserves_custom_extensions_and_reuses_managed_hash(live, artwork_client):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    (grid / "3000000001p.webp").write_bytes(b"custom portrait")
    (grid / "3000000001.png").write_bytes((RESOURCE.parent / "artwork/halo-ce-landscape.png").read_bytes())
    before = {path.name: path.read_bytes() for path in grid.iterdir()}
    result = live._live_artwork(home, game, 3000000001)
    assert result == {"status": "preserved", "installed": [], "preserved": ["3000000001p.webp"], "unchanged": ["3000000001.png"]}
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
    for name in ("halo-ce-cover.jpg", "halo-ce-landscape.png"):
        (sources / name).write_bytes(b"bad source")
    with pytest.raises(live.LiveSteamError, match="integrity"):
        live._live_artwork(home, game, 3000000001, sources)
    assert client.calls == 0 and not client.writes and not list(grid.iterdir())


def test_artwork_failure_keeps_verified_library_result_and_reports_manual(live, artwork_client, monkeypatch):
    home, game, grid, foreign, login, client, shortcut = artwork_client
    monkeypatch.setattr(live, "_library", lambda *args: {"appid": 3000000001, "created": False})
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
