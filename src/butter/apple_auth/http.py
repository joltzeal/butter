"""HTTP transport shared by every client.

The reference client used ``curl_cffi`` with Chrome TLS impersonation so that
Apple's bot detection sees a browser fingerprint. We keep that behaviour and
fall back to plain ``httpx`` when the impersonation backend is unavailable
(e.g. a platform wheel that did not ship).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import socket
import string
from urllib.parse import urlparse
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

LOGGER = logging.getLogger("butter.http")

try:  # pragma: no cover - depends on wheel availability
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession

    HAS_CURL_CFFI = True
except Exception:  # pragma: no cover
    _CurlAsyncSession = None  # type: ignore[assignment]
    HAS_CURL_CFFI = False


@dataclass
class Response:
    status: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""
    content: bytes = b""

    def header(self, name: str, default: str = "") -> str:
        low = name.lower()
        for key, value in self.headers.items():
            if key.lower() == low:
                return value
        return default

    def headers_all(self, name: str) -> list[str]:
        """Every value for a repeated header (notably ``Set-Cookie``)."""
        low = name.lower()
        out: list[str] = []
        for key, value in self.headers.items():
            if key.lower() == low:
                out.extend(part for part in str(value).split("\n") if part)
        return out

    def set_cookies(self) -> list[str]:
        """Individual ``Set-Cookie`` header values, one per cookie.

        ``dict(headers)`` collapses repeated headers to the last one, which used
        to drop most of Apple's cookies — including the HttpOnly ``aa`` flag
        that distinguishes a completed sign-in.
        """
        return self.headers_all("set-cookie")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


def new_fetch_id() -> str:
    """Apple's frame id, exactly 37 chars: ``auth-<8>-<4>-<4>-<4>-<8>``.

    The blob's shape is load bearing. ``authorize/signin`` derives the length of
    ``X-Apple-Auth-Attributes`` from this string (measured:
    ``len(attrs) == 232 + len(frame_id) * 1.5``), and Apple rejects requests
    whose attributes are shorter than the browser's. A bare 8-char id yields
    252 chars; the browser shape yields the expected 292.
    """
    pick = lambda n: "".join(random.choices(_ID_ALPHABET, k=n))  # noqa: E731
    return f"auth-{pick(8)}-{pick(4)}-{pick(4)}-{pick(4)}-{pick(8)}"


_ID_ALPHABET = string.ascii_lowercase + string.digits


def resolve_host(host: str, port: int = 443) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    ordered: list[str] = []
    for family, _, _, _, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in ordered:
            ordered.append(ip)
    return ordered


def mask_proxy(url: str) -> str:
    if not url:
        return "(no proxy)"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "(unparsable)"
    if parts.username and parts.password:
        netloc = f"{parts.username}:****@{parts.hostname}:{parts.port}"
        return f"{parts.scheme}://{netloc}"
    return url


def _merge_headers(resp: Any) -> dict[str, str]:
    """Collapse a response's headers while keeping *every* ``Set-Cookie``.

    curl_cffi/httpx expose repeated headers through ``raw``/``multi_items``;
    plain ``dict(headers)`` keeps only the last value, silently discarding the
    cookies that matter (``aa``, ``myacinfo``, rotated ``scnt`` siblings).
    ``Set-Cookie`` values are joined with ``\n`` so callers can split them.
    """
    merged: dict[str, str] = {}
    try:
        pairs = list(resp.headers.multi_items())
    except Exception:
        try:
            pairs = list(resp.headers.items())
        except Exception:
            return {}
    for key, value in pairs:
        if key.lower() == "set-cookie":
            if "Set-Cookie" in merged:
                merged["Set-Cookie"] += "\n" + value
            else:
                merged["Set-Cookie"] = value
        else:
            merged[key] = value
    return merged


class Transport:
    """Small async wrapper that keeps cookies and a stable impersonation profile."""

    def __init__(self, proxy: str | None = None, impersonate: str = "chrome142", timeout: float = 30.0) -> None:
        # Honour http(s)_proxy / all_proxy from the shell (curl_cffi reads them from
        # the process env, which made "直连" silently proxy through a system proxy).
        if os.environ.get("BUTTER_IGNORE_ENV_PROXY", "1") == "1":
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                os.environ.pop(key, None)
        self.proxy = proxy or None
        self.impersonate = impersonate
        self.timeout = timeout
        # Cookies are kept per registrable domain. Apple keeps separate jars for
        # ``idmsa.apple.com``, ``.apple.com`` and ``.store.apple.com``; collapsing
        # them into one dict leaks store tokens into IDMSA calls (and vice versa),
        # which the edge answers with 401/541.
        self.cookies: dict[str, str] = {}
        self.jar: dict[str, dict[str, str]] = {}
        self._session: Any = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "Transport":
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def open(self) -> None:
        if HAS_CURL_CFFI:
            kwargs: dict[str, Any] = {"impersonate": self.impersonate, "timeout": self.timeout}
            if self.proxy:
                kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
            self._session = _CurlAsyncSession(**kwargs)
        else:
            proxies = self.proxy if self.proxy else None
            self._client = httpx.AsyncClient(timeout=self.timeout, proxies=proxies, follow_redirects=False)

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # --- core -------------------------------------------------------------
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json_body: Any = None,
        cookies: dict[str, str] | None = None,
        allow_redirects: bool = False,
    ) -> Response:
        jar = self.cookies_for(url)
        jar.update(self.cookies)
        if cookies is not None:
            # Passing an explicit dict replaces the jar ({} means "send none"),
            # which is what Apple expects on the bare IDMSA state call.
            jar = dict(cookies)

        if self._session is None and self._client is None:
            await self.open()

        if self._session is not None:
            resp = await self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                json=json_body,
                cookies=jar or None,
                allow_redirects=allow_redirects,
            )
            try:
                self._store_cookies(url, dict(resp.cookies.items()))
            except Exception:
                pass
            return Response(
                status=resp.status_code,
                url=str(resp.url),
                headers=_merge_headers(resp),
                text=resp.text or "",
                content=resp.content or b"",
            )

        assert self._client is not None
        resp = await self._client.request(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            json=json_body,
            cookies=jar or None,
            follow_redirects=allow_redirects,
        )
        self._store_cookies(url, dict(resp.cookies.items()))
        return Response(
            status=resp.status_code,
            url=str(resp.url),
            headers=_merge_headers(resp),
            text=resp.text,
            content=resp.content,
        )

    # --- per-domain cookie jars -------------------------------------------
    @staticmethod
    def _scope(url: str) -> str:
        """Coarse scope key: ``store`` / ``idmsa`` / ``apple`` / other host."""
        host = (urlparse(url).hostname or "").lower()
        if host.endswith(".store.apple.com") or host == "store.apple.com":
            return "store"
        if host == "idmsa.apple.com":
            return "idmsa"
        if host == "appleid.apple.com":
            return "appleid"
        if host.endswith("apple.com"):
            return "apple"
        return host

    def _store_cookies(self, url: str, values: dict[str, str]) -> None:
        if not values:
            return
        scope = self._scope(url)
        bucket = self.jar.setdefault(scope, {})
        bucket.update(values)
        if scope in ("apple", "store"):
            # Domain=.apple.com cookies are valid everywhere under apple.com.
            self.jar.setdefault("apple", {}).update(values)

    def cookies_for(self, url: str) -> dict[str, str]:
        scope = self._scope(url)
        out = dict(self.jar.get("apple", {}))
        out.update(self.jar.get(scope, {}))
        return out

    async def get(self, url: str, **kw) -> Response:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw) -> Response:
        return await self.request("POST", url, **kw)

    async def put(self, url: str, **kw) -> Response:
        return await self.request("PUT", url, **kw)

    async def delete(self, url: str, **kw) -> Response:
        return await self.request("DELETE", url, **kw)


async def pre_resolve(host: str) -> str:
    """Resolve a proxy host ahead of the request (avoids blocked in-flight DNS)."""
    loop = asyncio.get_running_loop()
    addrs = await loop.run_in_executor(None, resolve_host, host)
    if not addrs:
        LOGGER.debug("pre-resolve failed for %s", host)
    return ",".join(addrs)


_SID_RE = re.compile(r"-sid-[a-z0-9]+")


def rotate_sid(proxy: str, sid: str, region: str = "") -> str:
    """Rebuild a sticky-session proxy URL with a fresh ``sid`` token."""
    if not proxy:
        return proxy
    parts = urlsplit(proxy)
    user = parts.username or ""
    if "-sid-" in user:
        user = _SID_RE.sub("", user)
    if region:
        user = f"{user}-region-{region}"
    user = f"{user}-sid-{sid}-t-10"
    credentials = user if not parts.password else f"{user}:{parts.password}"
    return f"{parts.scheme}://{credentials}@{parts.hostname}:{parts.port}"
