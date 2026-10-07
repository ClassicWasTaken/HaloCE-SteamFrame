"""Use Steam's verified local CEF library API without controlling its session.

This module has no CLI and accepts no caller-supplied JavaScript. It only talks
to loopback port 8080 and evaluates fixed native-Halo library operations.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import time
import urllib.parse
import urllib.request
import zlib

from frame_storage import validate_game_path

MAX_BYTES = 8 * 1024 * 1024
PORT = 8080
TIMEOUT = 30
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
HOME = Path("/home/steamos")
GAME = HOME / "Games/HaloCENativeVR"
NAME = "Halo: Combat Evolved VR (Native)"
SD_NAME = "Halo: Combat Evolved VR (Native, SD card)"
LAUNCH_OPTIONS = "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%"


class LiveSteamError(RuntimeError):
    pass


def verify_endpoint_owner(proc_net=Path("/proc/net")):
    """Require the kernel-reported listening socket UID before contacting CEF."""
    if not hasattr(os, "getuid"):
        raise LiveSteamError("Steam's live endpoint ownership cannot be verified.")
    owners = []
    for name in ("tcp", "tcp6"):
        try:
            with (proc_net / name).open("rb") as stream:
                encoded = stream.read(1024 * 1024 + 1)
        except FileNotFoundError:
            continue
        if len(encoded) > 1024 * 1024:
            raise LiveSteamError("Steam endpoint ownership data exceeds supported bounds.")
        for raw in encoded.decode("ascii", "strict").splitlines()[1:]:
            fields = raw.split()
            if len(fields) < 4:
                continue
            local = fields[1].rpartition(":")
            try:
                port = int(local[2], 16)
            except ValueError:
                continue
            if port == PORT and fields[3] == "0A":
                if len(fields) < 10 or not fields[7].isdecimal():
                    raise LiveSteamError("Steam's live endpoint owner is unknown.")
                owners.append(int(fields[7]))
    if not owners or any(uid != os.getuid() for uid in owners):
        raise LiveSteamError("Steam's live endpoint does not belong to this SteamOS account.")


class WebSocket:
    """Bounded stdlib CDP transport adapted from the previously verified helper."""

    def __init__(self, url, deadline):
        if not isinstance(url, str) or any(ord(char) < 32 or ord(char) == 127 for char in url):
            raise LiveSteamError("Unexpected Steam debugger WebSocket URL.")
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "ws" or parsed.hostname not in LOOPBACK or parsed.port != PORT
                or parsed.username or parsed.password or parsed.fragment
                or not parsed.path.startswith("/devtools/page/")):
            raise LiveSteamError("Steam debugger must use its verified loopback page endpoint.")
        self.deadline = deadline
        self.pending = bytearray()
        self.sock = socket.create_connection((parsed.hostname, PORT), self.remaining())
        try:
            self._handshake(parsed)
        except BaseException:
            self.sock.close()
            raise

    def _handshake(self, parsed):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        request = (f"GET {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode("ascii"))
        header = bytearray()
        while b"\r\n\r\n" not in header:
            self.sock.settimeout(self.remaining())
            chunk = self.sock.recv(4096)
            if not chunk:
                raise LiveSteamError("Steam debugger closed its WebSocket handshake.")
            header.extend(chunk)
            if len(header) > 65536:
                raise LiveSteamError("Steam debugger handshake exceeds supported bounds.")
        response, rest = bytes(header).split(b"\r\n\r\n", 1)
        self.pending.extend(rest)
        lines = response.decode("iso-8859-1").split("\r\n")
        if len(lines[0].split()) < 2 or lines[0].split()[1] != "101":
            raise LiveSteamError("Steam debugger rejected its WebSocket handshake.")
        headers = {key.lower().strip(): value.strip() for line in lines[1:] if ":" in line
                   for key, value in [line.split(":", 1)]}
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise LiveSteamError("Steam debugger returned an invalid handshake key.")

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("Steam's live library operation timed out.")
        return seconds

    def read(self, count):
        if not 0 <= count <= MAX_BYTES:
            raise LiveSteamError("Steam debugger read exceeds supported bounds.")
        while len(self.pending) < count:
            self.sock.settimeout(self.remaining())
            chunk = self.sock.recv(min(65536, count - len(self.pending)))
            if not chunk:
                raise LiveSteamError("Steam debugger WebSocket closed.")
            self.pending.extend(chunk)
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def send(self, payload, opcode=1):
        if len(payload) > MAX_BYTES:
            raise LiveSteamError("Steam debugger outgoing frame exceeds supported bounds.")
        size = len(payload)
        prefix = bytes([0x80 | opcode])
        if size < 126:
            prefix += bytes([0x80 | size])
        elif size <= 65535:
            prefix += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            prefix += bytes([0x80 | 127]) + struct.pack("!Q", size)
        mask = os.urandom(4)
        data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.settimeout(self.remaining())
        self.sock.sendall(prefix + mask + data)

    def receive_text(self):
        message, message_opcode = bytearray(), None
        while True:
            first, second = self.read(2)
            final, opcode = bool(first & 0x80), first & 0x0F
            if first & 0x70:
                raise LiveSteamError("Steam debugger requested unsupported WebSocket extensions.")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.read(8))[0]
            if length > MAX_BYTES or (opcode >= 8 and (not final or length > 125)):
                raise LiveSteamError("Steam debugger incoming frame exceeds supported bounds.")
            mask = self.read(4) if second & 0x80 else None
            payload = self.read(length)
            if mask:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 8:
                raise LiveSteamError("Steam debugger closed the connection.")
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                if message_opcode is not None:
                    raise LiveSteamError("Unexpected Steam debugger message start.")
                message_opcode = opcode
            elif opcode != 0 or message_opcode is None:
                raise LiveSteamError("Unexpected Steam debugger continuation frame.")
            message.extend(payload)
            if len(message) > MAX_BYTES:
                raise LiveSteamError("Steam debugger incoming message exceeds supported bounds.")
            if final:
                if message_opcode != 1:
                    raise LiveSteamError("Steam debugger returned a non-text CDP message.")
                return message.decode("utf-8")

    def close(self):
        try:
            self.send(b"", 8)
        except (OSError, TimeoutError):
            pass
        self.sock.close()


class Client:
    def __init__(self):
        verify_endpoint_owner()
        self.deadline = time.monotonic() + TIMEOUT
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(f"http://127.0.0.1:{PORT}/json", timeout=5) as response:
            encoded = response.read(MAX_BYTES + 1)
        if len(encoded) > MAX_BYTES:
            raise LiveSteamError("Steam debugger target list exceeds supported bounds.")
        targets = json.loads(encoded)
        if not isinstance(targets, list):
            raise LiveSteamError("Steam debugger target list has an unsupported format.")
        matches = [target for target in targets if isinstance(target, dict)
                   and target.get("title") == "SharedJSContext" and target.get("webSocketDebuggerUrl")]
        if len(matches) != 1:
            raise LiveSteamError("Steam's live library context is unavailable or ambiguous.")
        self.ws = WebSocket(matches[0]["webSocketDebuggerUrl"], self.deadline)
        self.sequence = 0

    def evaluate(self, expression):
        if len(expression.encode("utf-8")) > MAX_BYTES:
            raise LiveSteamError("Steam library request exceeds supported bounds.")
        self.sequence += 1
        self.ws.send(json.dumps({"id": self.sequence, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
            "timeout": max(1, int(self.ws.remaining() * 1000)),
        }}).encode("utf-8"))
        for _ in range(512):
            response = json.loads(self.ws.receive_text())
            if not isinstance(response, dict) or response.get("id") != self.sequence:
                continue
            result = response.get("result", {})
            if "error" in response or not isinstance(result, dict) or "exceptionDetails" in result:
                raise LiveSteamError("Steam's live library API could not complete the verified operation.")
            remote = result.get("result", {})
            value = remote.get("value") if isinstance(remote, dict) else None
            if not isinstance(value, dict):
                raise LiveSteamError("Steam's live library API returned an unsupported response.")
            return value
        raise LiveSteamError("Steam debugger produced too many unrelated events.")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.ws.close()


def native_spec(home, game, name=None, launch_options=LAUNCH_OPTIONS):
    if Path(home) != HOME or launch_options != LAUNCH_OPTIONS:
        raise LiveSteamError("The live client path is restricted to the managed native Halo installation.")
    try:
        destination = validate_game_path(home, game)
    except (OSError, ValueError) as error:
        raise LiveSteamError("The live client path is restricted to a currently verified native Halo installation: " + str(error)) from error
    expected_name = SD_NAME if destination["kind"] == "sd" else NAME
    if name is not None and name != expected_name:
        raise LiveSteamError("The live client shortcut name is restricted to its verified native Halo destination.")
    game = Path(game)
    exe = str(game / "halo")
    return {"name": expected_name, "exe": exe, "directory": str(game), "launchOptions": LAUNCH_OPTIONS,
            "candidateAppids": [zlib.crc32((value + expected_name).encode()) | 0x80000000
                                 for value in (exe, '"' + exe + '"')]}


PROBE = r"""(() => {
  const apps = typeof SteamClient !== 'undefined' && SteamClient.Apps;
  const store = typeof appStore !== 'undefined' && appStore.m_mapApps;
  if (!apps || !store || typeof store.values !== 'function') return {supported:false};
  const required = S.operation === 'remove' ? ['RemoveShortcut','RegisterForAppDetails'] :
    ['AddShortcut','SetShortcutName','SetShortcutExe','SetShortcutStartDir',
     'SetShortcutLaunchOptions','SetAppLaunchOptions','SpecifyCompatTool',
     'SetShortcutIsVR','RegisterForAppDetails'];
  const missing = required.filter(key => typeof apps[key] !== 'function');
  return {supported:missing.length === 0, missing};
})()"""


LIBRARY = r"""(async () => {
  const apps = SteamClient.Apps, store = appStore.m_mapApps;
  const deadline = Date.now() + 23000;
  const validId = id => Number.isInteger(id) && id >= 2147483648 && id < 4294967296;
  const exact = (value, wanted) => value === wanted || value === '"' + wanted + '"';
  const exactDirectory = value => exact(value, S.directory) || exact(value, S.directory + '/');
  async function bounded(value, limit = 3500) {
    let timer;
    try {
      return await Promise.race([Promise.resolve(value), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Steam library API timed out')),
          Math.max(1, Math.min(limit, deadline - Date.now())));
      })]);
    } finally { clearTimeout(timer); }
  }
  function all() {
    const entries = [];
    for (const entry of store.values()) {
      if (entries.length >= 100000) throw new Error('Steam library exceeds supported bounds');
      entries.push(entry);
    }
    return entries;
  }
  async function details(id, accept = () => true) {
    if (!validId(id)) throw new Error('Native shortcut app ID is invalid');
    return await new Promise((resolve, reject) => {
      let subscription, done = false;
      const cleanup = () => queueMicrotask(() => subscription?.unregister());
      const timer = setTimeout(() => {
        done = true; cleanup(); reject(new Error('Native shortcut details timed out'));
      }, Math.max(1, Math.min(4000, deadline - Date.now())));
      try {
        subscription = apps.RegisterForAppDetails(id, data => {
          if (done) return;
          const value = {appid:data.unAppID, exe:data.strShortcutExe,
            directory:data.strShortcutStartDir, launchOptions:data.strLaunchOptions,
            shortcutLaunchOptions:data.strShortcutLaunchOptions, vr:data.bShortcutIsVR,
            compatibilityTool:data.strCompatToolName};
          if (!accept(value)) return;
          done = true; clearTimeout(timer); cleanup(); resolve(value);
        });
      } catch (error) { done = true; clearTimeout(timer); cleanup(); reject(error); }
    });
  }
  async function identity() {
    // Steam initially names added entries from the executable, and users can
    // rename entries. Read exact paths before concluding the game is absent.
    const shortcuts = all().filter(entry => entry.app_type === 1073741824);
    if (shortcuts.length > 256) throw new Error('Too many non-Steam shortcuts to verify safely');
    const owned = [], foreign = [];
    for (let index = 0; index < shortcuts.length; index += 8) {
      const chunk = shortcuts.slice(index, index + 8);
      const values = await Promise.all(chunk.map(entry => details(entry.appid)));
      for (let position = 0; position < chunk.length; position++) {
        const entry = chunk[position], data = values[position];
        if (data.appid !== entry.appid) throw new Error('Shortcut details identity changed');
        if (exact(data.exe, S.exe)) owned.push(entry.appid);
        else if (entry.display_name === S.name || S.candidateAppids.includes(entry.appid))
          foreign.push(entry.appid);
      }
    }
    if (owned.length > 1) throw new Error('Multiple exact native Halo shortcuts exist');
    return {owned, foreign};
  }
  async function waitFor(check) {
    const until = Math.min(deadline, Date.now() + 4000);
    do {
      if (check()) return;
      await new Promise(resolve => setTimeout(resolve, 50));
    } while (Date.now() < until);
    throw new Error('Steam library readback timed out');
  }
  const before = await identity();
  if (S.operation === 'remove') {
    if (!before.owned.length) return {ok:true, status:'already-absent'};
    const id = before.owned[0];
    await bounded(apps.RemoveShortcut(id));
    await waitFor(() => !all().some(entry => entry.appid === id));
    const after = await identity();
    if (after.owned.length) throw new Error('Native shortcut removal could not be verified');
    return {ok:true, status:'removed', appid:id};
  }
  if (before.foreign.length) throw new Error('A different game uses the native Halo shortcut name');
  let id = before.owned[0], created = false;
  if (id === undefined) {
    if (all().some(entry => S.candidateAppids.includes(entry.appid)))
      throw new Error('Native shortcut app ID collides with another game');
    const previousIds = new Set(all().map(entry => entry.appid));
    // Verified installed-client signature: name, executable, arguments, cmdline.
    id = await bounded(apps.AddShortcut(S.name, S.exe, '', '"' + S.exe + '"'));
    if (!validId(id) || previousIds.has(id)) throw new Error('New native shortcut identity is invalid');
    created = true;
    await waitFor(() => all().some(entry => entry.appid === id && entry.app_type === 1073741824));
    const added = await details(id);
    if (added.appid !== id || !exact(added.exe, S.exe)) throw new Error('New native shortcut path could not be verified');
  }
  await bounded(apps.SetShortcutName(id, S.name));
  await bounded(apps.SetShortcutExe(id, S.exe));
  await bounded(apps.SetShortcutStartDir(id, S.directory));
  await bounded(apps.SetShortcutLaunchOptions(id, S.launchOptions));
  await bounded(apps.SetAppLaunchOptions(id, S.launchOptions));
  await bounded(apps.SpecifyCompatTool(id, ''));
  await bounded(apps.SetShortcutIsVR(id, true));
  const verified = await details(id, value => value.appid === id && exact(value.exe, S.exe) &&
    exactDirectory(value.directory) && value.launchOptions === S.launchOptions &&
    value.shortcutLaunchOptions === S.launchOptions && value.vr === true &&
    typeof value.compatibilityTool === 'string' && value.compatibilityTool === '');
  const after = await identity();
  if (after.owned.length !== 1 || after.owned[0] !== id || after.foreign.length)
    throw new Error('Native shortcut identity changed during registration');
  return {ok:true, status:'added', appid:id, created, verified};
})()"""


def expression(source, spec):
    # Only JSON literals are interpolated; Steam data is never executable source.
    # Each CDP evaluation gets a local scope; global lexical bindings persist.
    return "(() => {const S = " + json.dumps(spec, ensure_ascii=True) + ";\nreturn " + source + ";})()"


def _library(home, game, name, operation, launch_options=LAUNCH_OPTIONS):
    spec = native_spec(home, game, name, launch_options)
    spec["operation"] = operation
    with Client() as client:
        capabilities = client.evaluate(expression(PROBE, spec))
        if capabilities.get("supported") is not True:
            raise LiveSteamError("Steam's live library API is unavailable; its session was kept running.")
        value = client.evaluate(expression(LIBRARY, spec))
    if value.get("ok") is not True:
        raise LiveSteamError("Steam's live library operation could not be verified.")
    if operation == "remove":
        if value.get("status") not in ("removed", "already-absent"):
            raise LiveSteamError("Steam's native shortcut removal could not be verified.")
        if value.get("status") == "removed" and (type(value.get("appid")) is not int or not 2 ** 31 <= value["appid"] < 2 ** 32):
            raise LiveSteamError("Steam's removed native shortcut identity could not be verified.")
    else:
        if value.get("status") != "added" or type(value.get("appid")) is not int or not 2 ** 31 <= value["appid"] < 2 ** 32:
            raise LiveSteamError("Steam's native shortcut registration could not be verified.")
        verified = value.get("verified")
        exact = lambda actual, wanted: actual in (wanted, '"' + wanted + '"')
        if (not isinstance(verified, dict) or verified.get("appid") != value["appid"]
                or not exact(verified.get("exe"), spec["exe"])
                or not any(exact(verified.get("directory"), variant) for variant in (spec["directory"], spec["directory"] + "/"))
                or verified.get("launchOptions") != LAUNCH_OPTIONS or verified.get("shortcutLaunchOptions") != LAUNCH_OPTIONS
                or verified.get("vr") is not True or verified.get("compatibilityTool") != ""):
            raise LiveSteamError("Steam's native launch settings did not pass readback verification.")
    value["name"] = spec["name"]
    return value


ART_CONTEXT = r"""
  async function current() {
    const apps = typeof SteamClient !== 'undefined' && SteamClient.Apps;
    const user = typeof loginStore !== 'undefined' && loginStore.currentUser;
    if (!apps || typeof apps.SetCustomArtworkForApp !== 'function' ||
        typeof apps.RegisterForAppDetails !== 'function' ||
        !user || typeof user.accountName !== 'string' || !user.accountName)
      throw new Error('Active Steam artwork account is unavailable');
    const accountName = user.accountName;
    const details = await new Promise((resolve, reject) => {
      let subscription, done = false;
      const cleanup = () => queueMicrotask(() => subscription?.unregister());
      const timer = setTimeout(() => {done = true; cleanup();
        reject(new Error('Native artwork identity readback timed out'));}, 4000);
      try {
        subscription = apps.RegisterForAppDetails(S.appid, data => {
          if (done) return;
          done = true; clearTimeout(timer); cleanup();
          resolve({appid:data.unAppID, exe:data.strShortcutExe});
        });
      } catch (error) {done = true; clearTimeout(timer); cleanup(); reject(error);}
    });
    if (details.appid !== S.appid ||
        ![S.exe, '"' + S.exe + '"'].includes(details.exe) ||
        loginStore.currentUser?.accountName !== accountName)
      throw new Error('Native artwork account or executable changed');
    return {accountName, appid:details.appid, exe:details.exe};
  }
