"""Add the native game to the most recent Steam account while Steam is closed.

Steam's binary shortcuts format is undocumented. Unknown types are rejected,
existing entries retain their type/value structure, and an exact backup is kept.
"""
from __future__ import annotations

import json
import os
import re
import struct
import tempfile
import time
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

NAME = "Halo: Combat Evolved VR (Native)"
LAUNCH_OPTIONS = "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%"


@dataclass
class Value:
    kind: int
    value: object


def loads(data: bytes) -> OrderedDict:
    cursor = 0

    def read(n):
        nonlocal cursor
        if n < 0 or cursor + n > len(data):
            raise ValueError("Steam shortcuts file is truncated.")
        result = data[cursor:cursor + n]
        cursor += n
        return result

    def string():
        nonlocal cursor
        end = data.find(b"\0", cursor)
        if end < 0:
            raise ValueError("Steam shortcuts string is truncated.")
        result = data[cursor:end].decode("utf-8", "surrogateescape")
        cursor = end + 1
        return result

    def obj(depth=0):
        if depth > 20:
            raise ValueError("Steam shortcuts file is too deeply nested.")
        result = OrderedDict()
        while True:
            kind = read(1)[0]
            if kind == 8:
                return result
            key = string()
            if key in result:
                raise ValueError("Steam shortcuts has duplicate fields; no changes were made.")
            if kind == 0:
                value = obj(depth + 1)
            elif kind == 1:
                value = string()
            elif kind == 2:
                value = struct.unpack("<I", read(4))[0]
            elif kind in (3, 4, 6):
                value = read(4)
            elif kind == 5:
                count = read(2)
                value = count + read(struct.unpack("<H", count)[0] * 2)
            elif kind in (7, 10):
                value = read(8)
            else:
                raise ValueError(f"Unsupported Steam shortcuts field type {kind}; no changes were made.")
            result[key] = Value(kind, value)
    root = obj()
    if cursor != len(data):
        raise ValueError("Unexpected data after the Steam shortcuts root.")
    return root


def dumps(root: OrderedDict) -> bytes:
    def text(value):
        encoded = str(value).encode("utf-8", "surrogateescape")
        if b"\0" in encoded:
            raise ValueError("Steam shortcut fields cannot contain NUL.")
        return encoded + b"\0"

    def obj(fields):
        result = bytearray()
        for key, field in fields.items():
            result.extend(bytes([field.kind]) + text(key))
            if field.kind == 0:
                result.extend(obj(field.value))
            elif field.kind == 1:
                result.extend(text(field.value))
            elif field.kind == 2:
                result.extend(struct.pack("<I", field.value))
            elif field.kind in (3, 4, 5, 6, 7, 10):
                result.extend(field.value)
            else:
                raise ValueError("Unsupported field type.")
        result.append(8)
        return bytes(result)
    return obj(root)


def steam_running(proc: Path = Path("/proc")) -> bool:
    for item in proc.iterdir():
        if not item.name.isdecimal():
            continue
        try:
            name = (item / "comm").read_text().strip()
            exe = Path(os.readlink(item / "exe")).name
            if name == "steam" or exe == "steam":
                return True
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return False


def _active_account(steam: Path) -> str:
    users = steam / "config/loginusers.vdf"
    if users.is_file() and not users.is_symlink():
        text = users.read_text(encoding="utf-8")
        matches = []
        # loginusers has one flat quoted block per SteamID64; tolerate escaped names.
        for match in re.finditer(r'"(\d{17})"\s*\{([^{}]*)\}', text):
            if re.search(r'"MostRecent"\s*"1"', match.group(2), flags=re.I):
                value = int(match.group(1)) - 76561197960265728
                if 0 < value < 2 ** 32:
                    matches.append(str(value))
        if len(matches) == 1:
            return matches[0]
    userdata = steam / "userdata"
    accounts = [p.name for p in userdata.iterdir()
                if p.is_dir() and not p.is_symlink() and p.name.isdecimal() and 0 < int(p.name) < 2 ** 32] if userdata.exists() else []
    if len(accounts) != 1:
        raise ValueError("Could not identify one Steam account. Add the game manually after signing in.")
    return accounts[0]


def _text_vdf(text: str) -> dict:
    tokens = []
    i = 0
    while i < len(text):
        if text[i].isspace() or text[i] == "\ufeff":
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
        elif text[i] in "{}":
            tokens.append(text[i])
            i += 1
        elif text[i] == '"':
            i += 1
            value = []
            while i < len(text) and text[i] != '"':
                if text[i] == "\\" and i + 1 < len(text):
                    i += 1
                value.append(text[i])
                i += 1
            if i >= len(text):
                raise ValueError("Steam config has an unterminated string.")
            tokens.append(("string", "".join(value)))
            i += 1
        else:
            raise ValueError("Steam config has unsupported text fields.")
    cursor = 0
    def obj(depth=0):
        nonlocal cursor
        if depth > 30:
            raise ValueError("Steam config is too deeply nested.")
        fields = {}
        while cursor < len(tokens):
            key = tokens[cursor]
            cursor += 1
            if key == "}":
                if depth == 0:
                    raise ValueError("Steam config has an unexpected closing brace.")
                return fields
            if not isinstance(key, tuple) or cursor >= len(tokens):
                raise ValueError("Steam config has invalid key/value fields.")
            value = tokens[cursor]
            cursor += 1
            if value == "{":
                value = obj(depth + 1)
            elif isinstance(value, tuple):
                value = value[1]
            else:
                raise ValueError("Steam config has an invalid value.")
            fields[key[1]] = value
        if depth:
            raise ValueError("Steam config has an unterminated object.")
        return fields
    return obj()


