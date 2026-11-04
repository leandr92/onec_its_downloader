"""Скачивание одной онлайн-базы: оглавление, главы, картинки."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .client import Client, ClientError, Response
from .toc import (
    bookmark_anchor,
    browse_nav_url,
    content_href,
    content_rel,
    is_content_document,
    iter_nodes,
    parse_nav_items,
    parse_toc,
    relativize_html,
    site_rel,
    unique_doc_ids,
)

HOST = "https://its.1c.ru"
ASSET_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".bmp",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
}
_ATTR = re.compile(
    r"""(?:src|href)\s*=\s*(['"])(.*?)\1""",
    re.IGNORECASE,
)
_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE)
_CHARSET = re.compile(r"charset=([\w-]+)", re.IGNORECASE)


class DownloadStopped(Exception):
    pass


def asset_request_url(asset: str) -> str:
    """Локальная перепись ``/_site/css/...`` обратно в ``https://its.1c.ru/css/...``."""
    parts = urlsplit(asset)
    path = parts.path
    marker = "/_site/"
    if marker not in path:
        return asset
    tail = path.split(marker, 1)[1]
    query = f"?{parts.query}" if parts.query else ""
    return f"{HOST}/{tail}{query}"


def charset_of(content_type: str, default: str = "windows-1251") -> str:
    match = _CHARSET.search(content_type or "")
    return match.group(1) if match else default


def decode_body(response: Response) -> str:
    encoding = charset_of(response.content_type)
    try:
        return response.body.decode(encoding)
    except LookupError:
        return response.body.decode("windows-1251", "replace")


def asset_urls(html: str, page_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_ATTR, _CSS_URL):
        for match in pattern.finditer(html):
            raw = match.group(2).strip()
            if not raw or raw.startswith(("#", "mailto:", "javascript:", "data:")):
                continue
            absolute = urljoin(page_url, raw)
            split = urlsplit(absolute)
            if split.netloc and split.netloc != "its.1c.ru":
                continue
            if is_content_document(split.path):
                continue
            suffix = Path(split.path).suffix.lower()
            if suffix not in ASSET_EXT and "/_img/" not in split.path:
                continue
            if absolute not in seen:
                seen.add(absolute)
                found.append(absolute)
    return found


def _safe_dest(library: Path, rel: str) -> Path | None:
    parts = Path(rel).parts
    if not parts or any(part in ("", ".", "..") or ".." in part for part in parts):
        return None
    dest = (library / rel).resolve()
    try:
        dest.relative_to(library.resolve())
    except ValueError:
        return None
    return dest


def _write_bytes(dest: Path, body: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)


