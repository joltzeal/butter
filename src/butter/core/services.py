"""Domain services: login, billing fetch, billing update, session checks.

This is the orchestration layer that used to live inside Qt ``QThread`` workers.
Each operation is a plain coroutine so the API layer can push progress over a
WebSocket while the work runs; no thread pool and no Qt event loop involved.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..apple_auth import fingerprint as fp
from ..apple_auth.billing import (
    bin_detection_str,
    detect_card_type,
    encrypt_card_json,
    fill_address,
    normalize_card_expiry,
    validate_form,
)
from ..apple_auth.constants import STORE_BASE
from ..apple_auth.http import Transport, rotate_sid
from ..apple_auth.protocol_login import ProtocolLoginError, protocol_login
from ..apple_auth.cookie_scope import restore_session
from .bulk_import import parse_bulk
from .proxy import ProxyController
from .store import Account, AccountStore, Settings

LOGGER = logging.getLogger("butter.services")

RETRYABLE_MARKERS = (
    "503",
    "502",
    "504",
    "限流",
    "curl: (",
    "SSL",
    "TLS",
    "proxy",
    "timed out",
    "ConnectError",
    "Connection",
    "SOCKS",
    "network",
)


class EventSink(Protocol):
    def emit(self, event: str, payload: dict[str, Any]) -> None: ...


class NullSink:
    def emit(self, event: str, payload: dict[str, Any]) -> None:  # noqa: D401 - protocol stub
        return None


HSA2Provider = Callable[..., Awaitable[str | None]]


@dataclass
class LoginRequest:
    email: str
    password: str = ""
    note: str = ""
    persist: bool = True
    # Optional 2FA hooks: an inline code, or a URL that serves the 6 digits.
    code: str = ""
    code_url: str = ""
    force_legacy: bool = False


@dataclass
class BillingForm:
    card_number: str = ""
    card_expiry: str = ""
    first_name: str = ""
    last_name: str = ""
    street: str = ""
    street2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country_code: str = "US"
    phone: str = ""
    remove_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_number": self.card_number,
            "card_expiry": self.card_expiry,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "street": self.street,
            "street2": self.street2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country_code": self.country_code,
            "phone": self.phone,
            "remove_only": self.remove_only,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_retryable(message: str) -> bool:
    lowered = message.lower()
    return any(marker.lower() in lowered for marker in RETRYABLE_MARKERS)


def _cookies_for(account: Account) -> dict[str, str]:
    return {k: v for k, v in account.cookies.items()}


def _new_session(proxy: str | None):
    """curl_cffi session with the browser profile the store expects."""
    from curl_cffi import requests as creq

    return creq.Session(impersonate="chrome152_macos", **({"proxy": proxy} if proxy else {}))


def _snapshot(session, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Pull resume-relevant cookies out of a ``curl_cffi`` session."""
    from ..apple_auth.cookie_scope import snapshot_cookies

    return snapshot_cookies(session, extra=extra)