def _compatibility_warning(steam: Path, appid: int) -> str | None:
    config = steam / "config/config.vdf"
    if not config.exists():
        return None
    if config.is_symlink() or not config.is_file() or config.stat().st_size > 8 * 1024 * 1024:
        return "Steam's compatibility setting could not be checked. In Halo's Properties > Compatibility, leave Force the use of a specific Steam Play compatibility tool disabled."
    try:
        fields = _text_vdf(config.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "Steam's compatibility setting could not be checked. In Halo's Properties > Compatibility, leave Force the use of a specific Steam Play compatibility tool disabled."
    def find(value):
        for key, nested in value.items():
            if key.casefold() == "compattoolmapping" and isinstance(nested, dict):
                selected = nested.get(str(appid), {})
                if isinstance(selected, dict) and selected.get("name"):
                    return str(selected["name"])
            if isinstance(nested, dict):
                match = find(nested)
                if match:
                    return match
        return None
    tool = find(fields)
    if tool:
        return "The native Halo shortcut has a forced compatibility tool (" + tool + "). Open Halo's Properties > Compatibility and turn off Force the use of a specific Steam Play compatibility tool."
    return None


def _added_result(steam: Path, appid: int, **extra) -> dict:
    warning = _compatibility_warning(steam, appid)
    if warning:
        return {"status": "manual", "libraryAdded": True, "appid": appid, "name": NAME,
                "reason": warning, "instructions": warning, **extra}
    return {"status": "added", "appid": appid, "name": NAME, **extra}


def update_shortcut(data: bytes | None, executable: str, directory: str) -> tuple[bytes, int]:
    root = loads(data) if data is not None else OrderedDict([("shortcuts", Value(0, OrderedDict()))])
    if set(root) != {"shortcuts"} or root["shortcuts"].kind != 0:
        raise ValueError("Unexpected Steam shortcuts root; no changes were made.")
    shortcuts = root["shortcuts"].value
    exe = f'"{executable}"'
    start = f'"{directory}"'
    matches = []
    for index, entry in shortcuts.items():
        if entry.kind != 0:
            raise ValueError("Unexpected Steam shortcut record; no changes were made.")
        fields = entry.value
        title = fields.get("AppName", fields.get("appname"))
        path = fields.get("Exe", fields.get("exe"))
        if title and title.value == NAME:
            if path is None or str(path.value).strip('"') != executable:
                raise ValueError("A different game already uses this Steam shortcut name. Add this game manually.")
            matches.append((index, fields))
    if len(matches) > 1:
        raise ValueError("Multiple native Halo shortcuts exist. No changes were made.")
    if matches:
        _, fields = matches[0]
        app = fields.get("appid")
        if app is None or app.kind != 2 or not 2 ** 31 <= app.value < 2 ** 32:
            raise ValueError("The existing native Halo shortcut has an invalid app ID.")
        appid = app.value
    else:
        appid = zlib.crc32((exe + NAME).encode("utf-8")) | 0x80000000
        used = {entry.value.get("appid").value for entry in shortcuts.values() if entry.value.get("appid")}
        if appid in used:
            raise ValueError("Steam shortcut app ID collision. Add the game manually.")
        indices = [int(key) for key in shortcuts if key.isdecimal()]
        key = str(max(indices, default=-1) + 1)
        fields = OrderedDict()
        shortcuts[key] = Value(0, fields)
        fields["appid"] = Value(2, appid)
    # Preserve tags, artwork, playtime and all other fields on an existing entry.
    for key, value in {"AppName": NAME, "Exe": exe, "StartDir": start,
                       "LaunchOptions": LAUNCH_OPTIONS}.items():
        # Remove only an alternative case spelling of fields we are writing.
        for old in list(fields):
            if old.lower() == key.lower() and old != key:
                del fields[old]
        fields[key] = Value(1, value)
    for key in ("icon", "ShortcutPath"):
        if key not in fields:
            fields[key] = Value(1, "")
    for key, value in {"IsHidden": 0, "AllowDesktopConfig": 1, "AllowOverlay": 1,
                       "OpenVR": 1, "Devkit": 0, "DevkitOverrideAppID": 0}.items():
        fields[key] = Value(2, value)
    if "LastPlayTime" not in fields:
        fields["LastPlayTime"] = Value(2, 0)
    if "tags" not in fields:
        fields["tags"] = Value(0, OrderedDict())
    result = dumps(root)
    # Ensure the generated bytes can be parsed before writing anything.
    loads(result)
    return result, appid


def _session_environment(proc: Path = Path("/proc")) -> tuple[dict | None, bool]:
    allowed = {"DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
               "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE"}
    session = None
    game_running = False
    for item in proc.iterdir():
        if not item.name.isdecimal():
            continue
        try:
            if item.stat().st_uid != os.getuid():
                continue
            name = (item / "comm").read_text().strip()
            entries = {}
            for raw in (item / "environ").read_bytes().split(b"\0"):
                key, separator, value = raw.partition(b"=")
                if separator:
                    entries[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
            if name == "steam":
                env = dict(os.environ)
                env.update({key: entries[key] for key in allowed if key in entries})
                if "DISPLAY" in env or "WAYLAND_DISPLAY" in env:
                    session = env
            elif name != "steamwebhelper":
                appid = entries.get("SteamAppId", "0")
                if appid.isdecimal() and int(appid) not in (0, 250820):
                    game_running = True
                if Path(os.readlink(item / "exe")) == Path("/home/steamos/Games/HaloCENativeVR/halo"):
                    game_running = True
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return session, game_running


def add_native_shortcut(home: Path, game: Path, close_steam: bool = False) -> dict:
    """Optionally request Steam's normal shutdown, then restore its GUI session.

    The GUI must obtain explicit saved/closed-game acknowledgement for close_steam.
    No signals are sent to Steam, SteamVR, a game or another user's process.
    """
    import subprocess
    if not close_steam or not steam_running():
        return _write_native_shortcut(home, game)
    session, game_running = _session_environment()
    if game_running:
        return _manual(game, "A game is still running. Save and close games, then click Add to Steam again.")
    if session is None or not Path("/usr/bin/steam").is_file():
        return _manual(game, "Steam's desktop session could not be verified. Quit Steam and click Add to Steam again.")
    try:
        subprocess.run(["/usr/bin/steam", "-shutdown"], env=session,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return _manual(game, "Steam did not complete a normal shutdown. Quit it and click Add to Steam again.")
    deadline = time.monotonic() + 45
    while steam_running() and time.monotonic() < deadline:
        time.sleep(0.5)
    if steam_running():
        return _manual(game, "Steam is still running after its normal shutdown request. Its library files were left unchanged.")
    try:
        return _write_native_shortcut(home, game)
    finally:
        # Only restart a client this operation observed running and normally closed.
        subprocess.Popen(["/usr/bin/steam"], env=session, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def _manual(game: Path, reason: str | None = None) -> dict:
    manual = {"status": "manual", "name": NAME, "executable": str(game / "halo"),
              "directory": str(game), "launchOptions": LAUNCH_OPTIONS,
              "instructions": "Quit Steam and click Add to Steam again, or use Steam > Add a Game > Add a Non-Steam Game and browse to the executable. Set the displayed launch options and leave compatibility tools disabled."}
    if reason is not None:
        manual["reason"] = reason
    return manual


def _write_native_shortcut(home: Path, game: Path) -> dict:
    manual = _manual(game)
    if steam_running():
        return {**manual, "reason": "Steam is still running; its library files were left unchanged."}
    steam = home / ".local/share/Steam"
    if not steam.is_dir() or steam.resolve() != steam:
        return {**manual, "reason": "Steam's standard user-data folder was not found."}
    try:
        account = _active_account(steam)
        config = steam / "userdata" / account / "config"
        if config.is_symlink() or (config.exists() and config.resolve() != config):
            raise ValueError("Steam account config is a symbolic link; add the game manually.")
        config.mkdir(parents=True, exist_ok=True)
        path = config / "shortcuts.vdf"
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size > 8 * 1024 * 1024)):
            raise ValueError("Steam shortcuts file is not a supported ordinary file.")
        before = path.read_bytes() if path.exists() else None
        after, appid = update_shortcut(before, str(game / "halo"), str(game))
        # A second guard prevents overwriting Steam's live view if it opened during work.
        if steam_running():
            return {**manual, "reason": "Steam reopened during setup; its library files were left unchanged."}
        if (path.read_bytes() if path.exists() else None) != before:
            return {**manual, "reason": "Steam's shortcuts changed during setup; no changes were made."}
        if before == after:
            return _added_result(steam, appid, unchanged=True)
        backup = None
        if before is not None:
            backup = config / ("shortcuts.vdf.halo-frame-installer-" + str(time.time_ns()) + ".bak")
            with backup.open("xb") as stream:
                stream.write(before)
            backup.chmod(0o600)
        fd, temp = tempfile.mkstemp(prefix=".halo-shortcuts-", dir=config)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, path.stat().st_mode & 0o777 if path.exists() else 0o600)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return _added_result(steam, appid, backup=str(backup) if backup else None)
    except (OSError, ValueError, UnicodeError) as error:
        return {**manual, "reason": str(error)}
