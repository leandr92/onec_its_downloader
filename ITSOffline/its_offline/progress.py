"""Single-line console progress (stdlib only)."""

from __future__ import annotations

import sys


class Progress:
    def __init__(self, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = sys.stderr.isatty()
        self.enabled = enabled
        self._last_len = 0

    def update(self, overall: str, detail: str = "") -> None:
        if not self.enabled:
            return
        line = overall if not detail else f"{overall}  |  {detail}"
        pad = max(0, self._last_len - len(line))
        sys.stderr.write("\r" + line + (" " * pad))
        sys.stderr.flush()
        self._last_len = len(line)

    def finish(self, message: str = "") -> None:
        if not self.enabled:
            if message:
                print(message, file=sys.stderr)
            return
        if message:
            pad = max(0, self._last_len - len(message))
            sys.stderr.write("\r" + message + (" " * pad) + "\n")
        else:
            sys.stderr.write("\n")
        sys.stderr.flush()
        self._last_len = 0


def format_bytes(n: int | float) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"