class Services:
    def __init__(
        self,
        settings: Settings,
        store: AccountStore,
        proxy: ProxyController,
        sink: EventSink | None = None,
        hsa2_provider: HSA2Provider | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.proxy = proxy
        self.sink: EventSink = sink or NullSink()
        self.hsa2_provider = hsa2_provider
        self.apply_fingerprint(self.settings.fd_client_info)
        self._locks: dict[str, asyncio.Lock] = {}
        # Emails mid-login; the liveness poll skips them.
        self._busy: set[str] = set()
        self._cancel_check = False
        self._check_running = False
        # Imported lazily: session.py imports core.store, so a module-level
        # import here would close the cycle.
        from ..apple_auth.session import SessionManager

        self.sessions = SessionManager(self.store)
        self._captcha: dict[str, bytes] = {}

    # --- helpers ----------------------------------------------------------
    def apply_fingerprint(self, raw: str) -> bool:
        """Pin (or clear) the browser fingerprint used by every request."""
        ok = fp.pin_fingerprint(raw)
        LOGGER.info("[services] fingerprint pinned=%s len=%s", bool(fp.pinned()), len(fp.pinned()))
        return ok

    def _lock(self, email: str) -> asyncio.Lock:
        return self._locks.setdefault(email.lower(), asyncio.Lock())

    def _mark_busy(self, email: str, busy: bool) -> None:
        """Flag an email as mid-login so the poller leaves its session alone.

        The set lives on the instance: recreating it per call (a ``hasattr``
        check on the wrong name) emptied it every time, so the guard never held
        and the poll raced the login's authx.
        """
        key = email.lower()
        if busy:
            self._busy.add(key)
        else:
            self._busy.discard(key)

    def _is_busy(self, email: str) -> bool:
        return email.lower() in self._busy

    def _transport(self, email: str = "") -> Transport:
        proxy_url = self.proxy.socks_url()
        if proxy_url and email:
            proxy_url = rotate_sid(proxy_url, sid=email.split("@")[0][:8], region=self.settings.line)
        return Transport(proxy=proxy_url, impersonate=self.settings.impersonate)

    def _proxy_url(self, account: Account | None = None) -> str | None:
        """Proxy for the verified chain, with a per-account sticky sid."""
        proxy_url = self.proxy.socks_url()
        if proxy_url and account is not None:
            proxy_url = rotate_sid(
                proxy_url, sid=account.email.split("@")[0][:8], region=self.settings.line
            )
        return proxy_url or None

    def _emit(self, event: str, **payload: Any) -> None:
        self.sink.emit(event, payload)

    # --- login ------------------------------------------------------------
    async def login(self, request: LoginRequest, retries: int | None = None) -> dict[str, Any]:
        account = self.store.get(request.email) or Account(email=request.email)
        if request.password:
            account.password = request.password
        if request.note:
            account.note = request.note
        if request.code_url:
            account.code_url = request.code_url
        # Persist up front: the account has to be visible in the list while the
        # login waits for a code, or the UI cannot surface the pending state.
        self.store.upsert(account)
        attempts = retries or max(1, self.settings.retry_attempts)
        last_error = ""

        # Verified protocol chain first (see PROTOCOL.md). The legacy async client
        # below is kept only as a fallback for accounts that need its repair path.
        self._emit("login.progress", email=account.email, attempt=1, stage="connect")
        self._mark_busy(account.email, True)
        try:
            result = await protocol_login(
                account.email,
                account.password,
                proxy=self._proxy_url(account),
                code_url=request.code_url or account.code_url,
                code=request.code,
                defer_store=True,
                progress=lambda stage: self._emit(
                    "login.progress", email=account.email, attempt=1, stage=stage
                ),
            )
        except ProtocolLoginError as exc:
            LOGGER.info("[login] 协议链在 %s 失败: %s", exc.stage, exc.detail)
            self._emit("login.done", email=account.email, ok=False, message=str(exc))
            return {"ok": False, "message": str(exc), "account": account.public()}

        if result.get("hsa2_required") and not result.get("ok"):
            # The automatic fetch produced nothing usable (no code_url, or the
            # endpoint timed out). Ask the operator for the digits instead of
            # failing the login.
            reason = (
                "没有可用的 2FA 链接，请手动输入设备上收到的验证码"
                if not (request.code_url or account.code_url)
                else "2FA 链接没有取到有效验证码，请手动输入"
            )
            self._emit("login.progress", email=account.email, attempt=1, stage="hsa2")
            code = await self._request_hsa2(account.email, reason)
            if not code:
                message = "已取消两步验证"
                self._emit("login.done", email=account.email, ok=False, message=message)
                return {"ok": False, "message": message, "account": account.public()}
            try:
                retried = await protocol_login(
                    account.email,
                    account.password,
                    proxy=self._proxy_url(account),
                    code=code,
                    progress=lambda stage: self._emit(
                        "login.progress", email=account.email, attempt=2, stage=stage
                    ),
                )
            except ProtocolLoginError as exc:
                self._emit("login.done", email=account.email, ok=False, message=str(exc))
                self._mark_busy(account.email, False)
                return {"ok": False, "message": str(exc), "account": account.public()}
            result = retried

        session = result.get("session")
        if session is not None:
            # myacinfo comes from the 2sv/trust response header, not the jar.
            cookies = _snapshot(session, {"myacinfo": result.get("myacinfo") or ""})
            account.cookies = cookies
            account.logged_in = bool(result.get("ok") or cookies.get("myacinfo"))
            account.last_login = _now()
            account.status = "online" if account.logged_in else "offline"
            account.stk = result.get("stk") or account.stk
            account.fingerprint = {
                "impersonate": self.settings.impersonate,
                "timezone": self.settings.timezone,
            }
            if request.persist:
                self.store.upsert(account)
            # Keep the live connection: as_disa is bound to it, so a rebuilt
            # session would answer SESSIONEXPIRY.
            from curl_cffi import requests as _creq

            from ..apple_auth.apple_store_client import StoreClient as _SC

            _client = _SC(session=session, base=result.get("store_base") or STORE_BASE)
            _client.stk = result.get("stk") or ""
            self.sessions.attach(account.email, session, _client)
            if result.get("store_pending"):
                # authx costs ~9s server-side; run it after the account is
                # already usable instead of blocking the login response.
                # Reuse the very client the login chain built: its jar holds
                # the shld cookies and page meta, and the edge binds as_disa
                # to this connection.
                self._spawn_store_handshake(account.email, result.get("client") or _client)
        self._emit("login.done", email=account.email, ok=account.logged_in, message=result["message"])
        if not result.get("store_pending"):
            self._mark_busy(account.email, False)
        return {"ok": account.logged_in, "message": result["message"], "account": account.public()}

        return {"ok": False, "message": last_error or "登录失败", "account": account.public()}

    async def _request_hsa2(self, email: str, reason: str = "") -> str | None:
        if self.hsa2_provider is None:
            return None
        try:
            return await self.hsa2_provider(email, reason)
        except TypeError:
            # Provider written against the older single-argument signature.
            return await self.hsa2_provider(email)
        return await self.hsa2_provider(email)

    async def fetch_billing(self, email: str) -> dict[str, Any]:
        """Read billing. One path only — no cache fallback, no cooldown shortcut.

        A billing read either returns what Apple answered right now, or it
        reports an error. Serving a remembered copy (or silently degrading on a
        transient failure) would let the pane disagree with the real account
        state, which is exactly what we must not do.
        """
        account = self.store.get(email)
        if account is None:
            return {"ok": False, "message": "账号不存在"}

        async with self._lock(email):
            client, owns = self._billing_client(account)
            try:
                self._emit("billing.progress", email=email, stage="dashboard")
                await asyncio.to_thread(self._prepare_client, account, client, owns)
                info = await asyncio.to_thread(client.fetch_billing_info)
            except Exception as exc:  # noqa: BLE001 - surface the real reason
                LOGGER.warning("fetch_billing failed: %s", exc)
                self.sessions.detach(email)
                account.status = "offline"
                self.store.save()
                self._emit("billing.failed", email=email, message=str(exc))
                return {"ok": False, "message": str(exc) or exc.__class__.__name__}

            account.billing_checked = True
            account.has_card = bool(info.get("has_card"))
            account.card_suffix = str(info.get("card_suffix") or "")
            account.billing_updated_at = _now()
            account.logged_in = True
            account.status = "online"
            self.store.save()
            if owns:
                self.sessions.attach(email, client.s, client)
            self.sessions.save(email, client.s, stk=client.stk or "",
                               store_base=getattr(client, "base", ""))
            self._emit("billing.fetched", email=email, info=info)
            return {"ok": True, "info": info, "account": account.public()}

    async def _fetch_billing_live(self, account: Account, client) -> dict[str, Any]:
        """Read billing over the connection that minted as_disa."""
        email = account.email
        try:
            self._emit("billing.progress", email=email, stage="dashboard")
            # fetchCustomerAccount is the real source; fetchDashboard only
            # advertises the action and every inlined pane reports unavailable.
            info = client.fetch_billing_info()
            if info.get("error"):
                raise RuntimeError(f"商店暂未返回账单信息：{info['error']}")
            account.billing_checked = True
            account.has_card = bool(info.get("has_card"))
            account.card_suffix = str(info.get("card_suffix") or "")
            account.billing_updated_at = _now()
            account.logged_in = True
            account.status = "online"
            self.store.save()
            self._emit("billing.fetched", email=email, info=info)
            return {"ok": True, "info": info, "account": account.public()}
        except Exception as exc:  # noqa: BLE001
            self.sessions.detach(email)
            account.status = "offline"
            self.store.save()
            self._emit("billing.failed", email=email, message=str(exc), session_expired=True)
            return {"ok": False, "message": str(exc), "session_expired": True}


    # --- background keep-alive -------------------------------------------
    def start_poll(self) -> None:
        """Start the session liveness poller (idempotent)."""
        if getattr(self, "_poll_task", None) is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            LOGGER.debug("[poll] 无事件循环，未启动")
            return
        self._poll_task = loop.create_task(self._session_poll_loop())
        LOGGER.info("[poll] 已启动 | 每 %s 秒", self.settings.session_poll_seconds)

    def stop_poll(self) -> None:
        task = getattr(self, "_poll_task", None)
        if task is not None:
            task.cancel()
            self._poll_task = None

    async def _session_poll_loop(self) -> None:
        """Liveness poll.

        A billing session dies within minutes, and without this the list kept
        showing "在线" for an account that could no longer answer. Each tick
        sends one cheap RPC per live account and records what actually came
        back; the UI follows the recorded status instead of guessing from
        ``logged_in``, which only says a login once succeeded.
        """
        self._poll_strikes: dict[str, int] = {}
        while True:
            await asyncio.sleep(max(5, int(self.settings.session_poll_seconds or 20)))
            if not self.settings.session_poll:
                continue
            for account in [a for a in self.store.accounts if a.logged_in]:
                # A login is mid-handshake; probing now would race its authx and
                # rotate the x-aos-stk out from under it.
                if self._is_busy(account.email):
                    continue
                try:
                    async with self._lock(account.email):
                        await self._poll_one(account)
                except Exception as exc:  # noqa: BLE001 - never kill the loop
                    LOGGER.debug("[poll] %s: %s", account.email, exc)

    # One miss is noise; two in a row means the session is really gone.
    _POLL_STRIKES = 2

    async def _poll_one(self, account: Account) -> None:
        def probe(handshake: bool) -> bool:
            client = self.sessions.live_client(account.email)
            if client is None:
                return False
            try:
                if client.alive_payload():
                    return True
                if not handshake:
                    return False
                # A live-but-degraded session (rotated stk / expired as_disa) can
                # still be revived in place; only then call it offline.
                client.authenticate()
                self.sessions.save(account.email, client.s, stk=client.stk or "",
                                   store_base=getattr(client, "base", ""))
                return bool(client.alive_payload())
            except Exception:  # noqa: BLE001 - any error means "not answering"
                return False

        alive = await asyncio.to_thread(probe, True)
        if alive:
            self._poll_strikes[account.email] = 0
            if account.status != "online":
                account.status = "online"
                self.store.save()
                self._emit("account.status", email=account.email, status="online")
            return

        self._poll_strikes[account.email] = self._poll_strikes.get(account.email, 0) + 1
        if self._poll_strikes[account.email] < self._POLL_STRIKES:
            return
        if account.status == "offline":
            return
        account.status = "offline"
        self.sessions.detach(account.email)
        self.store.save()
        self._emit("account.status", email=account.email, status="offline")
        LOGGER.info("[poll] %s -> offline", account.email)

    def _spawn_store_handshake(self, email: str, client) -> None:
        """Finish the store handshake off the request path."""

        async def run() -> None:
            self._emit("login.progress", email=email, stage="store")
            try:
                # The login chain hands back its own IdmsaClient, which already
                # knows ssi / stk / shld for this connection. Calling its
                # step_acquire_as_disa is what the synchronous flow does inline;
                # a freshly built StoreClient would answer 541.
                acquire = getattr(client, "step_acquire_as_disa", None)
                if acquire is not None:
                    state = getattr(client, "state", None)
                    await asyncio.to_thread(acquire)
                    ok = bool(getattr(state, "as_disa", ""))
                    if ok:
                        # authx rotates x-aos-stk and issues as_disa; the store
                        # client still holds the pre-authx values, which answer
                        # 541. Push the fresh ones onto it before anything probes.
                        live = self.sessions.live_client(email)
                        if live is not None:
                            live.stk = getattr(state, "stk", "") or ""
                            live.as_disa = getattr(state, "as_disa", "") or ""
                            live.as_sfa = getattr(state, "as_sfa", "") or ""
                            if getattr(client, "store_base", ""):
                                live.base = client.store_base
                    if ok:
                        self.sessions.save(
                            email,
                            client.s,
                            stk=getattr(state, "stk", "") or "",
                            store_base=getattr(client, "store_base", ""),
                        )
                else:
                    ok = await asyncio.to_thread(client.prepare)
            except Exception as exc:  # noqa: BLE001 - the next billing call retries
                LOGGER.info("[login] 后台 store 握手失败 %s: %s", email, exc)
                self._emit("login.done", email=email, ok=True,
                           message="已登录（账单需要手动刷新）")
                self._mark_busy(email, False)
                return
            if not ok:
                LOGGER.info("[login] 后台 store 握手未成功 %s", email)
            # Refresh the cache so the panel shows reality instead of the empty
            # shell a previous failed read may have left behind.
            live = self.sessions.live_client(email)
            if live is not None and ok:
                try:
                    info = await asyncio.to_thread(live.fetch_billing_info)
                    account_now = self.store.get(email)
                    if account_now is not None:
                        account_now.has_card = bool(info.get("has_card"))
                        account_now.card_suffix = str(info.get("card_suffix") or "")
                        account_now.billing_checked = True
                        self.store.save()
                        self._emit("billing.fetched", email=email, info=info)
                except Exception as exc:  # noqa: BLE001 - best effort
                    LOGGER.info("[login] 登录后读账单失败 %s: %s", email, exc)

            stk_now = getattr(getattr(client, "state", None), "stk", "") or \
                getattr(client, "stk", "") or ""
            self.sessions.save(email, client.s, stk=stk_now,
                               store_base=getattr(client, "store_base", "")
                               or getattr(client, "base", ""))
            self._mark_busy(email, False)
            self._emit("login.done", email=email, ok=True,
                       message="已登录，账单可用")

        try:
            asyncio.get_running_loop().create_task(run())
        except RuntimeError:  # no loop (sync caller) — leave it to the next call
            LOGGER.debug("[login] 无事件循环，跳过后台握手")

    def _billing_client(self, account: Account):
        """Return (client, owns_session) backed by the verified sync client.

        The async transport keeps its own cookie dict and loses the attributes
        the store edge validates, so authenticated RPCs there come back as
        SESSIONEXPIRY. The sync client uses curl_cffi's native jar and is what
        has been verified end to end, so billing always goes through it.
        """
        from ..apple_auth.apple_store_client import StoreClient as SyncStoreClient
        from ..apple_auth.session import SessionManager as _SM  # noqa: F401

        live = self.sessions.live_client(account.email)
        live_session = self.sessions.live_socket(account.email)
        if live is not None and live_session is not None:
            return live, False

        saved = self.sessions.load(account.email)
        session = _new_session(self._proxy_url(account))
        restore_session(session, saved.cookies)
        client = SyncStoreClient(session=session, base=saved.store_base or STORE_BASE)
        client.stk = saved.stk
        # Seed the risk tokens so prepare() can probe instead of re-handshaking.
        client.as_disa = saved.cookies.get("as_disa", "")
        client.as_sfa = saved.cookies.get("as_sfa", "")
        return client, True

    def _prepare_client(self, account: Account, client, owns: bool) -> None:
        """Make sure ``client`` can talk to the store, handshaking only if needed.

        A restored ``as_disa`` is tried first: re-running authx when the session
        is still alive makes the edge answer 541 and looks like a hard failure.
        """
        if not owns:
            return
        if client.fast_probe(account.store_base) or client.as_disa:
            if client.alive_payload():
                account.store_base = getattr(client, "base", "") or account.store_base
                return
        if not client.fast_probe(account.store_base):
            client.warmup_with_retry()
        client.authenticate()
        account.store_base = getattr(client, "base", "") or account.store_base

    async def update_billing(self, email: str, form: BillingForm) -> dict[str, Any]:
        account = self.store.get(email)
        if account is None:
            return {"ok": False, "message": "账号不存在"}
        if not form.remove_only:
            missing = validate_form(form.as_dict())
            if missing:
                return {"ok": False, "message": f"缺少字段: {', '.join(missing)}"}

        async with self._lock(email):
            client, own_session = self._billing_client(account)
            session = client.s
            try:
                self._emit("billing.progress", email=email, stage="connect")
                await asyncio.to_thread(self._prepare_client, account, client, own_session)

                if form.remove_only:
                    self._emit("billing.progress", email=email, stage="remove")
                    await asyncio.to_thread(client.remove_billing)
                    return await self._confirm(account, client, session,
                                               expected_card=None,
                                               success="已移除付款方式")

                # The card is encrypted with the key the overlay advertises.
                self._emit("billing.progress", email=email, stage="rsa-config")
                edit = client._gcall("editBillingDetails",
                                     "home.customerAccount.billingInfo")
                try:
                    edit_payload = edit.json()
                except Exception:  # noqa: BLE001
                    edit_payload = {}
                public_key = _find_key(edit_payload, "publicKey")
                key_hash = _find_key(edit_payload, "publicKeyHash") or ""
                if not public_key:
                    # Fall back to the key published on the account overlay.
                    ca = client.fetch_customer_account()
                    public_key = _find_key(ca, "publicKey")
                    key_hash = key_hash or (_find_key(ca, "publicKeyHash") or "")
                if not public_key:
                    return {"ok": False, "message": "拿不到加密公钥，请重新登录后重试"}

                self._emit("billing.progress", email=email, stage="save")
                payload, resp = await asyncio.to_thread(
                    client.save_billing,
                    form.card_number.replace(" ", ""),
                    form.card_expiry,
                    public_key,
                    key_hash,
                    form.first_name,
                    form.last_name,
                    form.street,
                    form.street2,
                    form.city,
                    form.state,
                    form.postal_code,
                    form.phone,
                    (form.country_code or "US").upper(),
                )
                digits = form.card_number.replace(" ", "")
                # The save response only says "accepted"; re-read to learn what
                # the account actually holds now.
                return await self._confirm(account, client, session,
                                           expected_card=digits[-4:],
                                           success=f"账单已更新 · 尾号 {digits[-4:]}")
            except Exception as exc:  # noqa: BLE001 - the caller shows the real reason
                LOGGER.exception("update_billing failed")
                message = str(exc) or exc.__class__.__name__
                self._emit("billing.failed", email=email, message=message)
                return {"ok": False, "message": message}
            finally:
                if own_session:
                    with contextlib.suppress(Exception):
                        session.close()

    async def _confirm(self, account: Account, client, session,
                       expected_card: str | None, success: str) -> dict[str, Any]:
        """Re-read after a mutation and report what the server really has.

        A 200 on save only means "accepted". Without this the UI showed the form
        values back as if the write had landed, which is how a rejected save
        looked identical to a good one.
        """
        self._emit("billing.progress", email=account.email, stage="verify")
        info = await asyncio.to_thread(client.fetch_billing_info)

        if expected_card is None:
            if info.get("has_card"):
                return {
                    "ok": False,
                    "info": info,
                    "message": "服务器仍报告有付款方式，移除未生效",
                }
        elif not info.get("has_card"):
            return {"ok": False, "info": info, "message": "保存后服务器上仍然没有付款方式"}
        elif info.get("card_suffix") and info["card_suffix"] != expected_card:
            return {
                "ok": False,
                "info": info,
                "message": f"服务器上的卡号是 {info['card_suffix']}，不是 {expected_card}",
            }

        account.has_card = bool(info.get("has_card"))
        account.card_suffix = str(info.get("card_suffix") or "")
        account.billing_checked = True
        account.billing_updated_at = _now()
        account.store_base = getattr(client, "base", "")
        self.store.save()
        self.sessions.save(account.email, session, stk=client.stk or "",
                           store_base=getattr(client, "base", ""))
        self._emit("billing.updated", email=account.email, removed=expected_card is None)
        return {"ok": True, "message": success, "info": info,
                "account": account.public()}

    # --- session health ---------------------------------------------------
    async def check_session(self, email: str) -> dict[str, Any]:
        account = self.store.get(email)
        if account is None:
            return {"ok": False, "message": "账号不存在"}

        client, owns = self._billing_client(account)
        try:
            await asyncio.to_thread(self._prepare_client, account, client, owns)
            await asyncio.to_thread(client.fetch_billing_info)
        except Exception as exc:  # noqa: BLE001 - any failure means "offline"
            account.status = "offline"
            account.logged_in = False
            self.store.save()
            return {"ok": False, "status": "offline", "message": str(exc)}

        account.status = "online"
        account.logged_in = True
        self.store.save()
        if owns:
            self.sessions.attach(email, client.s, client)
        return {"ok": True, "status": "online"}

    async def check_sessions(self, emails: list[str] | None = None, top: int | None = None) -> dict[str, Any]:
        # Explicit selection only — see batch_relogin for the reasoning.
        if not emails:
            return {"ok": False, "results": [], "message": "请先勾选要检测的账号"}
        targets = emails[: top or self.settings.session_check_top]
        self._cancel_check = False
        self._check_running = True
        results = []
        for email in targets:
            if self._cancel_check:
                LOGGER.info("[session] 检测已取消")
                break
            self._emit("session.progress", email=email)
            results.append({"email": email, **await self.check_session(email)})
            await asyncio.sleep(0.4)
        self._check_running = False
        self._emit("session.done", count=len(results), offline=sum(1 for r in results if not r.get("ok")))
        return {"ok": True, "results": results}

    def cancel_check(self) -> bool:
        """Ask a running session check to stop after the current account."""
        if not getattr(self, "_check_running", False):
            return False
        self._cancel_check = True
        return True

    async def batch_relogin(self, emails: list[str] | None = None) -> dict[str, Any]:
        # Never fan out to every account implicitly: a batch login costs a full
        # handshake each, and silencing the whole list has burned the throttle
        # before. The caller must name the accounts.
        if not emails:
            return {"ok": False, "count": 0, "message": "请先勾选要重登的账号"}
        targets = emails
        finished = 0
        for account in self.store.accounts:
            if account.email not in targets:
                continue
            self._emit("batch.progress", email=account.email, index=finished + 1, total=len(targets))
            self._emit("login.progress", email=account.email, stage="connect",
                       index=finished + 1, total=len(targets))
            await self.login(LoginRequest(email=account.email, password=account.password))
            finished += 1
        self._emit("batch.done", count=finished)
        return {"ok": True, "count": finished}

    async def import_bulk(self, text: str) -> dict[str, Any]:
        """Create accounts from a strict multi-line paste, then log them in.

        Validation is all-or-nothing: any malformed line aborts the import so a
        bad paste cannot leave half a batch behind.
        """
        parsed = parse_bulk(text)
        if parsed.errors:
            return {
                "ok": False,
                "message": f"{len(parsed.errors)} 行格式不正确，已取消导入",
                "errors": [
                    {"line": e.line, "text": e.text[:120], "reason": e.reason}
                    for e in parsed.errors
                ],
                "created": 0,
            }

        created: list[str] = []
        updated: list[str] = []
        for item in parsed.accounts:
            existing = self.store.get(item.email)
            account = existing or Account(email=item.email)
            account.password = item.password
            account.code_url = item.code_url
            account.status = account.status or "idle"
            self.store.upsert(account)
            (updated if existing else created).append(item.email)

        self._emit("bulk.imported", created=len(created), updated=len(updated))

        total = len(parsed.accounts)
        for index, item in enumerate(parsed.accounts, start=1):
            self._emit("bulk.progress", email=item.email, index=index, total=total)
            await self.login(
                LoginRequest(
                    email=item.email,
                    password=item.password,
                    code_url=item.code_url,
                    persist=True,
                )
            )

        self._emit("bulk.done", count=total)
        return {
            "ok": True,
            "message": f"已导入 {total} 个账号（新增 {len(created)}，更新 {len(updated)}）",
            "created": len(created),
            "updated": len(updated),
            "accounts": created + updated,
        }

    @contextlib.asynccontextmanager
    def captcha_buffer(self, email: str) -> AsyncIterator[bytes]:
        yield self._captcha.get(email, b"")

    def store_captcha(self, email: str, data: bytes) -> None:
        self._captcha[email] = data


def _find_key(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None
