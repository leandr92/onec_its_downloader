"""Parse ITS offline latest.xml and filter databases by kit codes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

KIT_CODES: dict[str, str] = {
    "prof": "161",
    "techno": "160",
    "budget-prof": "164",
    "budget": "163",
    "medicine": "65",
}

KIT_LABELS: dict[str, str] = {
    "prof": "ПРОФ",
    "techno": "Техно",
    "budget-prof": "Бюджет ПРОФ",
    "budget": "Бюджет",
    "medicine": "Медицина",
}

DEFAULT_MANIFEST_URL = "https://its.1c.ru/itsoffline/update/latest.xml"


@dataclass(frozen=True)
class Database:
    name: str
    path: str
    access: frozenset[str]
    dbid: str = ""
    size: int | None = None

    def url(self, base: str) -> str:
        base = base if base.endswith("/") else base + "/"
        return urljoin(base, self.path)

    def pack_filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class Manifest:
    base: str
    databases: list[Database]


def https_base(base: str) -> str:
    """Rewrite http:// base to https:// (old exe ignored redirects)."""
    parsed = urlparse(base)
    if parsed.scheme == "http":
        parsed = parsed._replace(scheme="https")
    return urlunparse(parsed)


def _parse_access(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def access_has_code(access: frozenset[str], code: str) -> bool:
    """Exact token match: ``161`` does not match ``16`` or ``165``."""
    return code in access


def parse_manifest_xml(text: str) -> Manifest:
    root = ET.fromstring(text)
    base = root.attrib.get("base", "")
    databases: list[Database] = []
    for node in root.findall("./databases/database"):
        name = node.attrib.get("name", "")
        path = node.attrib.get("path", "")
        if not name or not path:
            continue
        size_raw = node.attrib.get("size")
        size = int(size_raw) if size_raw and size_raw.isdigit() else None
        databases.append(
            Database(
                name=name,
                path=path,
                access=_parse_access(node.attrib.get("access")),
                dbid=node.attrib.get("dbid", ""),
                size=size,
            )
        )
    return Manifest(base=https_base(base), databases=databases)


def resolve_kit_codes(kit_names: list[str]) -> list[str]:
    codes: list[str] = []
    for name in kit_names:
        key = name.strip().lower()
        if key not in KIT_CODES:
            raise ValueError(f"unknown kit: {name}")
        codes.append(KIT_CODES[key])
    return codes


def filter_databases(
    databases: list[Database],
    *,
    all_kits: bool = False,
    kit_codes: list[str] | None = None,
    database_name: str | None = None,
) -> list[Database]:
    """Select databases for download.

    ``--all`` keeps every database. Kit filter keeps databases with no access
    list (shared) or with at least one selected kit code. Optional
    ``database_name`` narrows the result further (case-insensitive).
    """
    if all_kits:
        selected = list(databases)
    else:
        if not kit_codes:
            raise ValueError("kit_codes required when all_kits is false")
        selected = []
        for db in databases:
            if not db.access:
                selected.append(db)
                continue
            if any(access_has_code(db.access, code) for code in kit_codes):
                selected.append(db)

    # Deduplicate by pack path (one base may appear once).
    seen: set[str] = set()
    unique: list[Database] = []
    for db in selected:
        key = db.path.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(db)

    if database_name:
        needle = database_name.lower()
        unique = [db for db in unique if db.name.lower() == needle]
    return unique
