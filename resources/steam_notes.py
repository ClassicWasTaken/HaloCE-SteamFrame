"""Add an About and controls note through Steam's own live Game Notes API.

Steam Notes are private notes on the game details page. They do not replace
Steam's non-Steam description or create store metadata, achievements, or an
official Steam application. No Steam files or sessions are changed here.
"""
from __future__ import annotations

from steam_live import Client, GAME, HOME, NAME, SD_NAME, expression, native_spec

NOTE_ID = "haloframeaboutv1"
NOTE_TITLE = "Halo CE VR — About & controls"
# Exact unchanged 1.4.0a2 note, verified from its local source ZIP.
# UTF-8 SHA256: a4e1776caa60548620e0510acbe194aa414645be8d042771d9cbe1ec49edc05e
A2_NOTE_CONTENT = """[h1]Halo: Combat Evolved VR (Experimental)[/h1]
Play the original 2001 Halo: Combat Evolved campaign as Master Chief, fighting
the Covenant and uncovering the secrets of a mysterious ringworld.

This independent community installation uses your original Xbox game data
with an experimental native ARM64 Linux/OpenXR VR port on Steam Frame.
It is unaffiliated with Microsoft, Bungie, or Valve. VR support and performance
vary by scene, headset software, and settings.

[h2]Xbox-style Frame controls[/h2]
Point the right controller to aim; move your head to look around.
Left stick: move relative to your head direction. Left stick click: crouch.
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
This experimental build uses protocol 17; stable protocol 11 cannot join it.
For campaign co-op, host a LAN or internet game and choose a SINGLEPLAYER map.
The experimental game and saves use a separate folder. Older checkpoints
cannot be loaded. Extra co-op enemies are disabled by default.
Halo PC, Custom Edition, MCC, and retail Xbox server compatibility is not
provided by this installer.

[h2]Sources and setup help[/h2]
[url=https://github.com/ClassicWasTaken/HaloSteamFrameMod]Stable installer project and sources[/url]
[url=https://github.com/startupfoundry/halo-ce-universal/tree/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4]Pinned native port source[/url]
"""

A4_NOTE_CONTENT = A2_NOTE_CONTENT.replace(
    """[h2]Multiplayer[/h2]
LAN and internet play require compatible native/OpenCE protocol builds.
This experimental build uses protocol 17; stable protocol 11 cannot join it.
For campaign co-op, host a LAN or internet game and choose a SINGLEPLAYER map.
The experimental game and saves use a separate folder. Older checkpoints
cannot be loaded. Extra co-op enemies are disabled by default.
Halo PC, Custom Edition, MCC, and retail Xbox server compatibility is not
provided by this installer.
""",
    """[h2]Online campaign co-op with a friend[/h2]
LAN and internet play require compatible native/OpenCE protocol builds.
Both players should install the same experimental version and supply their
own supported original Xbox maps. This build uses protocol 17; stable
protocol 11, Halo PC, Custom Edition, MCC and retail Xbox clients cannot join.

Host: in an active headset, Multiplayer > CO-OP CAMPAIGN opens online
hosting with SINGLEPLAYER campaign maps. Choose a level, then difficulty.
In Server Setup, set LISTING to PUBLIC for controller-only discovery.
PUBLIC lets anyone find and join the game; PRIVATE is the default.
Choose START GAME. Friend: Multiplayer > Join Game > Server Browser,
REFRESH if needed, select the host's game and press A. When both players
appear in the lobby, wait for the countdown or select START NOW.
Use the left d-pad to navigate/change row choices, A to accept, B to go back.
Each player uses their own headset; no local second controller is required.

For invite-only play, keep PRIVATE. On the host, select the INVITE LINK row
and press A to copy its halo://join/ link; share it yourself. The friend
copies it on their Frame, then uses Join Game > Direct Link > PASTE LINK
and selects the host's game. A PC clipboard is separate from the Frame's.
An invite stops working after its hosting game quits.

Internet play uses direct UDP with signaling brokers, not a gameplay relay.
Strict NAT/CGNAT can prevent joining even when a listing is visible. UPnP,
hosting from the other network, or forwarding a fixed network.tunnel_port
on an accessible router may help; distant-peer VR co-op remains unverified.
The experimental game/saves stay separate; older checkpoints cannot load.
Extra co-op enemies are disabled by default. For the original menu route,
use Create Game > Internet and change the Map chooser to SINGLEPLAYER.
Flat-screen CO-OP CAMPAIGN retains local split-screen.
""")