"""

ART_SESSION = "(async () => {" + ART_CONTEXT + "return await current();})()"
ART_WRITE = "(async () => {" + ART_CONTEXT + r"""
  const before = await current();
  if (before.accountName !== S.accountName) throw new Error('Steam artwork account changed');
  let timer;
  try {
    await Promise.race([Promise.resolve(SteamClient.Apps.SetCustomArtworkForApp(
      S.appid, S.base64Data, S.extension, S.assetType)),
      new Promise((_, reject) => {timer = setTimeout(() =>
        reject(new Error('Steam artwork API timed out')), 7000);})]);
  } finally {clearTimeout(timer);}
  const after = await current();
  if (after.accountName !== S.accountName) throw new Error('Steam artwork account changed');
  return {ok:true, accountName:after.accountName, appid:after.appid};
})()"""

ICON_WRITE = "(async () => {" + ART_CONTEXT + r"""
  if (typeof SteamClient.Apps.SetShortcutIcon !== 'function')
    throw new Error('Steam shortcut icon API is unavailable');
  const before = await current();
  if (before.accountName !== S.accountName) throw new Error('Steam icon account changed');
  const overview = typeof appStore !== 'undefined' &&
    typeof appStore.GetAppOverviewByAppID === 'function' ? appStore.GetAppOverviewByAppID(S.appid) : null;
  if (typeof overview?.icon_data !== 'string' || overview.icon_data.length)
    throw new Error('Steam current icon is no longer confirmed empty');
  let timer;
  try {
    await Promise.race([Promise.resolve(SteamClient.Apps.SetShortcutIcon(S.appid, S.iconPath)),
      new Promise((_, reject) => {timer = setTimeout(() =>
        reject(new Error('Steam shortcut icon API timed out')), 7000);})]);
  } finally {clearTimeout(timer);}
  const after = await current();
  if (after.accountName !== S.accountName) throw new Error('Steam icon account changed');
  return {ok:true, accountName:after.accountName, appid:after.appid};
})()"""

ICON_SESSION = "(async () => {" + ART_CONTEXT + r"""
  const session = await current();
  const overview = typeof appStore !== 'undefined' &&
    typeof appStore.GetAppOverviewByAppID === 'function' ? appStore.GetAppOverviewByAppID(S.appid) : null;
  const data = overview?.icon_data;
  let iconRequested = false;
  if (data === undefined && S.requestIcon === true && typeof SteamClient.Apps.RequestIconDataForApp === 'function') {
    SteamClient.Apps.RequestIconDataForApp(S.appid);
    iconRequested = true;
  }
  return {...session, iconRequested,
    iconState:typeof data !== 'string' ? 'unknown' : data.length ? 'present' : 'empty'};
})()"""


def _artwork_config(home, account_name):
    """Resolve the live client's account, never the disk MostRecent heuristic."""
    from steam_shortcut import _artwork_file, _private_steam_directory, _text_vdf
    if (not isinstance(account_name, str) or not account_name or len(account_name) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in account_name)):
        raise LiveSteamError("Steam's active artwork account could not be verified.")
    steam = Path(home) / ".local/share/Steam"
    for directory in (steam, steam / "config", steam / "userdata"):
        _private_steam_directory(directory)
    fields = _text_vdf(_artwork_file(steam / "config/loginusers.vdf", 512 * 1024).decode("utf-8"))
    users = [value for key, value in fields.items() if key.casefold() == "users" and isinstance(value, dict)]
    if len(users) != 1:
        raise LiveSteamError("Steam's active artwork account could not be matched to one profile.")
    accounts = []
    for steam_id, profile in users[0].items():
        if not isinstance(profile, dict):
            continue
        names = [value for key, value in profile.items() if key.casefold() == "accountname"]
        if len(names) != 1 or names[0] != account_name:
            continue
        if not steam_id.isdecimal() or len(steam_id) != 17:
            raise LiveSteamError("Steam's active artwork profile has an invalid ID.")
        account = int(steam_id) - 76561197960265728
        if not 0 < account < 2 ** 32:
            raise LiveSteamError("Steam's active artwork profile has an invalid ID.")
        accounts.append(str(account))
    if len(accounts) != 1:
        raise LiveSteamError("Steam's active artwork account could not be matched to one profile.")
    config = steam / "userdata" / accounts[0] / "config"
    for directory in (config.parent, config):
        _private_steam_directory(directory)
    grid = config / "grid"
    if grid.is_symlink() or grid.resolve() != grid or (grid.exists() and not grid.is_dir()):
        raise LiveSteamError("Steam's live artwork folder is not an ordinary directory.")
    if grid.exists():
        _private_steam_directory(grid)
    return grid


