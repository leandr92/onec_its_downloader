"""External ITS .pack archive: catalog + concatenated bodies."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from .paths import safe_join

HEADER_SIZE = 308
RECORD_SIZE = 284
COUNT_OFFSET = 0x130
# Catalog stores 16 zero bytes when the pack has no checksum for that file.
MISSING_MD5 = b"\x00" * 16


@dataclass
class PackEntry:
    size: int
    filetime: int
    md5: bytes
    path: str
    body_offset: int


@dataclass
class PackCatalog:
    header: bytes
    entries: list[PackEntry]
    data_start: int


class PackError(Exception):
    pass


def parse_pack_catalog(data: bytes) -> PackCatalog:
    if len(data) < HEADER_SIZE:
        raise PackError("pack too small")
    count = struct.unpack_from("<I", data, COUNT_OFFSET)[0]
    catalog_end = HEADER_SIZE + count * RECORD_SIZE
    if catalog_end > len(data):
        raise PackError("pack catalog truncated")
    entries: list[PackEntry] = []
    body = catalog_end
    for i in range(count):
        off = HEADER_SIZE + i * RECORD_SIZE
        size = struct.unpack_from("<I", data, off)[0]
        filetime = struct.unpack_from("<Q", data, off + 4)[0]
        md5 = data[off + 12 : off + 28]
        raw_path = data[off + 28 : off + 284].split(b"\0", 1)[0]
        path = raw_path.decode("cp1251", "replace")
        entries.append(
            PackEntry(size=size, filetime=filetime, md5=md5, path=path, body_offset=body)
        )
        body += size
    return PackCatalog(header=data[:HEADER_SIZE], entries=entries, data_start=catalog_end)


def build_pack(entries: list[tuple[str, bytes]], header: bytes | None = None) -> bytes:
    """Build a .pack from (path, body) pairs. MD5 is computed per body."""
    if header is None:
        header = bytearray(HEADER_SIZE)
        struct.pack_into("<I", header, 0, 1)
        struct.pack_into("<I", header, COUNT_OFFSET, len(entries))
    else:
        header = bytearray(header)
        if len(header) != HEADER_SIZE:
            raise PackError("header must be 308 bytes")
        struct.pack_into("<I", header, COUNT_OFFSET, len(entries))

    records = bytearray()
    bodies = bytearray()
    for path, body in entries:
        path_b = path.encode("cp1251", "replace")
        if len(path_b) >= 256:
            raise PackError(f"path too long: {path}")
        md5 = hashlib.md5(body).digest()
        rec = bytearray(RECORD_SIZE)
        struct.pack_into("<I", rec, 0, len(body))
        struct.pack_into("<Q", rec, 4, 0)
        rec[12:28] = md5
        rec[28 : 28 + len(path_b)] = path_b
        records.extend(rec)
        bodies.extend(body)
    return bytes(header) + bytes(records) + bytes(bodies)


def unpack_pack(
    pack_path: Path,
    dest_dir: Path,
    *,
    on_progress=None,
) -> tuple[int, list[str]]:
    """Unpack *pack_path* into *dest_dir*.

    Returns (written_count, skip_reasons). An all-zero catalog MD5 means the
    pack stored no checksum and the body is kept. A real MD5 mismatch skips
    only that file. A truncated body skips the whole pack. Paths that escape
    *dest_dir* are refused individually.
    """
    pack_path = Path(pack_path)
    dest_dir = Path(dest_dir)
    data = pack_path.read_bytes()
    catalog = parse_pack_catalog(data)
    total = len(catalog.entries)
    bodies: list[tuple[PackEntry, bytes]] = []
    reasons: list[str] = []

    for i, entry in enumerate(catalog.entries):
        if on_progress:
            on_progress(i + 1, total, entry.path)
        end = entry.body_offset + entry.size
        if end > len(data):
            return 0, [f"truncated body for {entry.path}"]
        body = data[entry.body_offset : end]
        if entry.md5 != MISSING_MD5 and hashlib.md5(body).digest() != entry.md5:
            reasons.append(f"MD5 mismatch for {entry.path}")
            continue
        bodies.append((entry, body))

    dest_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for entry, body in bodies:
        target = safe_join(dest_dir, entry.path)
        if target is None:
            reasons.append(f"path escapes destination: {entry.path}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        written += 1
    return written, reasons