# Exact previously shipped a3/a4 guide; upgrade only unchanged managed notes.
# UTF-8 SHA256: 55785ec794857e844722ba758a4ce47fdb607a6bba2c30f23a437dd8f320ae30
# Exact unchanged stable 1.3.5 note; UTF-8 SHA256: ceed0d2d403fa18904c5d529ae409c8bfedad733fa1f1a7d93a6e2c2fdb8d32a
STABLE_NOTE_CONTENT = "[h1]Halo: Combat Evolved VR (Native)[/h1]\nPlay the original 2001 Halo: Combat Evolved campaign as Master Chief, fighting\nthe Covenant and uncovering the secrets of a mysterious ringworld.\n\nThis independent community installation uses your original Xbox game data\nwith an experimental native ARM64 Linux/OpenXR VR port on Steam Frame.\nIt is unaffiliated with Microsoft, Bungie, or Valve. VR support and performance\nvary by scene, headset software, and settings.\n\n[h2]Xbox-style Frame controls[/h2]\nPoint the right controller to aim; move your head to look around.\nLeft stick: move. Left stick click: crouch.\nRight stick left/right: turn. Right stick click: zoom.\nRight trigger: fire. Left trigger: throw grenade.\nA: jump; accept menu selections. B: melee; go back in menus.\nX: reload/use; hold for context actions such as exchanging a weapon.\nY: change weapon. Left bumper: change grenade type.\nRight bumper: toggle flashlight. Left controller d-pad: navigate menus.\nView: scoreboard/back. Menu: pause.\nBoth grips held: recenter the headset view; release a held foregrip first.\nLeft grip near a long gun's foregrip: aim the gun with both hands.\nThese controls assume the game's default profile button layout.\nVR options are available in Settings > VR Setup.\n\n[h2]Multiplayer[/h2]\nLAN and internet play require compatible native/OpenCE protocol builds.\nHalo PC, Custom Edition, MCC, and retail Xbox server compatibility is not\nprovided by this installer.\n\n[h2]Sources and setup help[/h2]\n[url=https://github.com/ClassicWasTaken/HaloCE-SteamFrame]Installer, controls, and troubleshooting[/url]\n[url=https://github.com/startupfoundry/halo-ce-universal/tree/88142798513ebd99fc7c6224023e8b44c05d0106]Pinned native port source[/url]\n"
PREVIOUS_NOTE_CONTENTS = (A2_NOTE_CONTENT, A4_NOTE_CONTENT, STABLE_NOTE_CONTENT)
NOTE_CONTENT = (A4_NOTE_CONTENT[:A4_NOTE_CONTENT.index("[h2]Online campaign co-op with a friend[/h2]")]
                + """[h2]LAN and online campaign co-op[/h2]
LAN and internet play require compatible native/OpenCE protocol builds.
Both players should install the same experimental version and supply their
own supported original Xbox maps. This build uses protocol 17; stable
protocol 11, Halo PC, Custom Edition, MCC and retail Xbox clients cannot join.

Open Multiplayer > CO-OP CAMPAIGN. Each machine uses one local player.
On the same network: HOST LOCAL (LAN) and JOIN LOCAL (LAN).
Across different networks: HOST ONLINE (INTERNET) and JOIN ONLINE (INTERNET).
Choose a campaign level and difficulty on the host, then START GAME.
The friend selects the host's game; REFRESH if needed. Once both names
appear in the lobby, wait for the countdown or select START NOW.
Use the left d-pad to navigate/change choices, A to accept, B to go back.

Online hosting is PRIVATE by default. For server-browser discovery, set
LISTING to PUBLIC in Server Setup. PUBLIC lets anyone find and join.
For invite-only play, keep PRIVATE, select the INVITE LINK row and press A
to copy its halo://join/ link. Share it yourself. The friend copies it on
their Frame, selects JOIN INVITE LINK, then PASTE LINK and the host's game.
A PC clipboard is separate from the Frame's. The invite expires when its
hosting game quits. Each player uses their own headset or computer.

Internet play uses direct UDP with signaling brokers, not a gameplay relay.
Strict NAT/CGNAT can prevent joining even when a listing is visible. UPnP,
hosting from the other network, or forwarding a fixed network.tunnel_port
on an accessible router may help; distant-peer VR co-op remains unverified.
The experimental game/saves stay separate; older checkpoints cannot load.
Extra co-op enemies are disabled by default.

"""
                + A4_NOTE_CONTENT[A4_NOTE_CONTENT.index("[h2]Sources and setup help[/h2]"):])

