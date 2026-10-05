"""Synthetic filesystem/cache metadata only: these fixtures contain no game data."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from halo_frame_installer import assets


def cache_header(build="01.10.12.2276", version=5):
    data = bytearray(2048)
    data[:4] = b"daeh"
    # Deliberately larger than the on-disc file to exercise compressed caches.
    struct.pack_into("<II", data, 4, version, 4096)
    data[32:36] = b"test"
    encoded = build.encode("ascii")
    data[64:64 + len(encoded)] = encoded
    data[-4:] = b"toof"
    return bytes(data)


def directory(records):
    """Produce a legal right-linked XDVDFS tree with padded 4-byte nodes."""
    result = bytearray()
    offsets = []
    for name, start, size, attributes in records:
        encoded = name.encode("latin-1")
        offsets.append(len(result))
        result.extend(struct.pack("<HHIIBB", 0, 0, start, size, attributes, len(encoded)))
        result.extend(encoded)
        result.extend(b"\0" * (-len(result) % 4))
    for index, offset in enumerate(offsets[:-1]):
        struct.pack_into("<H", result, offset + 2, offsets[index + 1] // 4)
    return result


def make_image(path, names=None, partition=0, version=5, build="01.10.12.2276"):
    names = list(assets.REQUIRED_MAPS) if names is None else names
    map_table = directory([(name, 50 + index, 2048, 0x20) for index, name in enumerate(names)])
    root_table = directory([("maps", 40, len(map_table), 0x10), ("default.xbe", 90, 16, 0x20)])
    descriptor = bytearray(2048)
    descriptor[:20] = assets.XBOX_MAGIC
    descriptor[0x7EC:0x800] = assets.XBOX_MAGIC
    struct.pack_into("<II", descriptor, 20, 36, len(root_table))
    with path.open("wb") as image:
        image.seek(partition + 100 * 2048 - 1)
        image.write(b"\0")
        for offset, data in ((0x10000, descriptor), (36 * 2048, root_table),
                             (40 * 2048, map_table)):
            image.seek(partition + offset)
            image.write(data)
        for index in range(len(names)):
            image.seek(partition + (50 + index) * 2048)
            image.write(cache_header(build, version))
        image.seek(partition + 90 * 2048)
        image.write(b"FAKE EXECUTABLE!")
    return path


def change(path, offset, data):
    with path.open("r+b") as stream:
        stream.seek(offset)
        stream.write(data)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.image = make_image(self.root / "synthetic.iso")

    def tearDown(self):
        self.directory.cleanup()

    def test_extracts_only_required_maps_and_hashes_every_file(self):
        progress = []
        info = assets.inspect_image(self.image)
        self.assertEqual((info.kind, info.map_count, info.estimated_bytes),
                         ("original-xbox", 24, 24 * 2048))
        dest = self.root / "prepared"
        manifest = assets.extract_image(self.image, dest, lambda *args: progress.append(args))
        self.assertEqual(set(p.name for p in (dest / "maps").iterdir()), set(assets.REQUIRED_MAPS))
        self.assertFalse((dest / "default.xbe").exists())
        self.assertEqual(manifest, json.loads((dest / "xbox-data-manifest.json").read_text()))
        for entry in manifest["files"]:
            self.assertEqual(entry["sha256"], hashlib.sha256((dest / entry["path"]).read_bytes()).hexdigest())
            self.assertEqual(entry["cacheVersion"], 5)
        self.assertEqual(progress[-1][1:], (24 * 2048, 24 * 2048))
        self.assertFalse(list(self.root.glob(".halo-assets-*")))

    def test_nonzero_partition_offset(self):
        # Use the actual 34 MiB partition offset; no copyrighted contents.
        path = make_image(self.root / "partitioned.iso", partition=0x02080000)
        self.assertEqual(assets.inspect_image(path).partition_offset, 0x02080000)

    def test_all_upstream_supported_retail_regions(self):
        for build in assets.SUPPORTED_BUILDS:
            with self.subTest(build=build):
                make_image(self.image, build=build)
                self.assertEqual(assets.inspect_image(self.image).build, build)

    def test_rejects_pc_cache_and_unknown_build(self):
        make_image(self.image, version=7)
        with self.assertRaisesRegex(assets.AssetError, "Halo PC"):
            assets.inspect_image(self.image)
        make_image(self.image, build="09.99.fake")
        with self.assertRaisesRegex(assets.AssetError, "Unsupported Xbox"):
            assets.inspect_image(self.image)

    def test_rejects_missing_campaign_or_multiplayer_map(self):
        for missing in ("a10.map", "ui.map", "bloodgulch.map"):
            with self.subTest(missing=missing):
                make_image(self.image, names=[name for name in assets.REQUIRED_MAPS if name != missing])
                with self.assertRaisesRegex(assets.AssetError, missing):
                    assets.inspect_image(self.image)

    def test_rejects_invalid_filesystem_descriptor(self):
        change(self.image, 0x107EC, b"x")
        with self.assertRaisesRegex(assets.AssetError, "original Xbox XDVDFS"):
            assets.inspect_image(self.image)

    def test_rejects_truncated_header_and_bad_footer(self):
        change(self.image, 50 * 2048 + 2044, b"bad!")
        with self.assertRaisesRegex(assets.AssetError, "not an original Xbox"):
            assets.inspect_image(self.image)
        make_image(self.image)
        change(self.image, 40 * 2048 + 8, struct.pack("<I", 1024))
        with self.assertRaisesRegex(assets.AssetError, "truncated map"):
            assets.inspect_image(self.image)

    def test_rejects_unsafe_image_names(self):
        for bad in ("../a10.map", "a/b.map", "C:bad.map", "CON.map", "nul.txt", "end.", "end "):
            with self.subTest(bad=bad):
                make_image(self.image, names=[*assets.REQUIRED_MAPS, bad])
                with self.assertRaisesRegex(assets.AssetError, "unsafe"):
                    assets.inspect_image(self.image)

    def test_rejects_case_duplicates(self):
        make_image(self.image, names=[*assets.REQUIRED_MAPS, "A10.MAP"])
        with self.assertRaisesRegex(assets.AssetError, "duplicate"):
            assets.inspect_image(self.image)

    def test_rejects_node_cycle_and_out_of_bounds_child(self):
        # First maps node is padded to 24 bytes. Its successor points to itself.
        change(self.image, 40 * 2048 + 24 + 2, struct.pack("<H", 24 // 4))
        with self.assertRaisesRegex(assets.AssetError, "cyclic"):
            assets.inspect_image(self.image)
        make_image(self.image)
        change(self.image, 40 * 2048 + 2, struct.pack("<H", 0xFFFF))
        with self.assertRaisesRegex(assets.AssetError, "directory tree"):
            assets.inspect_image(self.image)

    def test_rejects_overlap_between_directory_records(self):
        change(self.image, 40 * 2048 + 2, struct.pack("<H", 1))
        with self.assertRaises(assets.AssetError):
            assets.inspect_image(self.image)

    def test_rejects_recursive_directory_sector_and_oversized_table(self):
        # Root maps entry points back at the root table.
        change(self.image, 36 * 2048 + 4, struct.pack("<I", 36))
        with self.assertRaisesRegex(assets.AssetError, "overlapping Xbox directories"):
            assets.inspect_image(self.image)
        make_image(self.image)
        change(self.image, 0x10000 + 24, struct.pack("<I", assets.MAX_DIRECTORY_BYTES + 1))
        with self.assertRaisesRegex(assets.AssetError, "directory length"):
            assets.inspect_image(self.image)

    def test_rejects_file_extent_outside_image_or_aliasing_another_map(self):
        change(self.image, 40 * 2048 + 4, struct.pack("<I", 10000))
        with self.assertRaisesRegex(assets.AssetError, "outside"):
            assets.inspect_image(self.image)
        make_image(self.image)
        change(self.image, 40 * 2048 + 24 + 4, struct.pack("<I", 50))
        with self.assertRaisesRegex(assets.AssetError, "overlap"):
            assets.inspect_image(self.image)

    def test_existing_destination_is_never_modified(self):
        dest = self.root / "existing"
        dest.mkdir()
        sentinel = dest / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(assets.AssetError, "already exists"):
            assets.extract_image(self.image, dest)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_cancellation_removes_partial_extraction(self):
        event = threading.Event()
        def progress(message, current, total):
            if current:
                event.set()
        dest = self.root / "cancelled"
        with self.assertRaises(assets.ExtractionCancelled):
            assets.extract_image(self.image, dest, progress, event)
        self.assertFalse(dest.exists())
        self.assertFalse(list(self.root.glob(".halo-assets-*")))

    def test_write_error_removes_owned_staging_and_does_not_publish(self):
        dest = self.root / "failed"
        with patch.object(assets.os, "fsync", side_effect=OSError("synthetic disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                assets.extract_image(self.image, dest)
        self.assertFalse(dest.exists())
        self.assertFalse(list(self.root.glob(".halo-assets-*")))

    def test_maps_folder_copy_and_validation(self):
        first = self.root / "source"
        assets.extract_image(self.image, first)
        info = assets.inspect_maps(first)
        self.assertEqual(info.partition_offset, None)
        second = self.root / "copy"
        manifest = assets.copy_maps(first / "maps", second)
        self.assertEqual(manifest["totalBytes"], info.estimated_bytes)
        self.assertEqual(len(manifest["files"]), 24)
        (first / "maps" / "a10.map").unlink()
        with self.assertRaisesRegex(assets.AssetError, "a10.map"):
            assets.copy_maps(first, self.root / "incomplete")

    def test_map_directory_links_are_rejected(self):
        first = self.root / "source"
        assets.extract_image(self.image, first)
        link = first / "maps" / "extra.map"
        try:
            link.symlink_to(first / "maps" / "ui.map")
        except (OSError, NotImplementedError):
            self.skipTest("Host cannot create unprivileged symlinks")
        with self.assertRaisesRegex(assets.AssetError, "Links are not accepted"):
            assets.copy_maps(first, self.root / "linked")

    def test_extract_does_not_publish_when_destination_appears_concurrently(self):
        dest = self.root / "raced"
        def progress(message, current, total):
            if current == total:
                dest.mkdir()
                (dest / "keep.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            assets.extract_image(self.image, dest, progress)
        self.assertEqual((dest / "keep.txt").read_text(), "keep")
        self.assertFalse((dest / "maps").exists())
        self.assertFalse(list(self.root.glob(".halo-assets-*")))


if __name__ == "__main__":
    unittest.main()
