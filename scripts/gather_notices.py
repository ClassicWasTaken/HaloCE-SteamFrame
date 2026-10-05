#!/usr/bin/env python3
"""Copy installed dependency notices and source metadata into release resources.

Run with the same Python environment that freezes the installer. No local paths,
environment values, credentials, game files or game binaries are exported.
Only --download-sources enables the primary-source network fetches below.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slug(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]", "-", name)
    if value in {"", ".", ".."}:
        raise ValueError("Invalid distribution name")
    return value


def notice_name(path: PurePosixPath) -> bool:
    name = path.name.lower()
    return name.startswith(("license", "copying", "copyright", "notice", "authors")) and path.suffix.lower() in {"", ".txt", ".md", ".terms", ".apache", ".bsd"}


def write_notice(output: Path, relative: str, data: bytes, source: str | None = None) -> dict:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe notice destination")
    target = output.joinpath(*path.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    result = {"path": path.as_posix(), "sha256": digest(data), "bytes": len(data)}
    if source is not None:
        result["source"] = source
    return result


def get_https(url: str, limit: int = 32 * 1024 * 1024) -> bytes:
    allowed = {"pypi.org", "files.pythonhosted.org", "raw.githubusercontent.com"}
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password:
        raise ValueError("Unsupported notice/source URL")
    request = Request(url, headers={"User-Agent": "halo-steam-frame-installer-notices/1"})
    with urlopen(request, timeout=30) as response:
        final = urlparse(response.url)
        if final.scheme != "https" or final.hostname not in allowed:
            raise ValueError("Unsupported source redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Source archive exceeds limit")
    return data


def installed_notices(output: Path) -> list[dict]:
    result = []
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        entry = {
            "name": name,
            "version": distribution.version,
            "license_expression": distribution.metadata.get("License-Expression"),
            "declared_license": distribution.metadata.get("License"),
            "project_urls": distribution.metadata.get_all("Project-URL") or [],
            "notices": [],
        }
        for record in sorted(distribution.files or [], key=str):
            path = PurePosixPath(str(record).replace("\\", "/"))
            if ".." in path.parts or not notice_name(path):
                continue
            source = Path(distribution.locate_file(record))
            if source.is_file():
                entry["notices"].append(write_notice(output, f"packages/{slug(name)}/{path.as_posix()}", source.read_bytes()))
        if entry["notices"]:
            result.append(entry)
        elif name.lower() in {"paramiko", "cryptography", "bcrypt", "pynacl", "pyinstaller", "cffi"}:
            raise RuntimeError(f"Installed {name} has no original license notice")
    return result


def python_notices(output: Path) -> list[dict]:
    base = Path(sys.base_prefix)
    license_file = base / "LICENSE.txt"
    if not license_file.is_file():
        license_file = base / "LICENSE"
    if not license_file.is_file():
        raise RuntimeError("Python runtime LICENSE is missing; supply a licensed Python distribution")
    notices = [write_notice(output, "runtime/Python-LICENSE.txt", license_file.read_bytes())]
    tcl_root = base / "tcl"
    if tcl_root.is_dir():
        for candidate in sorted(tcl_root.rglob("license.terms")):
            if "demos" not in candidate.relative_to(tcl_root).parts:
                notices.append(write_notice(output, "runtime/tcl-tk/" + candidate.relative_to(tcl_root).as_posix(), candidate.read_bytes()))
    return notices


def download_sources(output: Path, entries: list[dict]) -> list[dict]:
    paramiko = next((p for p in entries if p["name"].lower() == "paramiko"), None)
    if not paramiko:
        raise RuntimeError("Paramiko is not installed in the build environment")
    api = f"https://pypi.org/pypi/paramiko/{paramiko['version']}/json"
    info = json.loads(get_https(api, 4 * 1024 * 1024))
    files = [p for p in info["urls"] if p["packagetype"] == "sdist"]
    if len(files) != 1:
        raise RuntimeError("Expected one official Paramiko source archive")
    archive = files[0]
    filename = archive["filename"]
    if PurePosixPath(filename).name != filename or not filename.endswith(".tar.gz"):
        raise ValueError("Unsafe Paramiko archive filename")
    data = get_https(archive["url"])
    if digest(data) != archive["digests"]["sha256"]:
        raise RuntimeError("Paramiko source checksum mismatch")
    notices = [write_notice(output, "sources/" + filename, data, archive["url"])]
    notices[0]["metadata_source"] = api
    # cryptography statically links its own OpenSSL; Python ssl may use another.
    import ssl
    from cryptography.hazmat.backends.openssl.backend import backend

    versions = {ssl.OPENSSL_VERSION, backend.openssl_version_text()}
    for description in sorted(versions):
        match = re.match(r"OpenSSL (\d+\.\d+\.\d+)\b", description)
        if not match:
            raise RuntimeError("Cannot determine bundled OpenSSL version")
        version = match.group(1)
        url = f"https://raw.githubusercontent.com/openssl/openssl/openssl-{version}/LICENSE.txt"
        notices.append(write_notice(output, f"runtime/openssl-{version}-LICENSE.txt", get_https(url, 1024 * 1024), url))
    import tkinter

    version = str(tkinter.Tcl().call("info", "patchlevel"))
    tag = "core-" + version.replace(".", "-")
    url = f"https://raw.githubusercontent.com/tcltk/tcl/{tag}/license.terms"
    notices.append(write_notice(output, "runtime/tcl-LICENSE.terms", get_https(url, 1024 * 1024), url))
    return notices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "resources" / "licenses")
    parser.add_argument("--download-sources", action="store_true", help="Include checksum-verified Paramiko source and exact OpenSSL/Tcl license notices")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    entries = installed_notices(output)
    notices = python_notices(output)
    sources = download_sources(output, entries) if args.download_sources else []
    manifest = {
        "schema": 1,
        "python_version": platform.python_version(),
        "scope": "Installed build-environment notices; includes build/test packages that may not be present in the frozen installer.",
        "packages": entries,
        "runtime_notices": notices,
        "additional_sources_and_notices": sources,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Collected notices for {len(entries)} packages; Python {manifest['python_version']}; {len(sources)} additional source/notice files.")


if __name__ == "__main__":
    main()
