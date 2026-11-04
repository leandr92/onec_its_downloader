"""Сессия its.1c.ru: вход через login.1c.ru и обычные GET."""

from __future__ import annotations

import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ITS_SERVICE = "https://its.1c.ru/login/?action=aftercheck&provider=login"


def its_login_url() -> str:
    """Адрес формы входа. ``service`` кодируется целиком, иначе ``&provider`` отрезается."""
    return "https://login.1c.ru/login?" + urlencode({"service": ITS_SERVICE})


def quote_url(url: str) -> str:
    """Путь с кириллицей — в процентах, иначе http.client кодирует запрос в ASCII."""
    parts = urlsplit(url)
    path = quote(unquote(parts.path), safe="/%")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


class ClientError(Exception):
    pass


class LoginError(ClientError):
    pass


@dataclass
class Response:
    status: int
    url: str
    content_type: str
    body: bytes


def ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    for candidate in (
        "/etc/ssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/opt/homebrew/etc/ca-certificates/cert.pem",
    ):
        if Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Client:
    def __init__(self, delay: float = 0.25) -> None:
        self.delay = delay
        self._last = 0.0
        jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            urllib.request.HTTPSHandler(context=ssl_context()),
        )

    def _pause(self) -> None:
        rest = self.delay - (time.monotonic() - self._last)
        if rest > 0:
            time.sleep(rest)
        self._last = time.monotonic()

    def request(
        self,
        url: str,
        data: bytes | None = None,
        referer: str | None = None,
        limit: int | None = None,
    ) -> Response:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
        }
        if referer:
            headers["Referer"] = quote_url(referer)
        req = urllib.request.Request(quote_url(url), data=data, headers=headers)
        last_error: Exception | None = None
        for attempt in range(4):
            self._pause()
            try:
                with self._opener.open(req, timeout=60) as resp:
                    body = resp.read() if limit is None else resp.read(limit)
                    return Response(
                        status=getattr(resp, "status", 200),
                        url=resp.geturl(),
                        content_type=resp.headers.get("Content-Type", ""),
                        body=body,
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in (429, 502, 503) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                detail = exc.read(400)
                return Response(exc.code, url, exc.headers.get("Content-Type", ""), detail)
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
        raise ClientError(f"сеть недоступна: {last_error}")

    def request_public(self, url: str) -> Response:
        """GET без куков. Оглавление ИТС отдаётся и так, а сессионная страница иногда без дерева."""
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context()))
        req = urllib.request.Request(
            quote_url(url),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"},
        )
        self._pause()
        try:
            with opener.open(req, timeout=60) as resp:
                return Response(
                    status=getattr(resp, "status", 200),
                    url=resp.geturl(),
                    content_type=resp.headers.get("Content-Type", ""),
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:
            return Response(exc.code, url, exc.headers.get("Content-Type", ""), exc.read(400))

    def _cookie_names(self) -> set[str]:
        for handler in self._opener.handlers:
            if isinstance(handler, HTTPCookieProcessor):
                return {cookie.name for cookie in handler.cookiejar}
        return set()

    def login(self, username: str, password: str, auth_url: str = "") -> None:
        # Сессия its.1c.ru должна уже существовать, иначе билет входа не прикрепляется.
        del auth_url  # адрес сервиса фиксированный, чтобы не разрезать параметр service
        self.request("https://its.1c.ru/")
        form = its_login_url()
        page = self.request(form)
        text = page.body.decode("utf-8", "replace")
        execution = re.search(r'name="execution"\s+value="([^"]+)"', text)
        if not execution:
            raise LoginError("форма входа login.1c.ru не открылась")
        event = re.search(r'name="_eventId"\s+value="([^"]*)"', text)
        payload = urlencode(
            {
                "username": username,
                "password": password,
                "execution": execution.group(1),
                "_eventId": event.group(1) if event else "submit",
                "rememberMe": "on",
                "geolocation": "",
                "inviteCode": "",
                "inviteType": "",
                "submit": "Войти",
            }
        ).encode()
        result = self.request(page.url, data=payload)
        host = urlsplit(result.url).netloc
        if host != "its.1c.ru" or b"error=1" in result.body:
            raise LoginError("логин или пароль не приняты")
        if "BITRIX_SM_LOGIN" not in self._cookie_names():
            raise LoginError("сессия ИТС не открылась")