# Public 1.4.0 uses the existing native shortcut and preserves older checkpoints.
NOTE_CONTENT = (NOTE_CONTENT
    .replace("Halo: Combat Evolved VR (Experimental)", "Halo: Combat Evolved VR (Native)")
    .replace("with an experimental native ARM64", "with a native ARM64")
    .replace("the same experimental version", "the same 1.4.0 release")
    .replace("This build uses protocol 17; stable", "1.4.0 uses protocol 17; 1.3.5")
    .replace("The experimental game/saves stay separate; older checkpoints cannot load.",
             "1.4.0 upgrades the existing native game. New profiles and saves use\n"
             "save-v1.4 inside its game folder. Your old save folder is retained\n"
             "unchanged; older checkpoints cannot load in the newer engine.")
    .replace("Stable installer project and sources", "Installer project and sources"))

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
  if (!Array.isArray(S.previousContents) || S.previousContents.length > 4 ||
      S.previousContents.some(content => typeof content !== 'string' ||
        new TextEncoder().encode(content).length > 16384))
    return manual('The previous installer note list is invalid. Existing notes were preserved.');
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
    let previous;
    if (matches.length) {
      await identity();
      if (matches[0].title !== S.title || matches[0].shortcut_name !== S.name ||
          (matches[0].content !== S.content && !S.previousContents.includes(matches[0].content)))
        return {ok:true,status:'custom',message:'Your edited Halo note was kept unchanged.'};
      if (matches[0].content === S.content)
        return {ok:true,status:'existing',message:'The Halo About and controls note is already present.'};
      previous=matches[0];
    }
    if (!previous && doc.notes.length >= S.maxNotes) throw new Error('Steam notes exceed supported bounds');
    const timestamp=Math.floor(Date.now()/1000);
    const note=previous ? {...previous,content:S.content,time_modified:timestamp} :
      {id:S.noteId,shortcut_name:S.name,ordinal:0,time_created:timestamp,
      time_modified:timestamp,title:S.title,content:S.content};
    const updated={...doc,notes:previous ? doc.notes.map(entry => entry === previous ? note : entry) :
      [...doc.notes,note]};
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
    return previous ? {ok:true,status:'updated',message:'Updated the unchanged Halo note with online co-op instructions.'} :
      {ok:true,status:'added',message:'Added the Halo About and controls note to Steam Game Notes.'};
  } catch(error) {
    return manual('Steam could not verify the Halo note. Your other notes were preserved; add the supplied text manually.');
  }
})()"""


def _note_content(name):
    if name == NAME:
        return NOTE_CONTENT
    if name != SD_NAME:
        raise ValueError("The native Halo Notes name is unsupported.")
    return (NOTE_CONTENT.replace(NAME, SD_NAME)
        .replace("the same 1.4.0 release", "matching native protocol-17 builds")
        .replace("1.4.0 uses protocol 17; 1.3.5", "This native build uses protocol 17; 1.3.5")
        .replace(
        "1.4.0 upgrades the existing native game. New profiles and saves use\n"
        "save-v1.4 inside its game folder. Your old save folder is retained\n"
        "unchanged; older checkpoints cannot load in the newer engine.",
        "This SD-card installation stays separate from the internal installation.\n"
        "Profiles and saves use save-v1.4 inside this game folder. Keep this SD\n"
        "card inserted and mounted when playing. Internal game files are retained."))


def add_notes(home, game, appid, name=None):
    """Return independent notes status without interrupting game registration."""
    result = {"ok": False, "status": "manual",
              "message": "Steam Game Notes is unavailable. Add the supplied text as a note manually.",
              "title": NOTE_TITLE, "content": NOTE_CONTENT}
    try:
        spec = native_spec(home, game, name)
        content = _note_content(spec["name"])
        result["content"] = content
        if type(appid) is not int or not 2 ** 31 <= appid < 2 ** 32:
            return result
        spec.update({"appid": appid, "noteId": NOTE_ID, "title": NOTE_TITLE,
                     "content": content, "maxBytes": MAX_DOCUMENT_BYTES,
                     "maxNotes": MAX_NOTES,
                     "previousContents": list(PREVIOUS_NOTE_CONTENTS) if spec["name"] == NAME else []})
        with Client() as client:
            value = client.evaluate(expression(NOTES, spec))
        status = value.get("status")
        if status in ("added", "updated", "existing", "custom") and value.get("ok") is True:
            result.update({"ok": True, "status": status,
                           "message": {"added": "Added the Halo About and controls note to Steam Game Notes.",
                                       "updated": "Updated the unchanged Halo note with online co-op instructions.",
                                       "existing": "The Halo About and controls note is already present.",
                                       "custom": "Your edited Halo note was kept unchanged."}[status]})
        elif status == "manual":
            result["message"] = "Steam could not verify the Halo note. Add the supplied text to Steam Game Notes manually."
    except Exception:
        # Notes are optional enrichment: failure never controls Steam, edits its
        # files, or changes a successfully installed game's registration.
        pass
    return result
