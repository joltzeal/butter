"""Cookie scope helpers shared by session persistence and the services layer.

Kept dependency-free on purpose: ``session.py`` imports ``core.store`` and
``core.services`` imports ``session``, so anything both need has to live
outside that cycle.
"""

from __future__ import annotations

# Cookies minted on idmsa.apple.com. They are useless on the store host and
# must be written back to the IDMSA scope or the session half disappears.
IDMSA_COOKIES = ("myacinfo", "aasp", "ifssp")

# Cookies worth persisting to resume a session.
SESSION_COOKIES = ("DES", "myacinfo", "as_disa", "as_sfa", "ifssp", "aasp")

# Extra jar members that affect risk scoring and must survive a restart.
TRACKING_COOKIES = (
    "dssid2",
    "dssf",
    "as_dsc",
    "as_pcts",
    "shld_bt_ck",
    "shld_bt_m",
    "geo",
)


def is_session_cookie(name: str) -> bool:
    """``DES*`` are the refresh tokens; the rest are named explicitly."""
    return name.startswith("DES") or name in SESSION_COOKIES


def is_persisted(name: str) -> bool:
    return is_session_cookie(name) or name in TRACKING_COOKIES


def scope_for(name: str) -> str:
    """IDMSA origin vs the shared apple.com scope."""
    return "idmsa.apple.com" if name in IDMSA_COOKIES else ".apple.com"


def restore_session(session, cookies: dict[str, str]) -> None:
    """Write saved cookies back onto a ``curl_cffi`` session or a Transport.

    ``Transport`` keeps a scope-keyed ``jar`` dict; assigning everything to
    ``.apple.com`` silently drops the IDMSA half, which reads as "cookies all
    present but the session is dead".
    """
    jar = getattr(session, "jar", None)
    if isinstance(jar, dict):
        for name, value in (cookies or {}).items():
            if not value:
                continue
            scope = "idmsa" if name in IDMSA_COOKIES else "apple"
            jar.setdefault(scope, {})[name] = value
        return

    for name, value in (cookies or {}).items():
        if not value:
            continue
        try:
            session.cookies.set(name, value, domain=scope_for(name), path="/")
        except Exception:  # noqa: BLE001 - jar API differs across versions
            try:
                session.cookies.set(name, value)
            except Exception:  # noqa: BLE001
                pass


def snapshot_cookies(session, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Collect resume-relevant cookies from a ``curl_cffi`` session.

    ``extra`` carries values that never reach the jar — ``myacinfo`` arrives in
    a ``2sv/trust`` response header and is consumed before it can be stored.
    """
    out: dict[str, str] = {}
    for name, value in (extra or {}).items():
        if value:
            out[name] = value
    try:
        for cookie in session.cookies.jar:
            if cookie.value and is_persisted(cookie.name):
                out[cookie.name] = cookie.value
    except Exception:  # noqa: BLE001 - jar API differs across versions
        pass
    return out
