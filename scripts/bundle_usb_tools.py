"""Bundle only pinned open-source ADB components and their unmodified notices."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "37.0.1"
URL = "https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip"
ARCHIVE_SHA256 = "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99"
FILES = {
    "adb.exe": "b4a6b455702684652cccf7b46258b29e653538904359a58fd4931cf3ef286b3f",
    "AdbWinApi.dll": "c1d653030b4bde65d3e07e4d0b0979e17be56df1436cdd15528630f27808050d",
    "AdbWinUsbApi.dll": "0710e894d9b40f71a670c13c694079d564c92c1279da382cfe4850983aaebe1b",
    "NOTICE.txt": "38ec8c6f5b7799c223ffeab1f9e81c2d5fc67b5e56d6424f649630ca1ee1a811",
}


def prepare(payload: bytes, output: Path) -> dict:
    if hashlib.sha256(payload).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("The official USB tools archive checksum did not match.")
    selected = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name, expected in FILES.items():
            member = archive.getinfo("platform-tools/" + name)
            if member.file_size > 20 * 1024 * 1024:
                raise RuntimeError("Unexpected USB component size.")
            data = archive.read(member)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError("USB component checksum did not match: " + name)
            selected[name] = data
    # Extract an explicit allowlist only, never execute archive contents here.
    output.mkdir(parents=True, exist_ok=True)
    for name, data in selected.items():
        (output / name).write_bytes(data)
    manifest = {"version": VERSION, "sourceUrl": URL, "archiveSha256": ARCHIVE_SHA256,
                "files": {name: digest for name, digest in FILES.items() if name != "NOTICE.txt"},
                "noticeSha256": FILES["NOTICE.txt"],
                "sourceReferences": [
                    "https://android.googlesource.com/platform/packages/modules/adb/+/1cf2f017d312f73b3dc53bda85ef2610e35a80e9/NOTICE",
                    "https://android.googlesource.com/platform/development/+/88f7870b2c652922dc2afb01c076737e8bc50130/host/windows/usb/api/AdbWinApi.cpp",
                    "https://android.googlesource.com/platform/development/+/88f7870b2c652922dc2afb01c076737e8bc50130/host/windows/usb/winusb/AdbWinUsbApi.cpp"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Optional cached official ZIP; same checksum required")
    args = parser.parse_args()
    if args.archive:
        payload = args.archive.read_bytes()
    else:
        with urlopen(Request(URL, headers={"User-Agent": "HaloFrameInstaller-build/1.3"}), timeout=45) as response:
            if response.url != URL:
                raise RuntimeError("Unexpected USB tools download redirect.")
            payload = response.read(20 * 1024 * 1024 + 1)
        if len(payload) > 20 * 1024 * 1024:
            raise RuntimeError("USB tools archive exceeds size limit.")
    manifest = prepare(payload, ROOT / "resources" / "usb")
    print(json.dumps({"usbToolsVersion": VERSION, "components": list(manifest["files"]), "archiveSha256": ARCHIVE_SHA256}))


if __name__ == "__main__":
    main()
