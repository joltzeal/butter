"""Protocol constants fetched from the activation service.

The client can be decompiled, so the values that took real work to find are not
kept in the binary alone: with a licence the shell hands over the current bundle,
it is verified with the same key that signs licences, and cached.

Resolution order for every lookup: cache, then built-in default. Losing the
network never bricks the app; losing the licence only costs the overrides.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.request
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .store import data_dir

LOGGER = logging.getLogger("butter.params")

# Master public key — same one embedded in the shell for licence checks.
PUBLIC_KEY_HEX = "7fb80f6aebd9e7f32e56dda314ac11688e2a14407a9298480b1383e6b7a28c86"

# Cache is refreshed lazily; older copies are still used.
MAX_AGE = 7 * 24 * 3600

DEFAULTS: dict[str, Any] = {"jr": "30", "domain_id": "39", "ver": 0}


def _path():
    return data_dir() / "params.json"


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _load_cache() -> dict[str, Any]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing or unreadable cache
        return {}
    return raw if isinstance(raw, dict) else {}


def current() -> dict[str, Any]:
    """Effective values: cached overrides on top of the built-ins."""
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in _load_cache().items() if v})
    return merged


def get(key: str) -> Any:
    return current().get(key, DEFAULTS.get(key))


def srp_n_hex(fallback: str) -> str:
    """Group order override; falls back to the compiled constant."""
    return str(get("n_hex") or fallback)


def refresh() -> bool:
    """Fetch and verify a fresh bundle. Returns whether the cache changed."""
    base = os.environ.get("BUTTER_ACTIVATION_URL", "")
    payload = os.environ.get("BUTTER_LICENSE_PAYLOAD", "")
    sig = os.environ.get("BUTTER_LICENSE_SIG", "")
    machine = os.environ.get("BUTTER_MACHINE", "")
    if not (base and payload and sig and machine):
        return False

    cache = _load_cache()
    if cache.get("fetched", 0) and time.time() - cache["fetched"] < MAX_AGE:
        return False

    req = urllib.request.Request(
        f"{base.rstrip('/')}/params",
        headers={
            "x-payload": payload,
            "x-sig": sig,
            "x-machine": machine,
            # Cloudflare's bot rules reject the stock urllib agent.
            "user-agent": "butter-params/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            body = json.loads(res.read())
    except Exception as exc:  # noqa: BLE001 - offline is normal
        LOGGER.info("[params] 拉取失败: %s", exc)
        return False

    raw = _b64decode(body["payload"])
    key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
    try:
        key.verify(_b64decode(body["sig"]), raw)
    except InvalidSignature:
        LOGGER.warning("[params] 签名不匹配，保留缓存")
        return False

    bundle = json.loads(raw)
    bundle["fetched"] = int(time.time())
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(bundle), encoding="utf-8")
    LOGGER.info("[params] 已更新 ver=%s", bundle.get("ver"))
    return True
