"""Session persistence + billing access for the rewritten protocol.

The protocol modules (``apple_exe_replica`` / ``apple_shld_v3`` /
``apple_store_client``) are verbatim copies of the verified clients and stay
stateless. This module is the glue the rest of butter talks to:

    read cookies      → rebuild a Transport without logging in again
    login             → run the full IDMSA + store chain, then persist
    fetch billing     → authenticated Graviton RPC, then persist the summary

Persistence lives in ``accounts.json`` through :class:`butter.core.store.AccountStore`,
so a restart resumes straight from the saved cookie jar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from curl_cffi import requests as creq

from ..core.store import Account, AccountStore
from .cookie_scope import (
    SESSION_COOKIES,
    is_session_cookie as _is_session_cookie,
    restore_session,
    snapshot_cookies,
)
from .apple_store_client import (
    STORE_BASE,
    StoreClient,
    detect_card_type,
    encrypt_card,
)

LOGGER = logging.getLogger("butter.session")

# Cookies that actually matter for resuming a store session. DES* is the Apple
# ID refresh token, myacinfo is the IDMSA session, as_disa is the store one.
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SavedSession:
    """What we persist so the next start skips the login chain."""

    email: str = ""
    cookies: dict[str, str] = field(default_factory=dict)
    stk: str = ""
    store_base: str = STORE_BASE
    saved_at: str = ""

    @property
    def has_login(self) -> bool:
        return any(_is_session_cookie(k) for k in self.cookies)

    @property
    def has_store(self) -> bool:
        return bool(self.cookies.get("as_disa"))




class SessionManager:
    """Persist / restore account sessions and expose billing reads.

    Live sessions are cached per email. This matters more than it looks: the
    store ties ``as_disa`` to the connection that minted it, so rebuilding a
    ``curl_cffi`` session from saved cookies — even redoing the whole SHLD +
    authx handshake — still answers ``SESSIONEXPIRY``. Reading through the
    original object keeps working, so the cache is the fast path and cookie
    replay is only a fallback for a cold process.
    """

    def __init__(self, store: AccountStore | None = None) -> None:
        self.store = store or AccountStore()
        self._live: dict[str, creq.Session] = {}
        self._clients: dict[str, StoreClient] = {}

    def attach(self, email: str, session: creq.Session, client: StoreClient) -> None:
        """Remember the live pair produced by a login handshake."""
        self._live[email.lower()] = session
        self._clients[email.lower()] = client

    def detach(self, email: str) -> None:
        self._live.pop(email.lower(), None)
        self._clients.pop(email.lower(), None)

    def live_client(self, email: str) -> StoreClient | None:
        return self._clients.get(email.lower())

    def live_socket(self, email: str):
        """Raw session behind :meth:`live_client` (the connection as_disa is bound to)."""
        return self._live.get(email.lower())

    # --- persistence ------------------------------------------------------
    def load(self, email: str) -> SavedSession:
        account = self.store.get(email)
        if not account:
            return SavedSession(email=email)
        return SavedSession(
            email=account.email,
            cookies=dict(account.cookies or {}),
            stk=account.stk or "",
            saved_at=account.last_login or "",
        )

    def save(
        self,
        email: str,
        session: creq.Session,
        *,
        stk: str = "",
        store_base: str = "",
        password: str | None = None,
        extra_cookies: dict[str, str] | None = None,
    ) -> SavedSession:
        """Write the live jar + stk back to ``accounts.json``."""
        cookies = snapshot_cookies(session, extra=extra_cookies)
        account = self.store.get(email) or Account(email=email)
        account.cookies = cookies
        account.stk = stk or account.stk
        if store_base:
            account.store_base = store_base
        account.logged_in = any(k.startswith("DES") or k == "myacinfo" for k in cookies)
        account.last_login = _now()
        account.status = "online" if account.logged_in else "idle"
        if password is not None:
            account.password = password
        self.store.upsert(account)
        saved = SavedSession(email=email, cookies=cookies, stk=account.stk,
                             store_base=store_base or STORE_BASE, saved_at=account.last_login)
        LOGGER.info(
            "[session] 已保存 %s | cookies=%s DES=%s store=%s",
            email,
            len(cookies),
            saved.has_login,
            saved.has_store,
        )
        return saved

    def clear(self, email: str) -> None:
        account = self.store.get(email)
        if not account:
            return
        account.cookies = {}
        account.stk = ""
        account.logged_in = False
        account.status = "idle"
        self.store.upsert(account)
        LOGGER.info("[session] 已清除 %s", email)

    def has_refresh_token(self, email: str) -> bool:
        """True when a long-lived DES token is on disk (silent re-auth possible)."""
        saved = self.load(email)
        return any(k.startswith("DES") for k in saved.cookies)

    def renew_store_session(self, email: str, proxy: str | None = None) -> bool:
        """Rebuild the store session from the saved DES token, without a password.

        ``as_disa`` is short-lived and bound to the connection that minted it, so
        once it dies the store answers an empty payload. The IDMSA half usually
        survives (DES lives 30 days after ``rememberMe``), which is enough to redo
        ``ssi → stk → SHLD → authx`` silently.
        """
        saved = self.load(email)
        if not any(k.startswith("DES") for k in saved.cookies):
            return False
        session = creq.Session(impersonate="chrome152_macos",
                               **({"proxy": proxy} if proxy else {}))
        restore_session(session, saved.cookies)
        client = StoreClient(session=session, base=saved.store_base or STORE_BASE)
        try:
            client.warmup_with_retry()
            client.authenticate()
        except Exception as exc:  # noqa: BLE001 - caller falls back to a login
            LOGGER.info("[session] 静默续期失败: %s", exc)
            return False
        self.attach(email, session, client)
        self.save(email, session, stk=client.stk or "", store_base=client.base)
        LOGGER.info("[session] 静默续期成功 %s", email)
        return True

    # --- billing ----------------------------------------------------------
    async def fetch_billing(self, email: str, proxy: str | None = None,
                            prefer_cache: bool = False) -> dict[str, Any]:
        """Resume the saved session and read the billing summary.

        Raises ``RuntimeError`` when there is nothing to resume — the caller is
        expected to run a login first.
        """
        saved = self.load(email)
        live = self.live_client(email)
        if not live and not saved.has_login and not saved.has_store:
            raise RuntimeError(f"{email} 没有可用的会话，请先登录")

        if live is not None:
            client = live
            session = self._live.get(email.lower())
        else:
            # Cold process: replay cookies and redo the store handshake. Note the
            # resulting as_disa is bound to this connection, so reads must keep
            # using the same object afterwards.
            session = creq.Session(impersonate="chrome152_macos",
                                   **({"proxy": proxy} if proxy else {}))
            restore_session(session, saved.cookies)
            client = StoreClient(session=session, base=saved.store_base or STORE_BASE)
            if saved.stk:
                client.stk = saved.stk
            self.attach(email, session, client)
            client.authenticate()

        try:
            # Billing lives behind fetchCustomerAccount, not fetchDashboard:
            # the dashboard only advertises the action URL and every pane it
            # inlines reports "Information about … is currently unavailable".
            info = client.fetch_billing_info()
        except Exception as exc:  # noqa: BLE001
            self.detach(email)
            raise RuntimeError(f"读取账单失败: {exc}") from exc
        finally:
            if session is not None:
                # Persist whatever the handshake added (as_disa, fresh stk, shld ck).
                self.save(email, session, stk=client.stk or "",
                          store_base=getattr(client, "base", ""))

        account = self.store.get(email)
        if account:
            account.billing_checked = True
            account.has_card = info["has_card"]
            account.card_suffix = info["card_suffix"]
            account.billing_updated_at = _now()
            self.store.upsert(account)
        LOGGER.info("[session] 账单 %s | has_card=%s suffix=%s", email,
                    info["has_card"], info["card_suffix"] or "-")
        return info

    async def save_billing(
        self,
        email: str,
        *,
        card_number: str,
        card_expiry: str,
        pub_key_b64: str,
        key_hash: str,
        address: dict[str, str],
        contact: dict[str, str],
        proxy: str | None = None,
    ) -> dict[str, Any]:
        """Write a card + address into the account's billing overlay."""
        saved = self.load(email)
        if not saved.has_login and not saved.has_store:
            raise RuntimeError(f"{email} 没有可用的会话，请先登录")

        session = creq.Session(impersonate="chrome152_macos",
                               **({"proxy": proxy} if proxy else {}))
        restore_session(session, saved.cookies)
        client = StoreClient(session=session, base=saved.store_base or STORE_BASE)
        if saved.stk:
            client.stk = saved.stk
        try:
            if not saved.has_store:
                client.authenticate()
            cipher = encrypt_card(card_number, pub_key_b64, key_hash)
            result, resp = client.save_billing(
                card_number=cipher,
                card_expiry=card_expiry,
                pub_key_b64=pub_key_b64,
                key_hash=key_hash,
                first_name=contact.get("firstName"),
                last_name=contact.get("lastName"),
                street=address.get("street"),
                city=address.get("city"),
                state=address.get("state"),
                zipcode=address.get("postalCode"),
                phone=contact.get("fullDaytimePhone"),
                country_code=address.get("countryCode", "US"),
            )
        finally:
            self.save(email, session, stk=client.stk, store_base=client.base)
        LOGGER.info("[session] 写卡 %s | type=%s status=%s", email,
                    detect_card_type(card_number), getattr(resp, "status_code", "?"))
        return {"ok": True, "steps": len(result or []), "result": result}


