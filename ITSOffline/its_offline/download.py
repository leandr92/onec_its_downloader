"""Download ITS offline packs, unpack, extract ISCF into library/."""

from __future__ import annotations

import shutil
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import iscf, pack
from .manifest import (
    DEFAULT_MANIFEST_URL,
    Database,
    Manifest,
    filter_databases,
    parse_manifest_xml,
    resolve_kit_codes,
)
from .progress import Progress, format_bytes


def _move_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dest / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(child), str(target))


def fetch_bytes(url: str, *, dest: Path | None = None, expected_size: int | None = None, progress=None) -> bytes | None:
    """GET *url*. If *dest* is set, stream to file (resume by size) and return None."""
    ctx = ssl.create_default_context()
    headers = {"User-Agent": "ITSOffline/0.1"}
    if dest is not None:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        existing = dest.stat().st_size if dest.is_file() else 0
        if expected_size is not None and existing == expected_size and expected_size > 0:
            if progress:
                progress(existing, expected_size, done=True)
            return None
        if expected_size is None and existing > 0:
            if progress:
                progress(existing, existing, done=True)
            return None
        start = existing
        if expected_size is not None and existing > expected_size:
            dest.unlink()
            start = 0
        req_headers = dict(headers)
        if start > 0:
            req_headers["Range"] = f"bytes={start}-"
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
                mode = "ab" if start > 0 and resp.status == 206 else "wb"
                if mode == "wb":
                    start = 0
                total = expected_size
                if total is None:
                    cl = resp.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        total = start + int(cl)
                written = start
                with dest.open(mode) as out:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        written += len(chunk)
                        if progress:
                            progress(written, total)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and expected_size and dest.is_file() and dest.stat().st_size == expected_size:
                return None
            raise
        if expected_size is not None and dest.stat().st_size != expected_size:
            # leave partial for resume next time
            raise IOError(
                f"incomplete download {dest.name}: {dest.stat().st_size}/{expected_size}"
            )
        return None

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        return resp.read()


def load_manifest(url: str = DEFAULT_MANIFEST_URL) -> Manifest:
    raw = fetch_bytes(url)
    assert raw is not None
    # latest.xml is windows-1251
    text = raw.decode("cp1251", "replace")
    return parse_manifest_xml(text)


def _probe_size(url: str) -> int | None:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ITSOffline/0.1"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
    except Exception:
        return None
    return None


def download_databases(
    databases: list[Database],
    out_dir: Path,
    *,
    base: str,
    progress: Progress | None = None,
) -> int:
    """Download and unpack selected databases. Returns number fully ready."""
    out_dir = Path(out_dir)
    packs_dir = out_dir / "packs"
    library_dir = out_dir / "library"
    packs_dir.mkdir(parents=True, exist_ok=True)
    library_dir.mkdir(parents=True, exist_ok=True)
    prog = progress or Progress()
    ready = 0
    total = len(databases)

    for idx, db in enumerate(databases):
        overall = f"[{idx}/{total}] готово {ready}  текущая: {db.name}"
        prog.update(overall, "подготовка")
        url = db.url(base)
        pack_name = db.pack_filename()
        pack_path = packs_dir / pack_name
        expected = db.size
        if expected is None and not pack_path.is_file():
            expected = _probe_size(url)

        def on_dl(written, total_b, done=False, _overall=overall, _name=pack_name):
            if total_b:
                detail = f"скачивание {_name} {format_bytes(written)}/{format_bytes(total_b)}"
            else:
                detail = f"скачивание {_name} {format_bytes(written)}"
            if done:
                detail = f"есть {_name}"
            prog.update(_overall, detail)

        try:
            fetch_bytes(url, dest=pack_path, expected_size=expected, progress=on_dl)
        except Exception as exc:
            print(f"\nошибка скачивания {db.name}: {exc}", file=sys.stderr)
            continue

        unpack_root = library_dir / db.name
        # temporary unpack of full pack tree then promote SRC
        tmp_root = out_dir / "_tmp_unpack" / db.name
        if tmp_root.exists():
            shutil.rmtree(tmp_root)
        tmp_root.mkdir(parents=True, exist_ok=True)

        def on_un(i, n, path, _overall=overall):
            prog.update(_overall, f"распаковка {i}/{n} {path}")

        written, reasons = pack.unpack_pack(pack_path, tmp_root, on_progress=on_un)
        if any("truncated body" in r for r in reasons) or written == 0:
            print(f"\nпропуск пакета {pack_name}: {reasons[0] if reasons else 'пусто'}", file=sys.stderr)
            shutil.rmtree(tmp_root, ignore_errors=True)
            continue
        for r in reasons:
            print(f"\nпредупреждение {pack_name}: {r}", file=sys.stderr)

        unpack_root.mkdir(parents=True, exist_ok=True)
        try:
            cab = iscf.extract_data_cab_to_library(tmp_root, unpack_root)
            if cab is None:
                _move_tree(tmp_root, unpack_root)
                iscf.write_toc(unpack_root)
                print(
                    f"\n{db.name}: нет Storage/Data.cab — оставлена распаковка пакета",
                    file=sys.stderr,
                )
        except iscf.IscfError as exc:
            print(f"\n{db.name}: ISCF не прочитан ({exc}) — оставляю .pack и распаковку", file=sys.stderr)
            _move_tree(tmp_root, unpack_root)
            iscf.write_toc(unpack_root)
        finally:
            if tmp_root.exists():
                shutil.rmtree(tmp_root, ignore_errors=True)

        ready += 1
        prog.update(f"[{idx + 1}/{total}] готово {ready}  текущая: {db.name}", "готово")

    prog.finish(f"готово баз: {ready}/{total}")
    return ready


def run_download(
    out_dir: Path,
    *,
    all_kits: bool = False,
    kits: list[str] | None = None,
    database: str | None = None,
    manifest_url: str = DEFAULT_MANIFEST_URL,
) -> int:
    manifest = load_manifest(manifest_url)
    kit_codes = resolve_kit_codes(kits) if kits else None
    selected = filter_databases(
        manifest.databases,
        all_kits=all_kits,
        kit_codes=kit_codes,
        database_name=database,
    )
    if not selected:
        print("нет баз для выбранных режимов", file=sys.stderr)
        return 1
    print(f"пакетов к загрузке: {len(selected)}")
    download_databases(selected, out_dir, base=manifest.base)
    return 0
