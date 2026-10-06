"""Exercise the actual Notes JavaScript against a bounded native API contract."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


@pytest.fixture
def notes(monkeypatch):
    for name in ("steam_live", "steam_notes"):
        spec = importlib.util.spec_from_file_location(name, RESOURCES / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return sys.modules["steam_notes"]


NODE_CLIENT = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const calls=[];
const spec=input.spec;
const store=new Map([[spec.appid,{appid:spec.appid,app_type:1073741824,display_name:spec.name}]]);
if (input.foreignName) store.set(spec.appid+1,{appid:spec.appid+1,app_type:1073741824,display_name:spec.name});
globalThis.appStore={m_mapApps:store};
globalThis.loginStore={currentUser:{accountName:'current-account'}};
let doc=input.document ?? null,reads=0;
function call(method,...args) {
  calls.push([method,...args]);
  if (input.changeAccountAt===method) loginStore.currentUser.accountName='other-account';
}
globalThis.SteamClient={Apps:{RegisterForAppDetails:(id,callback)=>{
  call('RegisterForAppDetails',id);
  callback({unAppID:input.wrongId?id+1:id,strShortcutExe:input.foreignExe?'/foreign/game':spec.exe});
  return {unregister:()=>call('unregister')};
}},GameNotes:{
  SyncToClient:async()=>{call('SyncToClient');return input.syncClientResult ?? 1;},
  SyncToServer:async()=>{call('SyncToServer');return input.syncServerResult ?? 1;},
  GetNotes:async(filename,images)=>{
    call('GetNotes',filename,images);reads++;
    if (input.changeDocumentAtRead===reads) doc=input.changedDocument;
    if (input.invalidJSON) return {result:1,notes:'{bad json'};
    return doc===null?{result:input.missingResult ?? 9,notes:''}:
      {result:input.readResult ?? 1,notes:JSON.stringify(doc),images:[]};
  },
  SaveNotes:async(filename,text)=>{
    call('SaveNotes',filename);
    if ((input.saveResult ?? 1)===1) doc=JSON.parse(text);
    return input.saveResult ?? 1;
  }
}};
if (input.missingMethod) delete SteamClient.GameNotes[input.missingMethod];
(async()=>{
  try {
    const result=await eval(input.expression);
    process.stdout.write(JSON.stringify({result,calls,document:doc}));
  } catch(error) {process.stdout.write(JSON.stringify({error:String(error),calls,document:doc}));}
})();
"""


