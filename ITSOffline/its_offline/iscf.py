"""ISCF (1C ITS Data.cab) catalog parse and extract.

Catalog layout (empirical):
- Signature ``ISCF``
- Reserve length is a single ``u32`` at offset 36
- CFFOLDER at ``36 + 4 + reserve``
- Compression ``0x1573`` = LZX window 21
- CFDATA has no per-block reserve
- CFFILE ring: at ``coffFiles`` a leading ``size, offset, folder``, then
  repeated ``hash, type(=0x20), path\\0``, then the next record's size/offset/folder
- Encrypted payloads: XOR each CFDATA body with ``(first_u32 ^ 0x8d80805b)`` then LZX

LZX decompression is performed by the companion binary
``native/iscf_extract`` (Rust + lzxd). Build it once with cargo.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LZX_PROLOGUE = 0x8D80805B


@dataclass
class CabFolder:
    data_offset: int
    block_count: int
    compression: int


@dataclass
class CabFile:
    path: str
    size: int
    offset: int
    folder: int


class IscfError(Exception):
    pass


def parse_iscf(data: bytes) -> tuple[list[CabFolder], list[CabFile]]:
    if len(data) < 40 or data[:4] != b"ISCF":
        raise IscfError("not an ISCF container")
    coff_files = struct.unpack_from("<I", data, 16)[0]
    c_folders = struct.unpack_from("<H", data, 26)[0]
    c_files = struct.unpack_from("<H", data, 28)[0]
    reserve_len = struct.unpack_from("<I", data, 36)[0]
    folder_off = 36 + 4 + reserve_len

    folders: list[CabFolder] = []
    for i in range(c_folders):
        off = folder_off + i * 8
        folders.append(
            CabFolder(
                data_offset=struct.unpack_from("<I", data, off)[0],
                block_count=struct.unpack_from("<H", data, off + 4)[0],
                compression=struct.unpack_from("<H", data, off + 6)[0],
            )
        )

    dir_end = folders[0].data_offset if folders else len(data)
    pos = coff_files
    if pos + 10 > dir_end:
        raise IscfError("empty file directory")
    size, offset, folder = struct.unpack_from("<IIH", data, pos)
    pos += 10
    files: list[CabFile] = []
    while len(files) < c_files and pos + 6 < dir_end:
        typ = struct.unpack_from("<H", data, pos + 4)[0]
        name_start = pos + 6
        try:
            name_end = data.index(0, name_start, dir_end)
        except ValueError as exc:
            raise IscfError("truncated path in directory") from exc
        path = data[name_start:name_end].decode("cp1251", "replace")
        pos = name_end + 1
        if typ == 0x20 and folder < len(folders):
            files.append(CabFile(path=path, size=size, offset=offset, folder=folder))
        if len(files) >= c_files or pos + 10 > dir_end:
            break
        size, offset, folder = struct.unpack_from("<IIH", data, pos)
        pos += 10
    return folders, files


def detect_payload_xor_key(data: bytes, folders: list[CabFolder]) -> bytes | None:
    if not folders or folders[0].block_count == 0:
        return None
    pos = folders[0].data_offset
    if pos + 12 > len(data):
        return None
    cb_data = struct.unpack_from("<H", data, pos + 4)[0]
    if cb_data < 4 or pos + 8 + cb_data > len(data):
        return None
    magic = struct.unpack_from("<I", data, pos + 8)[0]
    if magic == LZX_PROLOGUE:
        return None
    return struct.pack("<I", magic ^ LZX_PROLOGUE)


def find_iscf_extract() -> Path | None:
    env = os.environ.get("ITSOFFLINE_ISCF_EXTRACT")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "bin" / "iscf_extract",
        here.parent / "native" / "iscf_extract" / "target" / "release" / "iscf_extract",
        here.parent / "native" / "iscf_extract" / "target" / "debug" / "iscf_extract",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def extract_iscf(cab_path: Path, out_dir: Path) -> int:
    """Extract all files from *cab_path* into *out_dir*. Returns file count."""
    cab_path = Path(cab_path)
    out_dir = Path(out_dir)
    data = cab_path.read_bytes()
    folders, files = parse_iscf(data)
    if not files:
        raise IscfError("no files in ISCF catalog")

    helper = find_iscf_extract()
    if helper is None:
        raise IscfError(
            "iscf_extract binary not found; build ITSOffline/native/iscf_extract "
            "(cargo build --release) or set ITSOFFLINE_ISCF_EXTRACT"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(helper), str(cab_path), str(out_dir)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "iscf_extract failed").strip()
        raise IscfError(msg)
    return len(files)


def build_toc(library_dir: Path) -> dict:
    """Build toc.json structure from extracted SRC tree."""
    library_dir = Path(library_dir)
    pages: list[dict] = []
    src = library_dir / "SRC"
    root = src if src.is_dir() else library_dir
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".htm", ".html"):
            continue
        rel = path.relative_to(library_dir).as_posix()
        parts = path.relative_to(root).parts
        # Parent folder of the page is the book (SRC/<...>/<book>/<chapter>.htm).
        book = parts[-2] if len(parts) >= 2 else ""
        title = path.stem
        pages.append({"path": rel, "book": book, "title": title})
    return {"pages": pages}


def write_toc(library_dir: Path) -> Path:
    toc = build_toc(library_dir)
    out = Path(library_dir) / "toc.json"
    out.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def extract_data_cab_to_library(pack_root: Path, library_dir: Path) -> Path | None:
    """Find Storage/Data.cab under *pack_root*, extract SRC into *library_dir*, write toc.

    Returns path to Data.cab or None if missing. Raises IscfError on parse/extract failure.
    """
    cab = Path(pack_root) / "Storage" / "Data.cab"
    if not cab.is_file():
        # also accept Data.cab at root
        cab = Path(pack_root) / "Data.cab"
    if not cab.is_file():
        return None
    library_dir = Path(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)
    extract_iscf(cab, library_dir)
    write_toc(library_dir)
    return cab


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python -m its_offline.iscf <Data.cab> <out_dir>", file=sys.stderr)
        return 2
    n = extract_iscf(Path(argv[0]), Path(argv[1]))
    write_toc(Path(argv[1]))
    print(f"extracted {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
