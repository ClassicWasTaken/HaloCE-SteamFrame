"""Quiet menu playback from the user's Xbox cache; no soundtrack is bundled.

Cache/tag layouts and Xbox ADPCM follow the pinned OpenCE source's
cache_files.c, sound_definitions.h and port/linux/src/dsound_sdl.c. Only the
title1/loops tag is read. Its decoded audio stays in a private temporary folder.
"""
from __future__ import annotations

from array import array
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import wave
import zlib

from .assets import _XboxImage, _cache_header, _regular_file, SECTOR_SIZE

MAX_CACHE = 128 * 1024 * 1024
MAX_TRACK = 16 * 1024 * 1024
MAX_SECONDS = 300
QUIET_GAIN = 0.12
STEP = (7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,
        50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,
        253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,
        1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,
        3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,
        10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,
        27086,29794,32767)
INDEX = (-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8)


class MusicError(ValueError):
    pass


def _cancel(event):
    if event is not None and event.is_set():
        raise MusicError('Menu music preparation cancelled.')


def _slice(data, offset, count):
    if offset < 0 or count < 0 or offset + count > len(data):
        raise MusicError('Menu sound data is outside its Xbox cache.')
    return data[offset:offset+count]


def _fields(data, offset, fmt):
    return struct.unpack(fmt, _slice(data, offset, struct.calcsize(fmt)))


def _read_cache(stream, size, cancel_event):
    parts = []
    remaining = size
    while remaining:
        _cancel(cancel_event)
        part = stream.read(min(remaining, 128 * 1024))
        if not part:
            raise MusicError('Menu cache is truncated.')
        parts.append(part)
        remaining -= len(part)
    return b''.join(parts)


def read_menu_map(source: Path, cancel_event=None) -> bytes:
    source = Path(source)
    _cancel(cancel_event)
    if source.is_dir():
        folder = source / 'maps' if (source / 'maps').is_dir() else source
        path = folder / 'ui.map'
        _regular_file(path)
        size = path.stat().st_size
        if size > MAX_CACHE:
            raise MusicError('Menu cache exceeds the music preview limit.')
        with path.open('rb') as stream:
            raw = _read_cache(stream, size, cancel_event)
    else:
        image = _XboxImage(source, cancel_event)
        try:
            entry = next(item for item in image.maps if item.name.casefold() == 'ui.map')
            if entry.size > MAX_CACHE:
                raise MusicError('Menu cache exceeds the music preview limit.')
            image.image.seek(image.partition + entry.start * SECTOR_SIZE)
            raw = _read_cache(image.image, entry.size, cancel_event)
        finally:
            image.close()
    _cache_header(raw[:SECTOR_SIZE], 'ui.map', len(raw))
    if raw[32:64].split(b'\0', 1)[0] != b'ui':
        raise MusicError('This is not the original Xbox menu cache.')
    declared = _fields(raw, 8, '<I')[0]
    if declared > MAX_CACHE:
        raise MusicError('Expanded menu cache exceeds the music preview limit.')
    _cancel(cancel_event)
    # Xbox retail disc caches are zlib streams following the uncompressed header.
    if raw[SECTOR_SIZE:SECTOR_SIZE+1] == b'\x78':
        decoder = zlib.decompressobj()
        try:
            body = decoder.decompress(raw[SECTOR_SIZE:], declared-SECTOR_SIZE+1)
        except zlib.error as exc:
            raise MusicError('Menu cache compression is invalid.') from exc
        if not decoder.eof or len(body) != declared-SECTOR_SIZE:
            raise MusicError('Menu cache decompression length is invalid.')
        result = raw[:SECTOR_SIZE] + body
    else:
        result = _slice(raw, 0, declared)
    _cancel(cancel_event)
    return result


