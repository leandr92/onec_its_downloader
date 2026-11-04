"""Command-line interface: download / serve."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .manifest import KIT_CODES, KIT_LABELS


def _default_data() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def _prompt_menu() -> tuple[bool, list[str] | None]:
    print("ITSOffline — выбор комплекта")
    print("1. Скачать всё")
    print("2. Выбор режимов")
    names = list(KIT_CODES.keys())
    for i, name in enumerate(names, start=1):
        print(f"   {i}. {KIT_LABELS[name]} ({name}, код {KIT_CODES[name]})")
    print()
    try:
        choice = input("Введите 1 или 2: ").strip()
    except EOFError:
        print("нет ввода", file=sys.stderr)
        raise SystemExit(2)
    if choice == "1":
        return True, None
    if choice != "2":
        print("нужно 1 или 2", file=sys.stderr)
        raise SystemExit(2)
    try:
        raw = input(
            "Номера режимов через запятую (например 1,2): "
        ).strip()
    except EOFError:
        print("нет ввода", file=sys.stderr)
        raise SystemExit(2)
    kits: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            print(f"не номер: {part}", file=sys.stderr)
            raise SystemExit(2)
        idx = int(part)
        if idx < 1 or idx > len(names):
            print(f"вне диапазона: {idx}", file=sys.stderr)
            raise SystemExit(2)
        kits.append(names[idx - 1])
    if not kits:
        print("не выбран ни один режим", file=sys.stderr)
        raise SystemExit(2)
    return False, kits


def cmd_download(args: argparse.Namespace) -> int:
    from . import download

    if args.all and args.kit:
        print("--all вместе с --kit запрещены", file=sys.stderr)
        return 2

    all_kits = bool(args.all)
    kits = [k.strip() for k in args.kit.split(",") if k.strip()] if args.kit else None

    if not all_kits and not kits:
        if not sys.stdin.isatty():
            print("нужен --all или --kit (меню только в терминале)", file=sys.stderr)
            return 2
        all_kits, kits = _prompt_menu()

    return download.run_download(
        Path(args.out),
        all_kits=all_kits,
        kits=kits,
        database=args.database,
        manifest_url=args.manifest,
    )


def cmd_serve(args: argparse.Namespace) -> int:
    from . import serve

    serve.serve(Path(args.data), port=args.port, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="its_offline", description="Загрузчик и просмотрщик ИТС Offline")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("download", help="скачать базы ИТС Offline")
    d.add_argument("--all", action="store_true", help="все базы из манифеста")
    d.add_argument(
        "--kit",
        help="комплекты через запятую: prof,techno,budget-prof,budget,medicine",
    )
    d.add_argument("--database", help="сузить до одной базы (имя из манифеста)")
    d.add_argument("--out", default=str(_default_data()), help="каталог data/")
    d.add_argument(
        "--manifest",
        default="https://its.1c.ru/itsoffline/update/latest.xml",
        help="URL latest.xml",
    )
    d.set_defaults(func=cmd_download)

    s = sub.add_parser("serve", help="локальный просмотрщик")
    s.add_argument("--data", default=str(_default_data()), help="каталог data/")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