def summarise_billing(dashboard: dict | None, overlay: dict | None) -> dict[str, Any]:
    """Flatten dashboard + overlay into the fields the UI shows."""

    def dig(data: Any, key: str) -> Any:
        if isinstance(data, dict):
            if key in data:
                return data[key]
            for value in data.values():
                hit = dig(value, key)
                if hit is not None:
                    return hit
        elif isinstance(data, list):
            for item in data:
                hit = dig(item, key)
                if hit is not None:
                    return hit
        return None

    has_card = dig(dashboard, "removeBillingDetails") is not None or dig(overlay, "cardSuffix") is not None
    suffix = ""
    for key in ("cardSuffix", "lastFour", "lastFourDigits"):
        value = dig(overlay, key) or dig(dashboard, key)
        if value:
            suffix = str(value)
            break
    return {
        "has_card": bool(has_card),
        "card_suffix": suffix,
        "expiry": str(dig(overlay, "expiration") or ""),
        "card_number": str(dig(overlay, "cardNumber") or ""),
        "display_card_type": str(dig(overlay, "displayCardType") or ""),
        "first_name": str(dig(overlay, "firstName") or ""),
        "last_name": str(dig(overlay, "lastName") or ""),
        "street": str(dig(overlay, "street") or ""),
        "street2": str(dig(overlay, "street2") or ""),
        "city": str(dig(overlay, "city") or ""),
        "state": str(dig(overlay, "state") or ""),
        "postal_code": str(dig(overlay, "postalCode") or ""),
        "country_code": str(dig(overlay, "countryCode") or ""),
        "phone": str(dig(overlay, "fullDaytimePhone") or ""),
        "fetched_at": _now(),
    }