def menu_tracks(cache: bytes) -> tuple[int, int, list[bytes]]:
    tag_offset, tag_size = _fields(cache, 16, '<II')
    _slice(cache, tag_offset, tag_size)
    header = _fields(cache, tag_offset, '<9I')
    if header[8] != 0x74616773 or not 1 <= header[3] <= 32768:
        raise MusicError('Menu tag index is invalid.')
    table = tag_offset + 36
    _slice(cache, table, header[3] * 32)
    magic = header[0] - table
    target = b'sound\\music\\title1\\loops'
    metadata = None
    for index in range(header[3]):
        entry = _fields(cache, table + index * 32, '<8I')
        if entry[0] != 0x736E6421:  # snd!
            continue
        name = entry[4] - magic
        _slice(cache, name, 1)
        end = cache.find(b'\0', name, min(len(cache), name + 256))
        if end < 0:
            raise MusicError('Menu tag name is invalid.')
        if cache[name:end].lower() == target:
            metadata = entry[5] - magic
            break
    if metadata is None:
        raise MusicError('The original Halo menu music tag was not found.')
    encoding, compression = _fields(cache, metadata+108, '<hh')
    rate = _fields(cache, metadata+6, '<h')[0]
    if encoding not in (0,1) or compression != 1 or rate not in (0,1):
        raise MusicError('Menu music uses an unsupported Xbox audio format.')
    channels, sample_rate = encoding+1, (22050,44100)[rate]
    ranges, address, _ = _fields(cache, metadata+152, '<3I')
    if ranges != 1:
        raise MusicError('Menu music has an unsupported pitch layout.')
    pitch = address-magic
    actual = _fields(cache, pitch+44, '<h')[0]
    count, address, _ = _fields(cache, pitch+60, '<3I')
    if not 1 <= actual <= count <= 256:
        raise MusicError('Menu music permutation count is invalid.')
    permutations = address-magic
    _slice(cache, permutations, count*124)
    tracks = []
    seen = set()
    total = 0
    for first in range(actual):
        pieces = []
        current = first
        while current != -1:
            if current in seen or not 0 <= current < count:
                raise MusicError('Menu music permutation chain is cyclic or invalid.')
            seen.add(current)
            perm = permutations+current*124
            kind, following = _fields(cache, perm+40, '<hh')
            size, _, offset, _, _ = _fields(cache, perm+64, '<5I')
            if kind != 1 or not 0 < size <= 4*1024*1024 or size % (36*channels):
                raise MusicError('Menu music ADPCM block is invalid.')
            total += size
            if total > MAX_TRACK:
                raise MusicError('Menu music exceeds the preview limit.')
            pieces.append(_slice(cache, offset, size))
            current = following
        tracks.append(b''.join(pieces))
    frames = total // (36*channels) * 64
    if frames > sample_rate*MAX_SECONDS:
        raise MusicError('Menu music duration exceeds the preview limit.')
    return channels, sample_rate, tracks


