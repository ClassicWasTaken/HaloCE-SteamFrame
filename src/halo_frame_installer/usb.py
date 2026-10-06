"""USB-only ADB forwarding for the existing authenticated SSH transport.

No network profiles, device services, drivers, or shared ADB connections change.
Only this operation's dynamically allocated SSH forward is removed on close.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import uuid


class USBError(RuntimeError):
    pass


ADB_FILES = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
TOOLS_URL = "https://developer.android.com/tools/releases/platform-tools"


def bundled_adb() -> Path | None:
    root = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]) / "resources" / "usb"
    if not root.exists():
        return None
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        hashes = manifest["files"]
        if set(hashes) != set(ADB_FILES):
            raise ValueError
        version = manifest["version"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
            raise ValueError
        for name in (*ADB_FILES, "NOTICE.txt"):
            path = root / name
            if (not path.is_file() or path.is_symlink() or path.stat().st_size > 20 * 1024 * 1024
                    or hashlib.sha256(path.read_bytes()).hexdigest() !=
                    (manifest["noticeSha256"] if name == "NOTICE.txt" else hashes[name])):
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise USBError("The included USB tools are missing or damaged. Download a fresh installer, or select adb.exe in Advanced settings.") from None
    # An ADB server can outlive setup. Execute from our persistent, versioned
    # tool cache so it cannot keep PyInstaller's temporary extraction locked.
    cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "HaloFrameInstaller" / "usb-tools" / version
    try:
        for parent in (cache.parent.parent, cache.parent, cache):
            parent.mkdir(parents=True, exist_ok=True)
            data = parent.lstat()
            if parent.is_symlink() or getattr(data, "st_file_attributes", 0) & 0x400:
                raise OSError
        for name in (*ADB_FILES, "NOTICE.txt"):
            target = cache / name
            expected = manifest["noticeSha256"] if name == "NOTICE.txt" else hashes[name]
            if target.is_symlink() or (target.exists() and getattr(target.lstat(), "st_file_attributes", 0) & 0x400):
                raise OSError
            if (target.is_file() and target.stat().st_size <= 20 * 1024 * 1024
                    and hashlib.sha256(target.read_bytes()).hexdigest() == expected):
                continue
            temporary = cache / (name + "." + uuid.uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write((root / name).read_bytes())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return cache / "adb.exe"
    except OSError:
        raise USBError("Could not prepare the included USB tools. Select a working adb.exe in Advanced settings, or download a fresh installer.") from None


def resolve_adb(selected: str | None = None) -> Path:
    if selected:
        path = Path(selected).expanduser().resolve()
        if not path.is_file() or path.name.lower() not in ("adb", "adb.exe"):
            raise USBError("Select adb.exe from the Android SDK platform-tools folder.")
        return path
    if sys.platform == "win32" or getattr(sys, "frozen", False):
        # Only the hash-verified bundle is known to be the build shipped with
        # this installer. The search path (which on Windows also covers the
        # working directory) can surface an unrelated or shadowing adb.exe, so
        # it is never trusted while a verified tool is available. The bundle
        # is consulted on every platform it ships on, not just Windows.
        included = bundled_adb()
        if included:
            return included
        sdk = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        if sdk.is_file():
            return sdk
    # A client found on the search path may cooperate with another
    # application's ADB server, but its provenance is unknown: last resort.
    existing = shutil.which("adb")
    if existing:
        return Path(existing).resolve()
    raise USBError("USB tools were not found. Install Google's Android SDK Platform Tools and select adb.exe in Advanced settings.")


def _serial(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", value) or value == "unknown":
        raise USBError("ADB did not identify a USB device. Enable Developer Mode and connect the Frame with a data-capable USB cable.")
    return value


def verify_loopback_listener(port: int) -> None:
    """Inspect actual bindings: a shared ADB server may have been started -a."""
    addresses = []
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            class TCP4(ctypes.Structure):
                _fields_ = [(name, wintypes.DWORD) for name in
                            ("state", "address", "port", "remote", "remote_port", "pid")]
            class TCP6(ctypes.Structure):
                _fields_ = [("address", ctypes.c_ubyte * 16), ("scope", wintypes.DWORD),
                            ("port", wintypes.DWORD), ("remote", ctypes.c_ubyte * 16),
                            ("remote_scope", wintypes.DWORD), ("remote_port", wintypes.DWORD),
                            ("state", wintypes.DWORD), ("pid", wintypes.DWORD)]
            get_table = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
            get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                  wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
            get_table.restype = wintypes.DWORD
            for family, row_type in ((socket.AF_INET, TCP4), (socket.AF_INET6, TCP6)):
                size = wintypes.DWORD()
                result = get_table(None, ctypes.byref(size), False, family, 3, 0)
                if result not in (0, 122) or not 4 <= size.value <= 8 * 1024 * 1024:
                    raise ValueError
                table = ctypes.create_string_buffer(size.value)
                if get_table(table, ctypes.byref(size), False, family, 3, 0):
                    raise ValueError
                count = int.from_bytes(table.raw[:4], "little")
                if 4 + count * ctypes.sizeof(row_type) > size.value:
                    raise ValueError
                for index in range(count):
                    row = row_type.from_buffer_copy(table, 4 + index * ctypes.sizeof(row_type))
                    if socket.ntohs(row.port & 0xffff) == port:
                        raw = (row.address.to_bytes(4, "little") if family == socket.AF_INET
                               else bytes(row.address))
                        addresses.append(ipaddress.ip_address(raw))
        else:
            for name, width in (("tcp", 4), ("tcp6", 16)):
                path = Path("/proc/net") / name
                if not path.exists() and width == 16:
                    continue
                for line in path.read_text(encoding="ascii").splitlines()[1:]:
                    columns = line.split()
                    if len(columns) < 4 or columns[3] != "0A":
                        continue
                    address, value = columns[1].split(":")
                    if int(value, 16) == port:
                        raw = bytes.fromhex(address)
                        if sys.byteorder == "little":
                            raw = b"".join(raw[i:i + 4][::-1] for i in range(0, width, 4))
                        addresses.append(ipaddress.ip_address(raw))
    except (OSError, ValueError, AttributeError):
        raise USBError("Could not verify that the USB transfer port is private to this PC. Setup refused to send the SSH password. Use Wi-Fi / Ethernet, or check the USB tools before retrying.") from None
    if (ipaddress.ip_address("127.0.0.1") not in addresses
            or not all(address.is_loopback for address in addresses)):
        raise USBError("Another application started USB debugging with network access enabled. Setup refused to send the SSH password. Close that application's USB tools and retry, or use Wi-Fi / Ethernet.")


class USBForward:
    def __init__(self, adb_path: str | None = None, serial: str | None = None):
        self.adb = resolve_adb(adb_path)
        self.serial = _serial(serial.strip()) if serial else None
        self.port: int | None = None
        self._protocol: int | None = None

    def _check_server_version(self) -> None:
        """ADB normally kills incompatible servers; reject before it can do so."""
        if self._protocol is None:
            version = self._execute("version")
            match = re.search(r"Android Debug Bridge version 1\.0\.([0-9]+)", version)
            if not match:
                raise USBError("The selected USB tools did not report a supported ADB version.")
            self._protocol = int(match[1])
        try:
            server = socket.create_connection(("127.0.0.1", 5037), timeout=3)
        except ConnectionRefusedError:
            return  # The subsequent local ADB command can start its normal server.
        except OSError:
            raise USBError("The local USB debugging server did not respond. Check other USB debugging applications, then retry.") from None
        try:
            with server:
                server.settimeout(3)
                server.sendall(b"000chost:version")
                def receive(count):
                    data = bytearray()
                    while len(data) < count:
                        part = server.recv(count - len(data))
                        if not part:
                            raise ValueError
                        data.extend(part)
                    return bytes(data)
                if receive(4) != b"OKAY":
                    raise ValueError
                length = int(receive(4), 16)
                if not 1 <= length <= 8:
                    raise ValueError
                protocol = int(receive(length), 16)
        except (OSError, ValueError):
            raise USBError("The local USB debugging server returned an unexpected response. Setup left it unchanged.") from None
        if protocol != self._protocol:
            raise USBError("Another application is using a different ADB server version. Setup left it running. Select matching adb.exe in Advanced settings, or close that application's USB tools before retrying.")

    def _run(self, *args: str) -> str:
        self._check_server_version()
        return self._execute(*args)

    def _execute(self, *args: str) -> str:
        env = os.environ.copy()
        for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_PORT", "ADB_SERVER_PORT", "ANDROID_SERIAL"):
            env.pop(name, None)
        # ADB treats the literal localhost as local and may auto-start a missing
        # server. 127.0.0.1 is classified as remote by some clients and cannot.
        command = [str(self.adb), "-H", "localhost", "-P", "5037", *args]
        try:
            result = subprocess.run(command, shell=False, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20, env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise USBError("USB detection timed out. Check the data cable, Developer Mode and any USB authorization prompt on the Frame, then retry.") from None
        except OSError:
            raise USBError("Could not start the USB tools. Select a working adb.exe in Advanced settings.") from None
        if result.returncode:
            diagnostic = (result.stderr + result.stdout).lower()
            if "unauthorized" in diagnostic:
                message = "Approve the USB debugging connection on the Frame, then click Test connection again."
            elif "more than one" in diagnostic:
                message = "More than one USB debugging device is connected. Unplug the other devices, or enter your Frame's USB serial in Advanced settings."
            elif "offline" in diagnostic:
                message = "The USB device is offline. Wake the Frame, check the cable and approve USB debugging if prompted, then retry."
            else:
                message = "Could not reach the Frame over USB. Enable Developer Mode, use a data-capable cable and approve USB debugging if prompted. If Windows cannot detect the device, check the official USB setup guide."
            # Do not expose arbitrary subprocess output or environment values.
            raise USBError(message)
        if len(result.stdout) > 65536:
            raise USBError("The USB tools returned an unexpected response.")
        return result.stdout.strip()

    def open(self) -> tuple[str, int]:
        if self.port is not None:
            raise USBError("This USB transfer connection is already open.")
        if self.serial is None:
            # -d selects physical USB transports; Wi-Fi ADB and Lepton emulators
            # can remain attached to the shared server without being selected.
            self.serial = _serial(self._run("-d", "get-serialno"))
        else:
            # Never let an explicitly selected TCP/Lepton endpoint masquerade as
            # wired transfer. Some backends omit the path: fail with guidance.
            devpath = self._run("-s", self.serial, "get-devpath")
            if not devpath.startswith("usb:"):
                raise USBError("The selected device could not be verified as a physical USB connection. Unplug other USB debugging devices and leave the USB serial field blank to detect the Frame automatically.")
        value = self._run("-s", self.serial, "forward", "--no-rebind", "tcp:0", "tcp:22")
        if not re.fullmatch(r"[0-9]{1,5}", value) or not 1 <= int(value) <= 65535:
            raise USBError("The USB tools did not return a valid transfer port. Update Android SDK Platform Tools and retry.")
        self.port = int(value)
        try:
            if self._forward_state() != "owned":
                raise USBError("The USB transfer connection could not be verified.")
            # ADB's CLI rejects hostname-qualified forward arguments. Inspect
            # both OS socket tables before using its standard dynamic TCP port.
            verify_loopback_listener(self.port)
        except Exception:
            try:
                self.close()
            except USBError:
                pass
            raise
        return self.serial, self.port

    def _forward_state(self) -> str:
        rows = [line.split() for line in self._run("forward", "--list").splitlines()]
        selected = [row for row in rows if len(row) == 3 and row[1] == f"tcp:{self.port}"]
        if not selected:
            return "absent"
        return "owned" if selected == [[self.serial, f"tcp:{self.port}", "tcp:22"]] else "foreign"

    def close(self) -> None:
        if self.port is None:
            return
        state = self._forward_state()
        if state == "foreign":
            raise USBError("The USB transfer port changed ownership. Setup left the other application's connection unchanged; unplug the cable to end the USB connection.")
        if state == "owned":
            self._run("-s", self.serial, "forward", "--remove", f"tcp:{self.port}")
            if self._forward_state() != "absent":
                raise USBError("SSH has closed, but the temporary USB forward could not be removed. Unplug the cable to end the USB connection.")
        self.port = None