def run_notes(notes, **options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the real Steam Notes expression")
    spec = notes.native_spec(notes.HOME, notes.GAME, notes.NAME)
    spec.update({"appid": 3000000001, "noteId": notes.NOTE_ID,
                 "title": notes.NOTE_TITLE, "content": notes.NOTE_CONTENT,
                 "maxBytes": notes.MAX_DOCUMENT_BYTES, "maxNotes": notes.MAX_NOTES,
                 "previousContents": list(notes.PREVIOUS_NOTE_CONTENTS)})
    spec.update(options.pop("spec_overrides", {}))
    body = {"spec": spec, "expression": notes.expression(notes.NOTES, spec), **options}
    output = subprocess.run([node, "-e", NODE_CLIENT], input=json.dumps(body),
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=12)
    return json.loads(output.stdout)


def document(notes, existing=None, **fields):
    return {"notes": existing or [], "shortcut_name": notes.NAME, **fields}


def managed(notes, **fields):
    return {"id": notes.NOTE_ID, "shortcut_name": notes.NAME, "title": notes.NOTE_TITLE,
            "content": notes.NOTE_CONTENT, "ordinal": 0, "time_created": 1,
            "time_modified": 2, **fields}


def methods(result):
    return [call[0] for call in result["calls"]]


def test_missing_file_adds_verified_shortcut_note_with_native_filename(notes):
    result = run_notes(notes)
    assert result["result"]["status"] == "added"
    assert methods(result).count("SaveNotes") == 1
    assert methods(result).index("SyncToClient") < methods(result).index("GetNotes")
    assert methods(result).index("SaveNotes") < methods(result).index("SyncToServer")
    reads = [call for call in result["calls"] if call[0] == "GetNotes"]
    expected = "notes_shortcut_Halo__Combat_Evolved_VR__Native_"
    assert len(reads) == 3
    assert all(call[1:] == [expected, expected + "_images/"] for call in reads)
    saved = result["document"]
    assert saved["shortcut_name"] == notes.NAME
    assert saved["notes"][0]["id"] == notes.NOTE_ID
    assert saved["notes"][0]["content"] == notes.NOTE_CONTENT
    assert saved["notes"][0]["time_created"] == saved["notes"][0]["time_modified"]
    assert "appid" not in saved["notes"][0]
    assert methods(result).count("unregister") == methods(result).count("RegisterForAppDetails")


def test_existing_notes_and_unknown_document_fields_are_preserved(notes):
    existing = [{"id": "user-note", "title": "My campaign", "content": "Leave untouched",
                 "other": {"key": [1, 2, 3]}}]
    original = document(notes, existing, unknown_metadata={"preserve": True})
    result = run_notes(notes, document=original)
    assert result["result"]["status"] == "added"
    assert result["document"]["notes"][:-1] == existing
    assert result["document"]["unknown_metadata"] == original["unknown_metadata"]


def test_matching_managed_note_is_idempotent(notes):
    original = document(notes, [managed(notes, extra="preserved")])
    result = run_notes(notes, document=original)
    assert result["result"]["status"] == "existing"
    assert result["document"] == original
    assert "SaveNotes" not in methods(result)


def test_only_exact_shipped_notes_are_allowed_previous_installer_content(notes):
    assert notes.PREVIOUS_NOTE_CONTENTS == (notes.A2_NOTE_CONTENT, notes.A4_NOTE_CONTENT, notes.STABLE_NOTE_CONTENT)
    assert hashlib.sha256(notes.A2_NOTE_CONTENT.encode("utf-8")).hexdigest() == \
        "a4e1776caa60548620e0510acbe194aa414645be8d042771d9cbe1ec49edc05e"
    assert hashlib.sha256(notes.A4_NOTE_CONTENT.encode("utf-8")).hexdigest() == \
        "55785ec794857e844722ba758a4ce47fdb607a6bba2c30f23a437dd8f320ae30"
    assert hashlib.sha256(notes.STABLE_NOTE_CONTENT.encode("utf-8")).hexdigest() == "ceed0d2d403fa18904c5d529ae409c8bfedad733fa1f1a7d93a6e2c2fdb8d32a"
    assert "save-v1.4" in notes.NOTE_CONTENT and "old save folder is retained" in notes.NOTE_CONTENT
    assert notes.NOTE_CONTENT != notes.A2_NOTE_CONTENT
    assert "LISTING to PUBLIC" in notes.NOTE_CONTENT and "PUBLIC lets anyone" in notes.NOTE_CONTENT
    assert "HOST LOCAL (LAN)" in notes.NOTE_CONTENT and "JOIN ONLINE (INTERNET)" in notes.NOTE_CONTENT
    assert "Flat-screen CO-OP CAMPAIGN retains local split-screen" not in notes.NOTE_CONTENT


@pytest.mark.parametrize("previous", ["A2_NOTE_CONTENT", "A4_NOTE_CONTENT", "STABLE_NOTE_CONTENT"])
def test_exact_unchanged_previous_note_is_upgraded_with_every_other_field_preserved(notes, previous):
    custom = {"id": "my-note", "title": "My campaign", "content": "Leave untouched", "extra": [1, 2]}
    old = managed(notes, content=getattr(notes, previous), ordinal=8, time_created=123, unknown={"keep": True})
    original = document(notes, [custom, old], unknown_document={"keep": [3]})
    result = run_notes(notes, document=original)
    assert result["result"]["status"] == "updated"
    assert methods(result).count("SaveNotes") == 1
    updated = result["document"]
    assert updated["unknown_document"] == original["unknown_document"]
    assert updated["notes"][0] == custom
    assert {key: value for key, value in updated["notes"][1].items() if key not in ("content", "time_modified")} == \
        {key: value for key, value in old.items() if key not in ("content", "time_modified")}
    assert updated["notes"][1]["content"] == notes.NOTE_CONTENT
    assert updated["notes"][1]["time_modified"] > old["time_modified"]
    assert run_notes(notes, document=updated)["result"]["status"] == "existing"


@pytest.mark.parametrize("field", ["content", "title", "shortcut_name"])
@pytest.mark.parametrize("previous", ["A2_NOTE_CONTENT", "A4_NOTE_CONTENT", "STABLE_NOTE_CONTENT"])
def test_previous_note_with_any_user_edit_or_identity_mismatch_is_preserved(notes, field, previous):
    old = getattr(notes, previous)
    changes = {"content": old}
    changes[field] = {"content": old + " ", "title": "My title", "shortcut_name": "Other game"}[field]
    original = document(notes, [managed(notes, **changes)])
    result = run_notes(notes, document=original)
    assert result["result"]["status"] == "custom"
    assert result["document"] == original
    assert "SaveNotes" not in methods(result)


@pytest.mark.parametrize("previous", ["A2_NOTE_CONTENT", "A4_NOTE_CONTENT", "STABLE_NOTE_CONTENT"])
def test_concurrent_edit_during_previous_note_upgrade_is_kept_without_write(notes, previous):
    old = getattr(notes, previous)
    original = document(notes, [managed(notes, content=old)])
    changed = document(notes, [managed(notes, content=old + " edited")])
    result = run_notes(notes, document=original, changeDocumentAtRead=2, changedDocument=changed)
    assert result["result"]["status"] == "manual"
    assert result["document"] == changed
    assert "SaveNotes" not in methods(result)


@pytest.mark.parametrize("previous", [None, [None], ["old"] * 5, ["é" * 8193]])
def test_malformed_or_excessive_previous_content_list_never_writes(notes, previous):
    original = document(notes, [managed(notes, content=notes.A2_NOTE_CONTENT)])
    result = run_notes(notes, document=original, spec_overrides={"previousContents": previous})
    assert result["result"]["status"] == "manual"
    assert result["document"] == original
    assert "SaveNotes" not in methods(result)


@pytest.mark.parametrize("previous", ["A2_NOTE_CONTENT", "A4_NOTE_CONTENT", "STABLE_NOTE_CONTENT"])
def test_exact_previous_note_upgrade_does_not_need_an_extra_note_slot(notes, previous):
    others = [{"id": str(index), "content": "Keep"} for index in range(notes.MAX_NOTES - 1)]
    result = run_notes(notes, document=document(notes, [*others, managed(notes, content=getattr(notes, previous))]))
    assert result["result"]["status"] == "updated"
    assert len(result["document"]["notes"]) == notes.MAX_NOTES
    assert result["document"]["notes"][:-1] == others


@pytest.mark.parametrize("changes", [{"content": "User edited"}, {"title": "User title"},
                                      {"shortcut_name": "Other game"}])
def test_edited_or_colliding_note_is_never_overwritten(notes, changes):
    original = document(notes, [managed(notes, **changes)])
    result = run_notes(notes, document=original)
    assert result["result"]["status"] == "custom"
    assert result["document"] == original
    assert "SaveNotes" not in methods(result)


@pytest.mark.parametrize("options", [
    {"document": {"notes": [], "shortcut_name": "Other game"}},
    {"document": {"notes": []}},
    {"document": {"notes": "not a list"}},
    {"document": {"notes": [None]}},
    {"invalidJSON": True}, {"missingResult": 2},
    {"readResult": 2, "document": {"notes": [], "shortcut_name": "Halo: Combat Evolved VR (Native)"}},
    {"foreignName": True}, {"foreignExe": True}, {"wrongId": True},
    {"syncClientResult": 2}, {"missingMethod": "SaveNotes"},
    {"changeAccountAt": "SyncToClient"}, {"changeAccountAt": "GetNotes"},
])
def test_unsupported_corrupt_foreign_or_changed_context_refuses_save(notes, options):
    result = run_notes(notes, **options)
    assert result["result"]["status"] == "manual"
    assert result["result"]["ok"] is False
    assert "SaveNotes" not in methods(result)


def test_duplicate_managed_id_is_manual_and_preserved(notes):
    original = document(notes, [managed(notes), managed(notes)])
    result = run_notes(notes, document=original)
    assert result["result"]["status"] == "manual"
    assert result["document"] == original
    assert "SaveNotes" not in methods(result)


def test_concurrent_note_edit_is_preserved_without_save(notes):
    original = document(notes)
    changed = document(notes, [{"id": "recent-edit", "content": "User typed this"}])
    result = run_notes(notes, document=original, changeDocumentAtRead=2, changedDocument=changed)
    assert result["result"]["status"] == "manual"
    assert result["document"] == changed
    assert "SaveNotes" not in methods(result)


@pytest.mark.parametrize("options", [{"saveResult": 2}, {"syncServerResult": 2},
                                      {"changeAccountAt": "SaveNotes"},
                                      {"changeDocumentAtRead": 3,
                                       "changedDocument": {"notes": [], "shortcut_name": "Other game"}}])
def test_failed_save_sync_or_readback_never_claims_success(notes, options):
    result = run_notes(notes, **options)
    assert result["result"]["status"] == "manual"
    assert result["result"]["ok"] is False


def test_document_count_and_utf8_byte_bounds_refuse_save(notes):
    full = document(notes, [{"id": str(index)} for index in range(notes.MAX_NOTES)])
    excessive = document(notes, [{"id": "user", "content": "é" * notes.MAX_DOCUMENT_BYTES}])
    for doc in (full, excessive):
        result = run_notes(notes, document=doc)
        assert result["result"]["status"] == "manual"
        assert "SaveNotes" not in methods(result)


@pytest.mark.parametrize("appid", [True, -1, 5, 2 ** 32, "3000000001"])
def test_wrapper_rejects_invalid_appid_without_client(notes, monkeypatch, appid):
    def unexpected_client():
        pytest.fail("An invalid app ID must not open the Steam client")
    monkeypatch.setattr(notes, "Client", unexpected_client)
    result = notes.add_notes(notes.HOME, notes.GAME, appid)
    assert result["status"] == "manual"
    assert result["title"] == notes.NOTE_TITLE and result["content"] == notes.NOTE_CONTENT


def test_wrapper_rejects_unmanaged_paths_without_client(notes, monkeypatch):
    monkeypatch.setattr(notes, "Client", lambda: pytest.fail("Unmanaged game must not connect"))
    assert notes.add_notes(notes.HOME, Path("/other/game"), 3000000001)["status"] == "manual"


def test_wrapper_client_failure_keeps_optional_manual_instructions(notes, monkeypatch):
    def unavailable():
        raise OSError("private endpoint detail")
    monkeypatch.setattr(notes, "Client", unavailable)
    result = notes.add_notes(notes.HOME, notes.GAME, 3000000001)
    assert result["status"] == "manual"
    assert "private endpoint" not in result["message"]


def test_wrapper_reports_verified_a2_upgrade_as_updated(notes, monkeypatch):
    class UpdatedClient:
        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            pass

        def evaluate(self, expression):
            assert "previousContents" in expression
            return {"ok": True, "status": "updated"}

    monkeypatch.setattr(notes, "Client", UpdatedClient)
    result = notes.add_notes(notes.HOME, notes.GAME, 3000000001)
    assert result["ok"] is True and result["status"] == "updated"
    assert "online co-op instructions" in result["message"]
    assert result["content"] == notes.NOTE_CONTENT


def test_module_has_no_file_or_session_mutation_routes(notes):
    source = (RESOURCES / "steam_notes.py").read_text(encoding="utf-8")
    assert "SetAppDescription" not in source and "steam_appid.txt" not in source
    assert "write_text(" not in source and "write_bytes(" not in source
    assert "subprocess" not in source and "Shutdown" not in source
    assert "SetShortcutName" not in source and "SetShortcutExe" not in source


def test_authored_note_matches_current_controls_and_protocol_scope(notes):
    assert "Right trigger: fire" in notes.NOTE_CONTENT
    assert "Left trigger: throw grenade" in notes.NOTE_CONTENT
    assert "Left bumper: change grenade type" in notes.NOTE_CONTENT
    assert "Right bumper: toggle flashlight" in notes.NOTE_CONTENT
    assert "compatible native/OpenCE protocol builds" in notes.NOTE_CONTENT
    assert "native ARM64 Linux/OpenXR" in notes.NOTE_CONTENT
