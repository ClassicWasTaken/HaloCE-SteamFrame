"""Add an About and controls note through Steam's own live Game Notes API.

Steam Notes are private notes on the game details page. They do not replace
Steam's non-Steam description or create store metadata, achievements, or an
official Steam application. No Steam files or sessions are changed here.
"""
from __future__ import annotations

from steam_live import Client, GAME, HOME, NAME, expression, native_spec

NOTE_ID = "haloframeaboutv1"
NOTE_TITLE = "Halo CE VR — About & controls"
NOTE_CONTENT = """[h1]Halo: Combat Evolved VR (Native)[/h1]
Play the original 2001 Halo: Combat Evolved campaign as Master Chief, fighting
the Covenant and uncovering the secrets of a mysterious ringworld.

This independent community installation uses your original Xbox game data
with an experimental native ARM64 Linux/OpenXR VR port on Steam Frame.
It is unaffiliated with Microsoft, Bungie, or Valve. VR support and performance
vary by scene, headset software, and settings.

[h2]Xbox-style Frame controls[/h2]
Point the right controller to aim; move your head to look around.
Left stick: move. Left stick click: crouch.
Right stick left/right: turn. Right stick click: zoom.
Right trigger: fire. Left trigger: throw grenade.
A: jump; accept menu selections. B: melee; go back in menus.
X: reload/use; hold for context actions such as exchanging a weapon.
Y: change weapon. Left bumper: change grenade type.
Right bumper: toggle flashlight. Left controller d-pad: navigate menus.
View: scoreboard/back. Menu: pause.
Both grips held: recenter the headset view; release a held foregrip first.
Left grip near a long gun's foregrip: aim the gun with both hands.
These controls assume the game's default profile button layout.
VR options are available in Settings > VR Setup.

[h2]Multiplayer[/h2]
LAN and internet play require compatible native/OpenCE protocol builds.
Halo PC, Custom Edition, MCC, and retail Xbox server compatibility is not
provided by this installer.

[h2]Sources and setup help[/h2]
[url=https://github.com/ClassicWasTaken/HaloCE-SteamFrame]Installer, controls, and troubleshooting[/url]
[url=https://github.com/startupfoundry/halo-ce-universal/tree/88142798513ebd99fc7c6224023e8b44c05d0106]Pinned native port source[/url]
"""

MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_NOTES = 512

