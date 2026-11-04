"""Safe path joining for packed archives."""

from __future__ import annotations

from pathlib import Path


def safe_join(base: Path, rel: str) -> Path | None:
    """Join *rel* under *base*. Return None if the path escapes *base*."""
    rel = rel.replace("\\", "/")
    parts: list[str] = []
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    out = base.joinpath(*parts) if parts else base
    try:
        out.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    return out