def _live_artwork(home, game, appid, sources=None):
    from steam_shortcut import (ARTWORK, ARTWORK_EXTENSIONS, ARTWORK_TYPES, ICON_NAME,
                                ICON_SHA256, _artwork_file, _private_steam_directory)
    spec = native_spec(home, game)
    spec["appid"] = appid
    sources = Path(sources) if sources is not None else Path(__file__).resolve().parent / "artwork"
    _private_steam_directory(sources)
    payloads = []
    for suffix, extension, filename, expected in ARTWORK:
        content = _artwork_file(sources / filename)
        if hashlib.sha256(content).hexdigest() != expected:
            raise LiveSteamError("Bundled Halo artwork failed its integrity check.")
        payloads.append({"stem": str(appid) + suffix, "extension": extension, "content": content,
                         "expected": expected, "assetType": ARTWORK_TYPES[suffix]})
    if hashlib.sha256(_artwork_file(sources / ICON_NAME)).hexdigest() != ICON_SHA256:
        raise LiveSteamError("Bundled Halo shortcut icon failed its integrity check.")
    installed, preserved, unchanged = [], [], []
    with Client() as client:
        def snapshot():
            session = client.evaluate(expression(ART_SESSION, spec))
            if (type(session.get("appid")) is not int or session["appid"] != appid
                    or session.get("exe") not in (spec["exe"], '"' + spec["exe"] + '"')):
                raise LiveSteamError("Steam's live artwork shortcut could not be verified.")
            return session
        session = snapshot()
        account_name = session.get("accountName")
        grid = _artwork_config(home, account_name)

        def inspect(payload):
            paths = [grid / (payload["stem"] + extension) for extension in ARTWORK_EXTENSIONS]
            present = [(path, _artwork_file(path)) for path in paths if path.exists() or path.is_symlink()]
            if not present:
                return "missing", []
            if (len(present) == 1 and present[0][0].name == payload["stem"] + payload["extension"]
                    and hashlib.sha256(present[0][1]).hexdigest() == payload["expected"]):
                return "unchanged", [present[0][0].name]
            return "preserved", [path.name for path, _ in present]

        # Validate all existing categories before publishing any asset.
        for payload in payloads:
            inspect(payload)
        for payload in payloads:
            state, names = inspect(payload)
            if state == "unchanged":
                unchanged.extend(names)
                continue
            if state == "preserved":
                preserved.extend(names)
                continue
            # Re-read the active account and category immediately before the API.
            fresh = snapshot()
            if fresh.get("accountName") != account_name or _artwork_config(home, account_name) != grid:
                raise LiveSteamError("Steam's active artwork account changed during setup.")
            state, names = inspect(payload)
            if state != "missing":
                (unchanged if state == "unchanged" else preserved).extend(names)
                continue
            write_spec = {**spec, "accountName": account_name,
                          "base64Data": base64.b64encode(payload["content"]).decode("ascii"),
                          "extension": payload["extension"].lstrip("."), "assetType": payload["assetType"]}
            result = client.evaluate(expression(ART_WRITE, write_spec))
            if result.get("ok") is not True or result.get("appid") != appid or result.get("accountName") != account_name:
                raise LiveSteamError("Steam's artwork update could not be verified.")
            target = grid / (payload["stem"] + payload["extension"])
            deadline = min(client.deadline, time.monotonic() + 5)
            while True:
                if grid.exists():
                    _private_steam_directory(grid)
                if target.exists() or target.is_symlink():
                    if hashlib.sha256(_artwork_file(target)).hexdigest() != payload["expected"]:
                        raise LiveSteamError("Steam's new Halo artwork did not pass its integrity check.")
                    break
                if time.monotonic() >= deadline:
                    raise LiveSteamError("Steam's new Halo artwork could not be verified on disk.")
                time.sleep(0.1)
            installed.append(target.name)
        after = snapshot()
        if after.get("accountName") != account_name:
            raise LiveSteamError("Steam's active artwork account changed during setup.")
    return {"status": "added" if installed else "preserved" if preserved else "unchanged",
            "installed": installed, "preserved": preserved, "unchanged": unchanged}


