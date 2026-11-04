"""Local browser viewer for extracted ITS library."""

from __future__ import annotations

import json
import mimetypes
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

TEXT_CHARSET = {
    ".htm": "windows-1251",
    ".html": "windows-1251",
    ".css": "windows-1251",
    ".js": "windows-1251",
    ".json": "utf-8",
}


def load_library_index(data_dir: Path) -> list[dict]:
    library = Path(data_dir) / "library"
    bases: list[dict] = []
    if not library.is_dir():
        return bases
    for base_dir in sorted(p for p in library.iterdir() if p.is_dir()):
        toc_path = base_dir / "toc.json"
        pages = []
        if toc_path.is_file():
            try:
                toc = json.loads(toc_path.read_text(encoding="utf-8"))
                pages = toc.get("pages") or []
            except json.JSONDecodeError:
                pages = []
        bases.append({"name": base_dir.name, "pages": pages})
    return bases


class ViewerHandler(BaseHTTPRequestHandler):
    data_dir: Path = Path(".")
    static_dir: Path = STATIC_DIR

    def log_message(self, fmt: str, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in ("/", "/index.html"):
            self._send_file(self.static_dir / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/toc":
            payload = json.dumps(load_library_index(self.data_dir), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path.startswith("/library/"):
            rel = path[len("/library/") :]
            target = (self.data_dir / "library" / rel).resolve()
            library_root = (self.data_dir / "library").resolve()
            try:
                target.relative_to(library_root)
            except ValueError:
                self.send_error(403)
                return
            if not target.is_file():
                self.send_error(404)
                return
            self._send_file(target, self._content_type(target))
            return
        # static assets
        static_target = (self.static_dir / path.lstrip("/")).resolve()
        try:
            static_target.relative_to(self.static_dir.resolve())
        except ValueError:
            self.send_error(403)
            return
        if static_target.is_file():
            self._send_file(static_target, self._content_type(static_target))
            return
        self.send_error(404)

    def _content_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in TEXT_CHARSET:
            base = {
                ".htm": "text/html",
                ".html": "text/html",
                ".css": "text/css",
                ".js": "text/javascript",
                ".json": "application/json",
            }[suffix]
            return f"{base}; charset={TEXT_CHARSET[suffix]}"
        guessed, _ = mimetypes.guess_type(str(path))
        return guessed or "application/octet-stream"

    def _send_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(data_dir: Path, port: int = 8765, *, open_browser: bool = True) -> None:
    data_dir = Path(data_dir).resolve()
    handler = partial(ViewerHandler)
    ViewerHandler.data_dir = data_dir
    ViewerHandler.static_dir = STATIC_DIR
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"ITSOffline viewer: {url}")
    print(f"data: {data_dir}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
