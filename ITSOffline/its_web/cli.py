"""Команда: python -m its_web download --db erp25doc"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .client import LoginError, load_env_file


def _default_data() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def _default_env() -> Path | None:
    candidate = Path(__file__).resolve().parents[2].parent / "its_scrapper" / ".env"
    return candidate if candidate.is_file() else None


def _credentials(env_path: Path | None) -> tuple[str, str, str]:
    file_env: dict[str, str] = {}
    if env_path is not None:
        if not env_path.is_file():
            print(f"нет файла учётных данных: {env_path}", file=sys.stderr)
            raise SystemExit(2)
        file_env = load_env_file(env_path)
    username = os.environ.get("ITS_USERNAME") or file_env.get("USERNAME") or ""
    password = os.environ.get("ITS_PASSWORD") or file_env.get("PASSWORD") or ""
    auth_url = os.environ.get("ITS_AUTH_URL") or file_env.get("AUTH_URL") or ""
    if not username or not password:
        print(
            "нужны логин и пароль: --env файл либо ITS_USERNAME и ITS_PASSWORD",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return username, password, auth_url


def cmd_download(args: argparse.Namespace) -> int:
    from .download import run_online

    env_path = Path(args.env) if args.env else _default_env()
    username, password, auth_url = _credentials(env_path)
    if args.delay < 0:
        print("--delay не может быть отрицательным", file=sys.stderr)
        return 2
    try:
        return run_online(
            Path(args.out),
            list(args.db),
            username,
            password,
            auth_url,
            delay=args.delay,
            limit=args.limit,
        )
    except LoginError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Прямая загрузка баз its.1c.ru")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="скачать указанные базы в data/library")
    download.add_argument("--db", action="append", required=True, help="код базы, например erp25doc")
    download.add_argument("--out", type=Path, default=_default_data(), help="каталог data")
    download.add_argument("--env", type=Path, default=None, help="файл с USERNAME и PASSWORD")
    download.add_argument("--delay", type=float, default=0.25, help="пауза между запросами, секунды")
    download.add_argument("--limit", type=int, default=0, help="скачать только первые N файлов")
    download.set_defaults(func=cmd_download)
    args = parser.parse_args(argv)
    return args.func(args)