def _live_icon(home, game, appid, sources=None):
    """Use the path API, reading persisted VDF only for identity and readback.

    Unlike the artwork API, Steam's shortcut icon API does not expose an icon
    path in AppDetails. Never assume such a field or write a live VDF ourselves.
    A newly created shortcut that has not yet persisted can be retried safely.
    """
    from steam_shortcut import (ICON_NAME, ICON_SHA256, _artwork_file,
                                _private_steam_directory, _publish_shortcut_icon,
                                _shortcut_icon_field)
    spec = native_spec(home, game)
    spec["appid"] = appid
    spec["requestIcon"] = True
    source = Path(sources) if sources is not None else Path(__file__).resolve().parent / "artwork"
    _private_steam_directory(source)
    if hashlib.sha256(_artwork_file(source / ICON_NAME)).hexdigest() != ICON_SHA256:
        raise LiveSteamError("Bundled Halo shortcut icon failed its integrity check.")
    with Client() as client:
        def snapshot():
            session = client.evaluate(expression(ICON_SESSION, spec))
            if (session.get("appid") != appid or session.get("exe") not in (spec["exe"], '"' + spec["exe"] + '"')):
                raise LiveSteamError("Steam's live icon shortcut could not be verified.")
            return session

        session = snapshot()
        account_name = session.get("accountName")
        spec["requestIcon"] = False
        config = _artwork_config(home, account_name).parent
        persisted = config / "shortcuts.vdf"
        _private_steam_directory(config)

        def current_icon():
            _, _, selected = _shortcut_icon_field(_artwork_file(persisted), appid, spec["exe"])
            return selected

        selected = current_icon()
        target = Path(game) / ".installer-artwork" / ICON_NAME
        if selected:
            if selected not in (str(target), '"' + str(target) + '"'):
                return {"status": "preserved", "reason": "Your selected Steam shortcut icon was kept."}
            _private_steam_directory(target.parent)
            if hashlib.sha256(_artwork_file(target)).hexdigest() == ICON_SHA256:
                return {"status": "unchanged", "path": str(target)}
            return {"status": "preserved", "reason": "Your customized Halo icon was kept."}
        if session.get("iconState") == "unknown" and session.get("iconRequested") is True:
            # Steam's own UI requests undefined data and waits for it to become
            # non-null. Request once, then accept only an explicit empty string.
            load_deadline = min(client.deadline, time.monotonic() + 2)
            while session.get("iconState") == "unknown" and time.monotonic() < load_deadline:
                time.sleep(0.1)
                session = snapshot()
                if session.get("accountName") != account_name or _artwork_config(home, account_name).parent != config:
                    raise LiveSteamError("Steam's active icon account changed while its icon was loading.")
        # The persisted record can lag a user's latest icon choice. A loaded
        # resident icon wins, and an unloaded value cannot prove it is empty.
        if session.get("iconState") == "present":
            return {"status": "preserved", "reason": "The icon currently loaded by Steam was kept."}
        if session.get("iconState") != "empty":
            raise LiveSteamError("Steam's current shortcut icon has not loaded yet. Click Add to Steam again after opening Halo's library page.")
        icon = _publish_shortcut_icon(Path(game), source)
        if "path" not in icon:
            return icon
        fresh = snapshot()
        if (fresh.get("accountName") != account_name or _artwork_config(home, account_name).parent != config):
            raise LiveSteamError("Steam's active icon account changed during setup.")
        if fresh.get("iconState") == "present":
            return {"status": "preserved", "reason": "The icon currently loaded by Steam was kept."}
        if fresh.get("iconState") != "empty":
            raise LiveSteamError("Steam's current shortcut icon could not be verified as empty.")
        # A user-selected path that appeared while preparing the sidecar wins.
        if current_icon():
            return {"status": "preserved", "reason": "Your selected Steam shortcut icon was kept."}
        result = client.evaluate(expression(ICON_WRITE, {**spec, "accountName": account_name, "iconPath": icon["path"]}))
        if result.get("ok") is not True or result.get("appid") != appid or result.get("accountName") != account_name:
            raise LiveSteamError("Steam's shortcut icon update could not be verified.")
        deadline = min(client.deadline, time.monotonic() + 5)
        while True:
            selected = current_icon()
            if selected in (icon["path"], '"' + icon["path"] + '"'):
                break
            if selected or time.monotonic() >= deadline:
                raise LiveSteamError("Steam has not yet persisted the Halo icon selection. Click Add to Steam again to retry.")
            time.sleep(0.1)
        if hashlib.sha256(_artwork_file(target)).hexdigest() != ICON_SHA256:
            raise LiveSteamError("Steam's Halo icon source changed during setup.")
        after = snapshot()
        if after.get("accountName") != account_name or _artwork_config(home, account_name).parent != config:
            raise LiveSteamError("Steam's active icon account changed during setup.")
        return {"status": "added", "path": icon["path"]}


def add_native(home, game, name=None, launch_options=LAUNCH_OPTIONS, artwork=None):
    value = _library(home, game, name, "add", launch_options)
    try:
        art_result = _live_artwork(home, game, value["appid"], artwork)
    except (ImportError, OSError, ValueError, RuntimeError, UnicodeError) as error:
        art_result = {"status": "manual", "reason": str(error),
                      "instructions": "Use Steam's custom artwork options, or retry adding Halo box art."}
    try:
        art_result["icon"] = _live_icon(home, game, value["appid"], artwork)
    except (ImportError, OSError, ValueError, RuntimeError, UnicodeError) as error:
        art_result["icon"] = {"status": "manual", "reason": str(error),
                              "instructions": "Click Add to Steam again to retry the Halo shortcut icon."}
    return {"status": "added", "libraryAdded": True, "appid": value["appid"], "name": value["name"],
            "unchanged": not value.get("created", False), "transport": "live-client",
            "artwork": art_result}


def remove_native(home, game, name=None):
    value = _library(home, game, name, "remove")
    return {"status": value["status"], "name": value["name"], "transport": "live-client", "accountScope": "active-client",
            **({"appid": value["appid"]} if "appid" in value else {})}