class DatabaseDownloader:
    def __init__(self, client: Client, library: Path, nick: str, limit: int = 0) -> None:
        self.client = client
        self.library = library
        self.nick = nick
        self.limit = limit
        self.manifest_path = library / "manifest.json"
        self.docs: dict[str, str] = {}
        self.errors: list[str] = []
        self.saved_assets = 0
        self._refusals = 0

    def load_manifest(self) -> None:
        if not self.manifest_path.is_file():
            return
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        self.docs = {str(k): v for k, v in (data.get("docs") or {}).items()}
        self.errors = list(data.get("errors") or [])

    def save_manifest(self) -> None:
        self.library.mkdir(parents=True, exist_ok=True)
        payload = {"nick": self.nick, "docs": self.docs, "errors": self.errors}
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _check(self, response: Response, what: str) -> None:
        if response.status in (403, 429, 503):
            self._refusals += 1
            if self._refusals >= 5:
                raise DownloadStopped(
                    f"{self.nick}: сервер отвечает {response.status}, остановка"
                )
            self.errors.append(f"{what}: HTTP {response.status}")
            return
        self._refusals = 0

    def fetch_toc(self) -> list[dict]:
        response = self.client.request(f"{HOST}/db/{self.nick}")
        self._check(response, "оглавление")
        if response.status != 200:
            raise DownloadStopped(f"{self.nick}: оглавление HTTP {response.status}")
        html = decode_body(response).replace("\\/", "/")
        nodes = self._toc_from_html(html)
        if unique_doc_ids(nodes):
            return nodes
        public = self.client.request_public(f"{HOST}/db/{self.nick}")
        if public.status == 200:
            public_html = decode_body(public).replace("\\/", "/")
            public_nodes = self._toc_from_html(public_html)
            if unique_doc_ids(public_nodes):
                return public_nodes
        return nodes

    def _toc_from_html(self, html: str) -> list[dict]:
        nodes = parse_toc(html)
        if unique_doc_ids(nodes):
            return nodes
        browsed = self._browse_tree(html)
        return browsed or nodes

    def _browse_tree(self, html: str) -> list[dict]:
        """Документация платформы: книги в nav_list, у каждой свой список глав."""
        match = re.search(
            rf"/db/metadata/{re.escape(self.nick)}/nav_list/\d+/-1_",
            html,
        )
        if not match:
            return []
        return self._read_nav(HOST + match.group(0), depth=0, seen=set())

    def _read_nav(self, url: str, depth: int, seen: set[str]) -> list[dict]:
        if url in seen or depth > 8:
            return []
        seen.add(url)
        response = self.client.request(url)
        self._check(response, "оглавление")
        if response.status != 200:
            self.errors.append(f"оглавление {url}: HTTP {response.status}")
            return []
        nodes: list[dict] = []
        for item in parse_nav_items(decode_body(response)):
            if item.pop("folder", False):
                child_url = browse_nav_url(self.nick, item["href"])
                if child_url:
                    item["children"] = self._read_nav(child_url, depth + 1, seen)
            nodes.append(item)
        return nodes

    def resolve_doc(self, doc_id: str) -> str | None:
        known = self.docs.get(doc_id)
        if known and (self.library / known).is_file():
            self._download_html(known)
            return known
        shell_url = f"{HOST}/db/{self.nick}/content/{doc_id}/hdoc"
        response = self.client.request(shell_url, limit=32768)
        self._check(response, f"doc {doc_id}")
        if response.status != 200:
            self.errors.append(f"doc {doc_id}: HTTP {response.status}")
            return known
        href = content_href(decode_body(response), self.nick)
        rel = content_rel(href, self.nick) if href else None
        if not rel:
            self.errors.append(f"doc {doc_id}: нет файла главы")
            return None
        self._download_html(rel)
        dest = self.library / rel
        if dest.is_file() and dest.stat().st_size > 0:
            self.docs[doc_id] = rel
            return rel
        self.docs.pop(doc_id, None)
        return None

    def _download_html(self, rel: str) -> None:
        dest = _safe_dest(self.library, rel)
        if dest is None:
            self.errors.append(f"{rel}: путь вне каталога")
            return
        if dest.is_file() and dest.stat().st_size > 0:
            encoding = "windows-1251"
            text = dest.read_bytes().decode(encoding, "replace")
            rewritten = relativize_html(text, self.nick, rel)
            if rewritten != text:
                _write_bytes(dest, rewritten.encode(encoding, "replace"))
            self._download_assets(rel, rewritten.encode(encoding, "replace"), encoding)
            return
        url = f"{HOST}/db/content/{self.nick}/{rel}"
        response = self.client.request(url, referer=f"{HOST}/db/{self.nick}")
        self._check(response, rel)
        if response.status != 200 or not response.body:
            self.errors.append(f"{rel}: HTTP {response.status}")
            return
        if "text/html" not in response.content_type.lower():
            self.errors.append(f"{rel}: не HTML ({response.content_type})")
            return
        encoding = charset_of(response.content_type)
        text = response.body.decode(encoding, "replace")
        rewritten = relativize_html(text, self.nick, rel)
        _write_bytes(dest, rewritten.encode(encoding, "replace"))
        self._download_assets(rel, rewritten.encode(encoding, "replace"), encoding)

    def _download_assets(self, page_rel: str, body: bytes, encoding: str) -> None:
        try:
            text = body.decode(encoding)
        except UnicodeDecodeError:
            text = body.decode(encoding, "replace")
        page_url = f"{HOST}/db/content/{self.nick}/{page_rel}"
        for asset in asset_urls(text, page_url):
            rel = content_rel(urlsplit(asset).path, self.nick) or site_rel(asset)
            if rel is None:
                continue
            dest = _safe_dest(self.library, rel)
            if dest is None or (dest.is_file() and dest.stat().st_size > 0):
                continue
            response = self.client.request(asset_request_url(asset), referer=page_url)
            self._check(response, rel)
            if response.status != 200 or not response.body:
                self.errors.append(f"{rel}: HTTP {response.status}")
                continue
            if "text/html" in response.content_type.lower() and dest.suffix.lower() != ".htm":
                self.errors.append(f"{rel}: вместо файла пришла страница")
                continue
            payload = response.body
            self.saved_assets += 1
            if dest.suffix.lower() == ".css":
                css = payload.decode(charset_of(response.content_type), "replace")
                css = relativize_html(css, self.nick, rel)
                payload = css.encode(charset_of(response.content_type), "replace")
                _write_bytes(dest, payload)
                self._download_assets(rel, payload, charset_of(response.content_type))
                continue
            _write_bytes(dest, payload)

    def write_toc(self, nodes: list[dict]) -> int:
        pages: list[dict] = []

        def walk(items: list[dict], book: str) -> None:
            for node in items:
                title = node["title"] or node["anchor"] or node["doc_id"]
                this_book = book or title or "(корень)"
                rel = self.docs.get(node["doc_id"], "")
                if node["doc_id"] and rel and (self.library / rel).is_file():
                    anchor = bookmark_anchor(node["href"], node["anchor"])
                    path = f"{rel}#{anchor}" if anchor else rel
                    pages.append({"path": path, "book": this_book, "title": title})
                walk(node["children"], this_book)

        walk(nodes, "")
        toc_path = self.library / "toc.json"
        toc_path.write_text(
            json.dumps({"pages": pages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(pages)

    def run(self) -> dict:
        self.library.mkdir(parents=True, exist_ok=True)
        self.load_manifest()
        self.errors = []
        nodes = self.fetch_toc()
        doc_ids = unique_doc_ids(nodes)
        if self.limit:
            doc_ids = doc_ids[: self.limit]
        print(
            f"{self.nick}: пунктов {sum(1 for _ in iter_nodes(nodes))}, файлов {len(doc_ids)}",
            flush=True,
        )
        for index, doc_id in enumerate(doc_ids, start=1):
            try:
                rel = self.resolve_doc(doc_id)
            except ClientError as exc:
                self.errors.append(f"doc {doc_id}: {exc}")
                rel = None
            name = rel or "нет файла"
            print(f"{self.nick}: {index}/{len(doc_ids)} {name}", flush=True)
            self.save_manifest()
            if index % 20 == 0 or index == len(doc_ids):
                self.write_toc(nodes)
        self.save_manifest()
        pages = self.write_toc(nodes)
        files = len({path for path in self.docs.values() if (self.library / path).is_file()})
        print(
            f"{self.nick}: готово, страниц в оглавлении {pages}, файлов {files}, "
            f"новых картинок {self.saved_assets}, ошибок {len(self.errors)}",
            flush=True,
        )
        return {"nick": self.nick, "pages": pages, "files": files, "errors": len(self.errors)}


def run_online(
    data_dir: Path,
    nicks: list[str],
    username: str,
    password: str,
    auth_url: str,
    delay: float,
    limit: int,
) -> int:
    client = Client(delay=delay)
    print("вход на its.1c.ru", flush=True)
    client.login(username, password, auth_url)
    print("вход выполнен", flush=True)
    library_root = Path(data_dir) / "library"
    failed = False
    for nick in nicks:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", nick):
            print(f"{nick}: недопустимое имя базы", flush=True)
            failed = True
            continue
        loader = DatabaseDownloader(client, library_root / nick, nick, limit=limit)
        try:
            result = loader.run()
        except DownloadStopped as exc:
            print(str(exc), flush=True)
            loader.save_manifest()
            failed = True
            continue
        if result["files"] == 0:
            failed = True
    return 1 if failed else 0
