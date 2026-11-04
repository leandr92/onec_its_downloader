"""Разбор оглавления its.1c.ru и локальных путей к главам."""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

_CONTENT_FILE = re.compile(r"\.html?$", re.IGNORECASE)


class TocParser(HTMLParser):
    """Дерево из единственного ``ul.tree`` на странице базы."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[dict] = []
        self._stack: list[list[dict]] = []
        self._cur: dict | None = None
        self._capture = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "ul":
            classes = attr.get("class", "").split()
            if not self._stack:
                if "tree" in classes:
                    self._stack.append(self.root)
                return
            if not self._stack[-1]:
                return
            self._stack.append(self._stack[-1][-1]["children"])
            return
        if not self._stack or tag != "li" and tag != "a":
            return
        if tag == "li":
            match = re.fullmatch(r"toc_(\d+)_(.*)", attr.get("id", ""))
            node = {
                "doc_id": match.group(1) if match else "",
                "anchor": match.group(2) if match else "",
                "href": "",
                "title": "",
                "children": [],
            }
            self._stack[-1].append(node)
            self._cur = node
            self._capture = False
            return
        if self._cur is not None and not self._cur["href"]:
            self._cur["href"] = attr.get("href", "")
            self._capture = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture and self._cur is not None:
            self._cur["title"] = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._capture = False
            return
        if tag == "ul" and self._stack:
            self._stack.pop()
            if not self._stack:
                self._cur = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)


def parse_toc(html: str) -> list[dict]:
    parser = TocParser()
    parser.feed(html)
    parser.close()
    return parser.root


def iter_nodes(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from iter_nodes(node["children"])


def unique_doc_ids(nodes: list[dict]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for node in iter_nodes(nodes):
        doc_id = node["doc_id"]
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            ordered.append(doc_id)
    return ordered


def bookmark_anchor(href: str, fallback: str) -> str:
    parts = [unquote(part) for part in urlsplit(href).path.split("/") if part]
    if "bookmark" in parts and parts[-1]:
        return parts[-1]
    return fallback


def content_href(html: str, nick: str) -> str | None:
    """Первый путь главы в оболочке. Он стоит в ``<base href>`` в начале страницы."""
    text = html.replace("\\/", "/")
    match = re.search(
        rf"/db/content/{re.escape(nick)}/[^\"'<>]+?\.html?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return unquote(match.group(0))


def content_rel(site_path: str, nick: str) -> str | None:
    prefix = f"/db/content/{nick}/"
    path = unquote(urlsplit(site_path).path)
    if not path.startswith(prefix):
        return None
    rel = path[len(prefix) :]
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    return rel


_SITE_PREFIXES = ("/css/", "/js/", "/img/", "/fonts/")


def site_rel(site_path: str) -> str | None:
    """Общие стили сайта (``/css``, ``/js``), не главы другой базы."""
    path = unquote(urlsplit(site_path).path)
    if not any(path.startswith(prefix) for prefix in _SITE_PREFIXES):
        return None
    if ".." in path.split("/"):
        return None
    return "_site" + path


def local_href(site_path: str, nick: str, page_rel: str) -> str | None:
    """Абсолютная ссылка its.1c.ru → относительный путь от сохранённой страницы."""
    split = urlsplit(site_path)
    rel = content_rel(split.path, nick)
    if rel is None:
        rel = site_rel(split.path)
    if rel is None:
        return None
    parent = os.path.dirname(page_rel.replace("\\", "/"))
    local = os.path.relpath(rel, start=parent or ".").replace("\\", "/")
    if split.query:
        local += "?" + split.query
    if split.fragment:
        local += "#" + split.fragment
    return local


# Не трогаем уже относительные пути: перед «/css» в «../_site/css» стоит буква.
_ABS_CONTENT = re.compile(
    r"(?<![\w./-])(?:https?://its\.1c\.ru)?(?:/db/content/|/(?:css|js|img|fonts)/)[^\"'\s<>)]+",
    re.IGNORECASE,
)


def relativize_html(html: str, nick: str, page_rel: str) -> str:
    def replace(match: re.Match[str]) -> str:
        local = local_href(match.group(0), nick, page_rel)
        return local if local is not None else match.group(0)

    return _ABS_CONTENT.sub(replace, html)


def is_content_document(site_path: str) -> bool:
    return bool(_CONTENT_FILE.search(urlsplit(site_path).path))


_NAV_LI = re.compile(
    r'<li\b([^>]*)>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def parse_nav_items(html: str) -> list[dict]:
    """Плоский список книг или глав из ``/db/metadata/.../nav_list/``."""
    items: list[dict] = []
    for attrs, href, raw_title in _NAV_LI.findall(html):
        klass = ""
        class_match = re.search(r'class="([^"]*)"', attrs)
        if class_match:
            klass = class_match.group(1)
        doc_match = re.search(r"/content/(\d+)/hdoc", href)
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = re.sub(r"\s+", " ", title).strip()
        items.append(
            {
                "doc_id": doc_match.group(1) if doc_match else "",
                "anchor": "",
                "href": href,
                "title": title,
                "children": [],
                "folder": "folder" in klass.split(),
            }
        )
    return items


def browse_nav_url(nick: str, href: str) -> str | None:
    """``/db/<nick>/browse/13/-1/1`` → список глав этой книги."""
    path = unquote(urlsplit(href).path).rstrip("/")
    prefix = f"/db/{nick}/browse/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :]
    if not rest or ".." in rest.split("/"):
        return None
    return f"https://its.1c.ru/db/metadata/{nick}/nav_list/{rest}_"
