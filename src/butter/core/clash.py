"""Control an already-running mihomo/Clash core over its REST API.

Why this exists: most local setups already run a Clash-family client whose core
*is* mihomo. Instead of launching a second core (port clashes, two rule sets,
two fake-ip DNS stacks), Butter can talk to the running core's
external-controller:

    GET /version                        → confirm it is mihomo and get the version
    GET /proxies                        → live node + group state
    PUT /proxies/{group} {"name": ...}  → switch the active node of a group
    GET /proxies/{name}/delay?url=...   → latency probe for one node

The core keeps its own routing; Butter only decides *which node* a group uses.
That keeps a single source of truth for rules (including the GEOIP,CN,DIRECT
split that would otherwise route apple.com straight out of the LAN).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

LOGGER = logging.getLogger("butter.clash")


class ClashError(RuntimeError):
    pass


@dataclass
class NodeInfo:
    name: str
    kind: str
    now: str = ""
    delay: int | None = None
    alive: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.kind, "now": self.now, "delay": self.delay, "alive": self.alive}


class ClashController:
    """Thin wrapper around mihomo's REST API (no websocket, no config writing)."""

    def __init__(self, api: str, secret: str = "", timeout: float = 5.0) -> None:
        if not api:
            raise ClashError("未配置 clash_api（形如 127.0.0.1:9090）")
        raw = api.strip()
        if "://" not in raw:
            raw = f"http://{raw}"
        # env proxies (http_proxy=…, NO_PROXY=[::1]) can corrupt loopback URLs
        self.base = raw.rstrip("/")
        self._trust_env = False
        self.secret = secret
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret}"} if self.secret else {}

    async def _request(self, method: str, path: str, json_body: Any = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            try:
                resp = await client.request(method, f"{self.base}{path}", headers=self._headers(), json=json_body)
            except httpx.HTTPError as exc:
                raise ClashError(f"无法连接 mihomo API ({self.base}): {exc}") from exc
        if resp.status_code in (401, 403):
            raise ClashError("mihomo API 需要 secret，请在网络页填写 clash_secret")
        if resp.status_code >= 400:
            raise ClashError(f"mihomo API {path} -> {resp.status_code} {resp.text[:120]}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # --- reads ------------------------------------------------------------
    async def version(self) -> dict[str, Any]:
        return await self._request("GET", "/version") or {}

    async def groups(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/proxies") or {}
        out = []
        for name, node in (data.get("proxies") or {}).items():
            if node.get("type") in ("Selector", "URLTest", "Fallback", "LoadBalance"):
                out.append(
                    {
                        "name": name,
                        "type": node.get("type"),
                        "now": node.get("now", ""),
                        "members": node.get("all", []),
                    }
                )
        return out

    async def nodes(self, keyword: str = "", limit: int = 400) -> list[NodeInfo]:
        data = await self._request("GET", "/proxies") or {}
        synonyms = {
            "hk": ("香港", "HK", "Hong Kong"),
            "us": ("美国", "US", "United States", "洛杉矶", "圣何塞"),
            "uk": ("英国", "UK", "GB", "London", "伦敦"),
            "gb": ("英国", "UK", "GB", "London", "伦敦"),
            "jp": ("日本", "JP", "Tokyo", "东京"),
        }
        needle = keyword.strip().lower()
        terms = synonyms.get(needle, (keyword,) if needle else ())
        result: list[NodeInfo] = []
        for name, node in (data.get("proxies") or {}).items():
            if node.get("type") in ("Selector", "URLTest", "Fallback", "LoadBalance", "Direct", "Reject"):
                continue
            if name in ("COMPATIBLE", "PASS", "REJECT", "DIRECT", "GLOBAL"):
                continue
            if terms and not any(term.lower() in name.lower() for term in terms):
                continue
            history = node.get("history") or []
            delay = history[-1].get("delay") if history else None
            result.append(NodeInfo(name=name, kind=node.get("type", ""), delay=delay, alive=bool(node.get("alive", True))))
            if len(result) >= limit:
                break
        return result

    async def current(self, group: str) -> str:
        data = await self._request("GET", f"/proxies/{quote(group, safe='')}") or {}
        return data.get("now", "")

    # --- writes -----------------------------------------------------------
    async def select(self, group: str, node: str) -> str:
        await self._request("PUT", f"/proxies/{quote(group, safe='')}", {"name": node})
        LOGGER.info("[clash] group %s -> %s", group, node)
        return await self.current(group)

    async def probe(self, node: str, url: str = "http://www.gstatic.com/generate_204") -> int | None:
        data = (
            await self._request("GET", f"/proxies/{quote(node, safe='')}/delay?timeout=5000&url={quote(url, safe='')}") or {}
        )
        return data.get("delay")