def decode_adpcm(source: bytes, channels: int, cancel_event=None, gain=QUIET_GAIN) -> bytes:
    if channels not in (1,2) or not 0 <= gain <= QUIET_GAIN or len(source) % (36*channels):
        raise MusicError('Invalid quiet ADPCM stream.')
    block_size = 36*channels
    samples = array('h', [0]) * (len(source)//block_size*64*channels)
    for block in range(len(source)//block_size):
        if block % 128 == 0:
            _cancel(cancel_event)
        position = block*block_size
        for channel in range(channels):
            predictor, index, _ = _fields(source, position+channel*4, '<hBB')
            if index > 88:
                raise MusicError('Invalid ADPCM predictor index.')
            for group in range(8):
                base = position+4*channels+(group*channels+channel)*4
                for byte in range(4):
                    packed = source[base+byte]
                    for half, nibble in enumerate((packed & 15, packed >> 4)):
                        step = STEP[index]
                        difference = (step >> 3) + (step >> 2 if nibble & 1 else 0) + (step >> 1 if nibble & 2 else 0) + (step if nibble & 4 else 0)
                        predictor = max(-32768, min(32767, predictor + (-difference if nibble & 8 else difference)))
                        index = max(0, min(88, index+INDEX[nibble]))
                        frame = block*64+group*8+byte*2+half
                        samples[frame*channels+channel] = int(predictor*gain)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


def prepare_menu_music(source: Path, destination: Path, cancel_event=None) -> Path:
    channels, rate, tracks = menu_tracks(read_menu_map(source, cancel_event))
    _cancel(cancel_event)
    with wave.open(str(destination), 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        for track in tracks:
            output.writeframesraw(decode_adpcm(track, channels, cancel_event))
    _cancel(cancel_event)
    return destination


class MenuMusic:
    """One quiet Windows sound, asynchronously prepared and never uploaded."""
    JOIN_SECONDS = 2

    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda text: None)
        self._lock = threading.RLock()
        self._muted = False
        self._closed = False
        self._playing = False
        self._generation = 0
        self._cancel = threading.Event()
        self._workers = []
        self._temporary = tempfile.TemporaryDirectory(prefix='halo-menu-preview-', ignore_cleanup_errors=True)
        self._track = None
        self._status = 'Choose Xbox data for menu music.'

    @property
    def muted(self):
        with self._lock:
            return self._muted

    @property
    def status(self):
        with self._lock:
            return self._status

    def _notify(self):
        if not self._closed:
            self.on_change(self.status)

    def _stop(self):
        if self._playing and sys.platform == 'win32':
            import winsound
            try:
                winsound.PlaySound(None, 0)
            except (OSError, RuntimeError):
                pass
        self._playing = False

    @staticmethod
    def _remove(path):
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Final directory cleanup retries files held by Windows.

    def _cleanup(self):
        # Called under the lock only after all workers have released their files.
        if self._closed and not self._workers:
            try:
                self._temporary.cleanup()
            except OSError:
                pass

    def _play(self):
        if self._track is not None and not self._muted and sys.platform == 'win32':
            import winsound
            winsound.PlaySound(str(self._track), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP | winsound.SND_NODEFAULT)
            self._playing = True
            self._status = 'Halo menu music · quiet'
        elif self._track is not None:
            self._status = 'Menu music muted.' if self._muted else 'Menu music requires Windows.'

    def load(self, source: Path | None):
        with self._lock:
            if self._closed:
                return
            self._cancel.set()
            self._cancel = threading.Event()
            cancel = self._cancel
            self._generation += 1
            generation = self._generation
            self._stop()
            self._remove(self._track)
            self._track = None
            self._status = 'Preparing Halo menu music…' if source else 'Choose Xbox data for menu music.'
            self._notify()
            if source is None:
                return
            def worker():
                path = Path(self._temporary.name) / f'menu-{generation}.wav'
                try:
                    prepare_menu_music(Path(source), path, cancel)
                    with self._lock:
                        if self._closed or cancel.is_set() or generation != self._generation:
                            self._remove(path)
                            return
                        self._track = path
                        self._play()
                        self._notify()
                except Exception:
                    with self._lock:
                        if self._track == path:
                            self._stop()
                            self._track = None
                        self._remove(path)
                        if not self._closed and generation == self._generation and not cancel.is_set():
                            self._status = 'Menu music unavailable; setup can continue.'
                            self._notify()
                finally:
                    with self._lock:
                        self._workers.remove(threading.current_thread())
                        self._cleanup()

            # Starting under the lock prevents close() from joining an unstarted
            # worker or removing its temporary folder before it begins.
            thread = threading.Thread(target=worker, daemon=True)
            self._workers.append(thread)
            thread.start()

    def toggle(self):
        with self._lock:
            self._muted = not self._muted
            self._stop()
            if self._track is not None:
                try:
                    self._play()
                except (OSError, RuntimeError):
                    self._status = 'Menu music unavailable; setup can continue.'
            self._notify()
            return self._muted

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel.set()
            self._stop()
            workers = list(self._workers)
        deadline = time.monotonic()+self.JOIN_SECONDS
        for thread in workers:
            thread.join(max(0, deadline-time.monotonic()))
        with self._lock:
            self._cleanup()
