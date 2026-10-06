"""Bounded extraction of user-supplied original Xbox Halo map caches.

No game assets are bundled or downloaded. XDVDFS offsets and directory records
are described by https://github.com/XboxDev/extract-xiso. Cache header fields
and supported retail builds come from the pinned native port's cache_files.c.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import tempfile
from typing import BinaryIO, Callable

SECTOR_SIZE = 2048
PARTITION_OFFSETS = (0, 0x0FD90000, 0x02080000, 0x18300000)
XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"
SUPPORTED_BUILDS = frozenset(("01.01.14.2342", "01.10.12.2276", "01.08.15.1749"))
REQUIRED_MAPS = tuple(sorted((
    "a10.map", "a30.map", "a50.map", "b30.map", "b40.map", "c10.map",
    "c20.map", "c40.map", "d20.map", "d40.map", "ui.map",
    "beavercreek.map", "bloodgulch.map", "boardingaction.map", "carousel.map",
    "chillout.map", "damnation.map", "hangemhigh.map", "longest.map",
    "prisoner.map", "putput.map", "ratrace.map", "sidewinder.map", "wizard.map",
)))
MAX_DIRECTORY_BYTES = 16 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 1024
MAX_MAP_BYTES = 0x11600000
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
Progress = Callable[[str, int, int], None]


class AssetError(ValueError):
    """The selected asset source is unsupported, incomplete, or malformed."""


class ExtractionCancelled(AssetError):
    """Extraction was cancelled; its staging directory has been removed."""


@dataclass(frozen=True)
class ImageInfo:
    kind: str
    build: str
    estimated_bytes: int
    map_count: int
    partition_offset: int | None = None


@dataclass(frozen=True)
class _Entry:
    name: str
    start: int
    size: int
    attributes: int


def _cancel(event) -> None:
    if event is not None and event.is_set():
        raise ExtractionCancelled("Installation cancelled while preparing game data.")


def _is_link(path: Path) -> bool:
    # Windows junctions are reparse points even when is_symlink() is false.
    data = path.lstat()
    return stat.S_ISLNK(data.st_mode) or bool(
        getattr(data, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _regular_file(path: Path) -> None:
    try:
        if _is_link(path) or not stat.S_ISREG(path.lstat().st_mode):
            raise AssetError(f"Select a regular file, not a link or device: {path.name}")
    except FileNotFoundError as exc:
        raise AssetError(f"File not found: {path.name}") from exc


def _safe_name(name: str) -> None:
    stem = name.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    reserved.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10))
    reserved.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "¹²³")
    if (not name or name in (".", "..") or name.endswith((".", " "))
            or any(ord(c) < 32 or ord(c) == 127 or c in '<>:"/\\|?*' for c in name)
            or stem in reserved):
        raise AssetError("The image contains an unsafe or non-portable filename.")


def _cache_header(header: bytes, name: str, actual_size: int) -> str:
    if len(header) != SECTOR_SIZE or not SECTOR_SIZE <= actual_size <= MAX_MAP_BYTES:
        raise AssetError(f"Invalid or truncated map: {name}")
    if header[:4] != b"daeh" or header[-4:] != b"toof":
        raise AssetError(f"{name} is not an original Xbox Halo map cache.")
    version, declared_size = struct.unpack_from("<II", header, 4)
    if version != 5:
        label = "Halo PC data" if version == 7 else f"cache version {version}"
        raise AssetError(f"{name} uses {label}. Select original Xbox Halo: Combat Evolved data.")
    # Xbox caches may be compressed: the embedded length is the uncompressed
    # length, and is intentionally not compared with the on-disc file size.
    if not SECTOR_SIZE <= declared_size <= MAX_MAP_BYTES:
        raise AssetError(f"Invalid declared cache length in {name}.")
    raw_build = header[64:96].split(b"\0", 1)[0]
    try:
        build = raw_build.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AssetError(f"Invalid retail build string in {name}.") from exc
    if build not in SUPPORTED_BUILDS:
        raise AssetError(f"Unsupported Xbox Halo build in {name}: {build!r}.")
    return build


class _XboxImage:
    def __init__(self, path: Path, cancel_event=None):
        _cancel(cancel_event)
        _regular_file(path)
        self.path = path
        self.image: BinaryIO = path.open("rb")
        self.size = os.fstat(self.image.fileno()).st_size
        self.cancel_event = cancel_event
        self.directories: list[tuple[int, int]] = []
        try:
            for partition in PARTITION_OFFSETS:
                _cancel(cancel_event)
                self.image.seek(partition + 0x10000)
                descriptor = self.image.read(SECTOR_SIZE)
                if (len(descriptor) == SECTOR_SIZE and descriptor[:20] == XBOX_MAGIC
                        and descriptor[0x7EC:0x800] == XBOX_MAGIC):
                    self.partition = partition
                    root_sector, root_size = struct.unpack_from("<II", descriptor, 20)
                    break
            else:
                raise AssetError("No original Xbox XDVDFS filesystem found. Use an original Xbox "
                                 "Halo: Combat Evolved ISO/XISO, not Halo PC or Xbox 360 Anniversary.")
            root = self.entries(root_sector, root_size)
            maps = next((entry for entry in root if entry.name.casefold() == "maps"), None)
            if maps is None or not maps.attributes & 0x10:
                raise AssetError("The image has no original Xbox Halo maps directory.")
            all_maps = self.entries(maps.start, maps.size)
            by_name = {entry.name.casefold(): entry for entry in all_maps}
            missing = set(REQUIRED_MAPS) - by_name.keys()
            if missing:
                raise AssetError("Incomplete Halo disc: missing " + ", ".join(sorted(missing)))
            self.maps = [by_name[name] for name in REQUIRED_MAPS]
            builds = set()
            ranges = []
            for entry in self.maps:
                _cancel(cancel_event)
                if entry.attributes & 0x10:
                    raise AssetError(f"Expected a map file, found a directory: {entry.name}")
                offset = self.partition + entry.start * SECTOR_SIZE
                end = offset + entry.size
                if any(offset < b and a < end for a, b in self.directories + ranges):
                    raise AssetError("Map contents overlap a directory or another map.")
                ranges.append((offset, end))
                self.image.seek(offset)
                builds.add(_cache_header(self.image.read(SECTOR_SIZE), entry.name, entry.size))
            _cancel(cancel_event)
            self.info = _info(builds, sum(entry.size for entry in self.maps), self.partition)
        except BaseException:
            self.image.close()
            raise

    def close(self) -> None:
        self.image.close()

    def entries(self, sector: int, length: int) -> list[_Entry]:
        _cancel(self.cancel_event)
        if not 0 < length <= MAX_DIRECTORY_BYTES:
            raise AssetError("Invalid Xbox directory length.")
        offset = self.partition + sector * SECTOR_SIZE
        end = offset + length
        if offset < self.partition or end > self.size:
            raise AssetError("An Xbox directory points outside the image.")
        if any(offset < b and a < end for a, b in self.directories):
            raise AssetError("Cyclic or overlapping Xbox directories.")
        self.directories.append((offset, end))
        self.image.seek(offset)
        table = self.image.read(length)
        if len(table) != length:
            raise AssetError("Truncated Xbox directory.")
        pending = [0]
        seen: set[int] = set()
        occupied: list[tuple[int, int]] = []
        names: set[str] = set()
        result = []
        while pending:
            _cancel(self.cancel_event)
            node = pending.pop()
            if node in seen or node < 0 or node + 14 > len(table):
                raise AssetError("Invalid or cyclic Xbox directory tree.")
            seen.add(node)
            if len(seen) > MAX_DIRECTORY_ENTRIES:
                raise AssetError("Xbox directory has too many entries.")
            left, right, start, count, attributes, name_length = struct.unpack_from("<HHIIBB", table, node)
            node_end = node + 14 + name_length
            if node_end > len(table) or any(node < b and a < node_end for a, b in occupied):
                raise AssetError("Overlapping or truncated Xbox directory records.")
            occupied.append((node, node_end))
            name = table[node + 14:node_end].decode("latin-1")
            _safe_name(name)
            folded = name.casefold()
            if folded in names:
                raise AssetError("Case-insensitive duplicate filenames in the Xbox image.")
            names.add(folded)
            if self.partition + start * SECTOR_SIZE + count > self.size:
                raise AssetError(f"{name} points outside the Xbox image.")
            result.append(_Entry(name, start, count, attributes))
            for child in (left, right):
                if child:
                    pending.append(child * 4)
        return result


def _info(builds: set[str], total: int, partition: int | None) -> ImageInfo:
    if len(builds) != 1:
        raise AssetError("The maps are from different Xbox Halo releases; use one complete retail disc.")
    if not 0 < total <= MAX_TOTAL_BYTES:
        raise AssetError("Game data exceeds the extraction size limit.")
    return ImageInfo("original-xbox", next(iter(builds)), total, len(REQUIRED_MAPS), partition)


def inspect_image(path: str | Path, cancel_event=None) -> ImageInfo:
    """Inspect image metadata, checking cancellation throughout validation."""
    _cancel(cancel_event)
    image = _XboxImage(Path(path), cancel_event)
    try:
        _cancel(cancel_event)
        return image.info
    finally:
        image.close()


def _maps_source(path: Path, cancel_event=None) -> tuple[Path, list[Path], ImageInfo]:
    _cancel(cancel_event)
    if not path.is_dir() or _is_link(path):
        raise AssetError("Select a real maps directory, not a link.")
    candidate = path / "maps"
    if candidate.is_dir():
        if _is_link(candidate):
            raise AssetError("The maps directory must not be a link.")
        path = candidate
    names: dict[str, Path] = {}
    for count, entry in enumerate(path.iterdir(), 1):
        _cancel(cancel_event)
        if count > MAX_DIRECTORY_ENTRIES:
            raise AssetError("The maps directory has too many entries.")
        _safe_name(entry.name)
        if _is_link(entry):
            raise AssetError(f"Links are not accepted in the maps directory: {entry.name}")
        folded = entry.name.casefold()
        if folded in names:
            raise AssetError("Case-insensitive duplicate filenames in the maps directory.")
        names[folded] = entry
    _cancel(cancel_event)
    missing = set(REQUIRED_MAPS) - names.keys()
    if missing:
        raise AssetError("Incomplete maps directory: missing " + ", ".join(sorted(missing)))
    files = [names[name] for name in REQUIRED_MAPS]
    builds, total = set(), 0
    for file in files:
        _cancel(cancel_event)
        _regular_file(file)
        with file.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            builds.add(_cache_header(source.read(SECTOR_SIZE), file.name, size))
            total += size
    _cancel(cancel_event)
    return path, files, _info(builds, total, None)


def inspect_maps(path: str | Path, cancel_event=None) -> ImageInfo:
    """Inspect extracted map headers without copying, with optional cancellation."""
    _cancel(cancel_event)
    return _maps_source(Path(path), cancel_event)[2]


def _new_staging(dest: Path) -> Path:
    dest = dest.absolute()
    parent = dest.parent
    if dest.exists() or dest.is_symlink():
        raise AssetError("The extraction destination already exists; choose a new empty location.")
    if not parent.is_dir():
        raise AssetError("The extraction destination's parent directory does not exist.")
    for component in (parent, *parent.parents):
        if _is_link(component):
            raise AssetError("Extraction destinations must not pass through links or junctions.")
    return Path(tempfile.mkdtemp(prefix=".halo-assets-", dir=parent))


def _copy_stream(source: BinaryIO, target: Path, size: int, done: int,
                 total: int, progress: Progress | None, cancel_event) -> dict:
    temporary = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    remaining = size
    header = bytearray()
    with temporary.open("xb") as output:
        while remaining:
            _cancel(cancel_event)
            chunk = source.read(min(remaining, CHUNK_BYTES))
            if not chunk:
                raise AssetError(f"Game data was truncated while copying {target.name}.")
            if len(header) < SECTOR_SIZE:
                header.extend(chunk[:SECTOR_SIZE - len(header)])
            output.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
            if progress:
                progress(f"Preparing {target.name}", done + size - remaining, total)
        output.flush()
        os.fsync(output.fileno())
    build = _cache_header(bytes(header), target.name, size)
    # Target lives only inside this operation's new private staging directory.
    temporary.rename(target)
    return {"path": "maps/" + target.name, "size": size,
            "sha256": digest.hexdigest(), "cacheVersion": 5, "build": build}


def _commit(stage: Path, dest: Path, source_name: str, info: ImageInfo, files: list[dict]) -> dict:
    manifest = {"schemaVersion": 1, "sourceImage": source_name,
                "partitionOffset": info.partition_offset, "kind": info.kind,
                "build": info.build, "files": files, "totalBytes": info.estimated_bytes}
    manifest_file = stage / "xbox-data-manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # mkdir reserves the destination without replacing even an empty directory
    # created concurrently. Every installed file is complete before publication.
    dest.mkdir(exist_ok=False)
    try:
        for child in stage.iterdir():
            child.rename(dest / child.name)
    except BaseException:
        shutil.rmtree(dest)
        raise
    return manifest


def extract_image(path: str | Path, dest: str | Path, progress: Progress | None = None,
                  cancel_event=None) -> dict:
    """Extract only 24 validated retail map files into a previously absent dest.

    Progress receives (message, bytes_prepared, total_bytes). Cancellation is a
    threading.Event-compatible object. Any failure removes this call's staging.
    """
    _cancel(cancel_event)
    image = _XboxImage(Path(path), cancel_event)
    stage = None
    try:
        dest = Path(dest).absolute()
        stage = _new_staging(dest)
        (stage / "maps").mkdir()
        files, done = [], 0
        if progress:
            progress("Preparing original Xbox game data", 0, image.info.estimated_bytes)
        for entry in image.maps:
            _cancel(cancel_event)
            image.image.seek(image.partition + entry.start * SECTOR_SIZE)
            files.append(_copy_stream(image.image, stage / "maps" / entry.name.casefold(),
                                      entry.size, done, image.info.estimated_bytes, progress, cancel_event))
            done += entry.size
        if {entry["build"] for entry in files} != {image.info.build}:
            raise AssetError("Game data changed during preparation; please select it again.")
        _cancel(cancel_event)
        return _commit(stage, dest, image.path.name, image.info, files)
    finally:
        image.close()
        if stage is not None:
            shutil.rmtree(stage)


def copy_maps(source: str | Path, dest: str | Path, progress: Progress | None = None,
              cancel_event=None) -> dict:
    """Prepare an already extracted retail maps folder using the same validation."""
    _cancel(cancel_event)
    source, source_files, info = _maps_source(Path(source), cancel_event)
    dest = Path(dest).absolute()
    stage = _new_staging(dest)
    try:
        (stage / "maps").mkdir()
        files, done = [], 0
        if progress:
            progress("Preparing original Xbox game data", 0, info.estimated_bytes)
        for file in source_files:
            _cancel(cancel_event)
            _regular_file(file)
            with file.open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                if size != file.stat().st_size:
                    raise AssetError(f"Game data changed while opening {file.name}.")
                files.append(_copy_stream(stream, stage / "maps" / file.name.casefold(),
                                          size, done, info.estimated_bytes, progress, cancel_event))
                done += size
        if done != info.estimated_bytes or {entry["build"] for entry in files} != {info.build}:
            raise AssetError("Game data changed during preparation; please select it again.")
        _cancel(cancel_event)
        return _commit(stage, dest, source.name, info, files)
    finally:
        shutil.rmtree(stage)