NOTES = r"""(async () => {
  const deadline = Date.now() + 23000;
  const apps = typeof SteamClient !== 'undefined' && SteamClient.Apps;
  const notes = typeof SteamClient !== 'undefined' && SteamClient.GameNotes;
  const store = typeof appStore !== 'undefined' && appStore.m_mapApps;
  const user = typeof loginStore !== 'undefined' && loginStore.currentUser;
  const manual = message => ({ok:false,status:'manual',message});
  if (!apps || typeof apps.RegisterForAppDetails !== 'function' || !notes ||
      ['SyncToClient','GetNotes','SaveNotes','SyncToServer'].some(k => typeof notes[k] !== 'function') ||
      !store || typeof store.values !== 'function' || typeof store.get !== 'function' ||
      !user || typeof user.accountName !== 'string' || !user.accountName ||
      typeof TextEncoder !== 'function')
    return manual('Steam Game Notes is unavailable. Add the supplied text as a note manually.');
  const accountName = user.accountName;
  async function bounded(value, limit=3500) {
    let timer;
    try {
      return await Promise.race([Promise.resolve(value),new Promise((_,reject) => {
        timer=setTimeout(() => reject(new Error('Steam Game Notes timed out')),
          Math.max(1,Math.min(limit,deadline-Date.now())));
      })]);
    } finally { clearTimeout(timer); }
  }
  async function identity() {
    if (Date.now() >= deadline) throw new Error('Steam Game Notes timed out');
    if (loginStore.currentUser?.accountName !== accountName)
      throw new Error('The active Steam account changed');
    let count=0;
    for (const entry of store.values()) {
      if (++count > 100000) throw new Error('Steam library exceeds supported bounds');
      if (entry.appid !== S.appid && entry.display_name === S.name)
        throw new Error('Another game uses the native Halo shortcut name');
    }
    const overview=store.get(S.appid);
    if (!overview || overview.app_type !== 1073741824 || overview.display_name !== S.name)
      throw new Error('The native Halo shortcut identity changed');
    await new Promise((resolve,reject) => {
      let subscription,done=false;
      const cleanup=() => queueMicrotask(() => subscription?.unregister());
      const timer=setTimeout(() => {done=true;cleanup();
        reject(new Error('Native Halo notes identity timed out'));},
        Math.max(1,Math.min(3500,deadline-Date.now())));
      try {
        subscription=apps.RegisterForAppDetails(S.appid,data => {
          if (done) return;
          done=true;clearTimeout(timer);cleanup();
          if (data.unAppID !== S.appid ||
              ![S.exe,'"'+S.exe+'"'].includes(data.strShortcutExe) ||
              loginStore.currentUser?.accountName !== accountName)
            reject(new Error('Native Halo notes account or executable changed'));
          else resolve();
        });
      } catch(error) {done=true;clearTimeout(timer);cleanup();reject(error);}
    });
  }
  function parse(response, missingAllowed=false) {
    if (!response || typeof response !== 'object')
      throw new Error('Steam returned an invalid notes response');
    if (response.result === 9 && missingAllowed)
      return {notes:[],shortcut_name:S.name};
    if (response.result !== 1 || typeof response.notes !== 'string' ||
        new TextEncoder().encode(response.notes).length > S.maxBytes)
      throw new Error('Steam notes could not be read within supported bounds');
    const doc=JSON.parse(response.notes);
    if (!doc || typeof doc !== 'object' || Array.isArray(doc) ||
        doc.shortcut_name !== S.name || !Array.isArray(doc.notes) ||
        doc.notes.length > S.maxNotes ||
        doc.notes.some(note => !note || typeof note !== 'object' || Array.isArray(note)))
      throw new Error('Steam notes belong to another shortcut or have an unsupported format');
    return doc;
  }
  function encoded(doc) {
    const text=JSON.stringify(doc);
    if (new TextEncoder().encode(text).length > S.maxBytes)
      throw new Error('Steam notes exceed supported bounds');
    return text;
  }
  // These name and filename rules match Steam's own GameNotesCloudStore.
  const filename='notes_shortcut_'+S.name.trim().replace(/[!-/:-@ [\\\]^`]/g,'_');
  const images=filename+'_images/';
  try {
    await identity();
    if (await bounded(notes.SyncToClient(),7000) !== 1)
      throw new Error('Steam notes cloud synchronization is unavailable');
    await identity();
    const first=await bounded(notes.GetNotes(filename,images));
    const doc=parse(first,true);
    const matches=doc.notes.filter(note => note.id === S.noteId);
    if (matches.length > 1) throw new Error('The Halo notes identifier is ambiguous');
    if (matches.length) {
      await identity();
      if (matches[0].title !== S.title || matches[0].content !== S.content ||
          matches[0].shortcut_name !== S.name)
        return {ok:true,status:'custom',message:'Your edited Halo note was kept unchanged.'};
      return {ok:true,status:'existing',message:'The Halo About and controls note is already present.'};
    }
    if (doc.notes.length >= S.maxNotes) throw new Error('Steam notes exceed supported bounds');
    const timestamp=Math.floor(Date.now()/1000);
    const note={id:S.noteId,shortcut_name:S.name,ordinal:0,time_created:timestamp,
      time_modified:timestamp,title:S.title,content:S.content};
    const updated={...doc,notes:[...doc.notes,note]};
    const text=encoded(updated);
    // Do not overwrite edits made while the installer was preparing the note.
    const reread=await bounded(notes.GetNotes(filename,images));
    if (encoded(parse(reread,true)) !== encoded(doc))
      throw new Error('Steam notes changed while setup was preparing the Halo note');
    await identity();
    if (await bounded(notes.SaveNotes(filename,text),7000) !== 1)
      throw new Error('Steam could not save the Halo note');
    await identity();
    if (await bounded(notes.SyncToServer(),7000) !== 1)
      throw new Error('The Halo note was saved locally but cloud synchronization is pending');
    await identity();
    const readback=parse(await bounded(notes.GetNotes(filename,images)));
    if (encoded(readback) !== text)
      throw new Error('The Halo note could not be verified after saving');
    await identity();
    return {ok:true,status:'added',message:'Added the Halo About and controls note to Steam Game Notes.'};
  } catch(error) {
    return manual('Steam could not verify the Halo note. Your other notes were preserved; add the supplied text manually.');
  }
})()"""


def add_notes(home, game, appid, name=NAME):
    """Return independent notes status without interrupting game registration."""
    result = {"ok": False, "status": "manual",
              "message": "Steam Game Notes is unavailable. Add the supplied text as a note manually.",
              "title": NOTE_TITLE, "content": NOTE_CONTENT}
    try:
        spec = native_spec(home, game, name)
        if type(appid) is not int or not 2 ** 31 <= appid < 2 ** 32:
            return result
        spec.update({"appid": appid, "noteId": NOTE_ID, "title": NOTE_TITLE,
                     "content": NOTE_CONTENT, "maxBytes": MAX_DOCUMENT_BYTES,
                     "maxNotes": MAX_NOTES})
        with Client() as client:
            value = client.evaluate(expression(NOTES, spec))
        status = value.get("status")
        if status in ("added", "existing", "custom") and value.get("ok") is True:
            result.update({"ok": True, "status": status,
                           "message": {"added": "Added the Halo About and controls note to Steam Game Notes.",
                                       "existing": "The Halo About and controls note is already present.",
                                       "custom": "Your edited Halo note was kept unchanged."}[status]})
        elif status == "manual":
            result["message"] = "Steam could not verify the Halo note. Add the supplied text to Steam Game Notes manually."
    except Exception:
        # Notes are optional enrichment: failure never controls Steam, edits its
        # files, or changes a successfully installed game's registration.
        pass
    return result
