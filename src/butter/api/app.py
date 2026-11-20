"""FastAPI application: REST + WebSocket control plane for the Tauri shell.

Design notes
------------
* The backend binds ``127.0.0.1`` only, on a port handed down by the Rust shell
  (``BUTTER_PORT``) or the first free port in ``7860-7960``.
* Every mutating call is idempotent enough to be retried by the UI.
* Long operations stream progress on ``/ws`` as JSON envelopes
  ``{"event": "...", "payload": {...}, "ts": "..."}``.
* Secrets are never returned: account payloads redact the password and only
  expose cookie *names*.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dataclasses import asdict

from ..apple_auth import fingerprint as fp
from ..apple_auth.http import HAS_CURL_CFFI
from ..core.address_parser import parse_clipboard
from ..core.proxy import ProxyController, build_profile, find_free_port, port_alive
from ..core.services import BillingForm, LoginRequest, Services
from ..core.store import Account, AccountStore, Settings, data_dir
from .models import AccountIn, AccountOut, AccountUpdate, BillingFormIn, BulkIn, BulkOut, CheckIn, ClashRotateIn, ClashSelectIn, Hsa2In, LoginIn, ParseOut, PasteIn, ReorderIn, SettingsIn

LOGGER = logging.getLogger("butter.api")

# The Tauri webview uses a privileged scheme; Vite dev serves from localhost.
# Both are loopback-owned, so a bounded regex is safer than "*" with credentials.
CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


class Broadcaster:
    """Fan-out of progress events to every connected UI."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def send(self, event: str, payload: dict[str, Any]) -> None:
        envelope = {"event": event, "payload": payload, "ts": datetime.now(UTC).isoformat(timespec="seconds")}
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(json.dumps(envelope, ensure_ascii=False, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    def sink(self):
        hub = self

        class _Sink:
            def emit(self, event: str, payload: dict[str, Any]) -> None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                loop.create_task(hub.send(event, payload))

        return _Sink()

    @property
    def count(self) -> int:
        return len(self._clients)


class AppState:
    def __init__(self) -> None:
        self.settings = Settings.load()
        self.store = AccountStore()
        self.proxy = ProxyController(self.settings)
        self.hub = Broadcaster()
        self.services = Services(self.settings, self.store, self.proxy, sink=self.hub.sink())
        self.pending_hsa2: dict[str, asyncio.Future[str | None]] = {}
        self.services.hsa2_provider = self._await_hsa2

    async def _await_hsa2(self, email: str, reason: str = "") -> str | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | None] = loop.create_future()
        self.pending_hsa2[email.lower()] = future
        # ``reason`` tells the dialog why the automatic fetch did not happen.
        LOGGER.info("[hsa2] 等待验证码 %s (clients=%s)", email, len(self.hub._clients))
        await self.hub.send("login.hsa2", {"email": email, "reason": reason})
        try:
            code = await asyncio.wait_for(future, timeout=300)
            LOGGER.info("[hsa2] 结束 %s -> %s", email, code or "取消/超时")
            return code
        except TimeoutError:
            return None
        finally:
            self.pending_hsa2.pop(email.lower(), None)

    def submit_hsa2(self, email: str, code: str) -> bool:
        LOGGER.info("[hsa2] submit %s code=%r", email, code)
        future = self.pending_hsa2.get(email.lower())
        if future and not future.done():
            future.set_result(code)
            return True
        return False

    def serialize(self, account: Account) -> AccountOut:
        public = account.public()
        return AccountOut(**{k: public[k] for k in AccountOut.model_fields if k in public})


state: AppState | None = None


def get_state() -> AppState:
    if state is None:  # pragma: no cover - guarded by lifespan
        raise RuntimeError("app state not initialised")
    return state


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global state
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("BUTTER_DEBUG") else logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    )
    state = AppState()
    state.services.start_poll()
    LOGGER.info("butter backend ready | data=%s curl_cffi=%s", data_dir(), HAS_CURL_CFFI)
    try:
        yield
    finally:
        state.services.stop_poll()
        state.proxy.stop()


def create_app() -> FastAPI:
    from .. import __version__ as _ver

    app = FastAPI(title="butter", version=_ver, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=CORS_ORIGIN_REGEX,
        allow_origins=[
            "tauri://localhost",
            "https://tauri.localhost",
            "http://tauri.localhost",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # --- meta -------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        st = get_state()
        return {
            "ok": True,
            "version": "0.1.0",
            "curl_cffi": HAS_CURL_CFFI,
            "data_dir": str(data_dir()),
            "clients": st.hub.count,
            "proxy": st.proxy.status().as_dict(),
            "fingerprint_pinned": bool(fp.pinned()),
        }

    @app.post("/api/sessions/check/cancel")
    async def cancel_check() -> dict[str, Any]:
        ok = get_state().services.cancel_check()
        return {"ok": ok, "message": "已取消" if ok else "没有运行中的检测"}

    @app.post("/api/accounts/{email}/login/cancel")
    async def cancel_login(email: str) -> dict[str, Any]:
        """Abort the step the login is waiting on.

        Resolving the pending 2FA future makes ``_await_hsa2`` return None, which
        the login treats as "cancelled" and unwinds normally.
        """
        st = get_state()
        LOGGER.info("[hsa2] cancel %s", email)
        future = st.pending_hsa2.pop(email.lower(), None)
        if future is not None and not future.done():
            future.set_result(None)
            st.services._mark_busy(email, False)
            return {"ok": True, "message": "已取消"}
        return {"ok": False, "message": "没有等待中的登录"}

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        from .. import __version__ as ver

        return {"version": ver}

    @app.get("/api/accounts", response_model=list[AccountOut])
    async def list_accounts() -> list[AccountOut]:
        st = get_state()
        out = []
        for account in st.store.accounts:
            payload = st.serialize(account)
            payload.awaiting_hsa2 = account.email.lower() in st.pending_hsa2
            out.append(payload)
        return out

    @app.post("/api/accounts", response_model=AccountOut)
    async def create_account(payload: AccountIn) -> AccountOut:
        st = get_state()
        email = payload.email.strip()
        if not email:
            raise HTTPException(400, "email required")
        # Case-insensitive: Apple IDs are not case sensitive, and a second row
        # for the same person would split their session and billing state.
        if any(a.email.lower() == email.lower() for a in st.store.accounts):
            raise HTTPException(409, f"{email} 已在列表中")
        account = Account(email=email, password=payload.password, note=payload.note)
        # Write first, then let the login run: the row must exist even if the
        # login never completes (2FA abandoned, wrong password).
        st.store.upsert(account)
        return st.serialize(account)

    @app.patch("/api/accounts/{email}", response_model=AccountOut)
    async def update_account(email: str, payload: AccountUpdate) -> AccountOut:
        st = get_state()
        account = st.store.get(email)
        if account is None:
            raise HTTPException(404, "account not found")
        if payload.password is not None:
            account.password = payload.password
        if payload.note is not None:
            account.note = payload.note
        st.store.save()
        return st.serialize(account)

    @app.delete("/api/accounts/{email}")
    async def delete_account(email: str) -> dict[str, bool]:
        st = get_state()
        return {"removed": st.store.remove(email)}

    @app.post("/api/accounts/reorder")
    async def reorder_accounts(payload: ReorderIn) -> dict[str, bool]:
        get_state().store.reorder(payload.emails)
        return {"ok": True}

    # --- login ------------------------------------------------------------
    @app.post("/api/accounts/login")
    async def login(payload: LoginIn) -> dict[str, Any]:
        st = get_state()
        if st.services._is_busy(payload.email.strip()):
            # A second attempt would overwrite pending_hsa2 and strand the first.
            return {"ok": False, "message": "该账号正在登录中"}
        result: dict[str, Any] | None = None
        try:
            result = await st.services.login(
                LoginRequest(
                    email=payload.email.strip(),
                    password=payload.password,
                    note=payload.note,
                    persist=payload.persist,
                    code=payload.code,
                    code_url=payload.code_url,
                    force_legacy=payload.force_legacy,
                )
            )
            return result
        finally:
            # The background handshake owns the flag when one was spawned;
            # every other exit (error, cancel, 2FA abandoned) must release it or
            # the account stays "logging in" forever.
            if not (result and result.get("store_pending")):
                st.services._mark_busy(payload.email.strip(), False)

    @app.post("/api/accounts/{email}/hsa2")
    async def hsa2(email: str, payload: Hsa2In) -> dict[str, bool]:
        return {"accepted": get_state().submit_hsa2(email, payload.code.strip())}

    @app.post("/api/accounts/bulk", response_model=BulkOut)
    async def bulk_import(payload: BulkIn) -> BulkOut:
        return BulkOut(**await get_state().services.import_bulk(payload.text))

    @app.post("/api/accounts/batch-relogin")
    async def batch_relogin(payload: CheckIn) -> dict[str, Any]:
        return await get_state().services.batch_relogin(payload.emails)

    # --- billing ----------------------------------------------------------
    @app.get("/api/accounts/{email}/billing")
    async def get_billing(email: str) -> dict[str, Any]:
        return await get_state().services.fetch_billing(email)

    @app.put("/api/accounts/{email}/billing")
    async def put_billing(email: str, payload: BillingFormIn) -> dict[str, Any]:
        form = BillingForm(**payload.model_dump())
        return await get_state().services.update_billing(email, form)

    @app.delete("/api/accounts/{email}/billing")
    async def delete_billing(email: str) -> dict[str, Any]:
        form = BillingForm(remove_only=True)
        return await get_state().services.update_billing(email, form)

    # --- sessions ---------------------------------------------------------
    @app.post("/api/sessions/check")
    async def check_sessions(payload: CheckIn) -> dict[str, Any]:
        return await get_state().services.check_sessions(payload.emails)

    @app.post("/api/accounts/{email}/session")
    async def check_session(email: str) -> dict[str, Any]:
        return await get_state().services.check_session(email)

    # --- clipboard --------------------------------------------------------
    @app.post("/api/paste", response_model=ParseOut)
    async def parse_paste(payload: PasteIn) -> ParseOut:
        fields = parse_clipboard(payload.text)
        return ParseOut(fields=fields, count=len(fields))

    # --- settings / proxy -------------------------------------------------
    @app.get("/api/settings")
    async def read_settings() -> dict[str, Any]:
        st = get_state()
        data = asdict(st.settings)
        data["proxy_pass"] = "***" if data.get("proxy_pass") else ""
        return data

    @app.put("/api/settings")
    async def write_settings(payload: SettingsIn) -> dict[str, Any]:
        st = get_state()
        for key, value in payload.model_dump(exclude_none=True).items():
            if key == "proxy_pass" and value == "***":
                continue
            setattr(st.settings, key, value)
        st.settings.save()
        if payload.fd_client_info is not None:
            ok = st.services.apply_fingerprint(payload.fd_client_info)
            if not ok:
                raise HTTPException(400, "指纹格式无效（应为 #fdcBrowserData 的 JSON 或纯 F 串）")
        return {"ok": True}

    @app.get("/api/proxy/preview")
    async def preview_profile() -> JSONResponse:
        st = get_state()
        try:
            profile = build_profile(st.settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(profile)

    @app.post("/api/proxy/start")
    async def start_proxy() -> dict[str, Any]:
        st = get_state()
        status = await asyncio.to_thread(st.proxy.start)
        return status.as_dict()

    @app.post("/api/proxy/stop")
    async def stop_proxy() -> dict[str, Any]:
        st = get_state()
        await asyncio.to_thread(st.proxy.stop)
        return st.proxy.status().as_dict()

    # --- existing mihomo/Clash core (REST control) -------------------------
    def _controller():
        st = get_state()
        from ..core.clash import ClashController, ClashError

        try:
            return ClashController(st.settings.clash_api, st.settings.clash_secret)
        except ClashError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/clash/status")
    async def clash_status(probe: bool = False) -> dict[str, Any]:
        from ..core.clash import ClashError

        try:
            ctl = _controller()
            version = await ctl.version()
            groups = await ctl.groups()
            try:
                nodes = await ctl.nodes(limit=500)
            except Exception:  # noqa: BLE001 - node list is optional telemetry
                nodes = []
            return {"ok": True, "version": version, "groups": groups, "nodes": [n.as_dict() for n in nodes]}
        except ClashError as exc:
            return {"ok": False, "message": str(exc), "groups": [], "nodes": []}

    @app.get("/api/clash/nodes")
    async def clash_nodes(keyword: str = "", limit: int = 400) -> dict[str, Any]:
        from ..core.clash import ClashError

        try:
            nodes = await _controller().nodes(keyword=keyword, limit=limit)
            return {"ok": True, "nodes": [n.as_dict() for n in nodes]}
        except ClashError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/clash/select")
    async def clash_select(payload: ClashSelectIn) -> dict[str, Any]:
        from ..core.clash import ClashError

        group = payload.group or get_state().settings.clash_group
        if not group:
            raise HTTPException(400, "缺少 group（设置里也没配 clash_group）")
        try:
            now = await _controller().select(group, payload.node)
        except ClashError as exc:
            raise HTTPException(502, str(exc)) from exc
        await get_state().hub.send("clash.selected", {"group": group, "node": now})
        return {"ok": True, "group": group, "now": now}

    @app.post("/api/clash/rotate")
    async def clash_rotate(payload: ClashRotateIn) -> dict[str, Any]:
        """Round-robin to the next alive member of the group (batch accounts)."""
        from ..core.clash import ClashError

        st = get_state()
        group = payload.group or st.settings.clash_group
        if not group:
            raise HTTPException(400, "缺少 group（设置里也没配 clash_group）")
        try:
            ctl = _controller()
            groups = {g["name"]: g for g in await ctl.groups()}
            members = groups.get(group, {}).get("members", [])
            keyword = payload.keyword.lower()
            candidates = [
                member
                for member in members
                if member not in ("DIRECT", "REJECT", "PASS") and (not keyword or keyword in member.lower())
            ]
            if not candidates:
                raise HTTPException(400, f"组 {group} 没有可用节点")
            index = 0
            if payload.stride:
                current = await ctl.current(group)
                if current in candidates:
                    index = (candidates.index(current) + payload.stride) % len(candidates)
            now = await ctl.select(group, candidates[index])
        except ClashError as exc:
            raise HTTPException(502, str(exc)) from exc
        await st.hub.send("clash.selected", {"group": group, "node": now})
        return {"ok": True, "group": group, "now": now, "total": len(candidates)}

    @app.get("/api/proxy/status")
    async def proxy_status() -> dict[str, Any]:
        st = get_state()
        status = st.proxy.status()
        data = status.as_dict()
        if status.port:
            data["alive"] = port_alive(status.port)
        return data

    # --- realtime ---------------------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        st = get_state()
        await st.hub.connect(ws)
        try:
            await ws.send_text(
                json.dumps({"event": "hello", "payload": {"clients": st.hub.count}, "ts": datetime.now(UTC).isoformat()})
            )
            while True:
                message = await ws.receive_text()
                if message == "ping":
                    await ws.send_text(json.dumps({"event": "pong", "payload": {}}))
        except WebSocketDisconnect:
            await st.hub.disconnect(ws)
        except Exception:
            await st.hub.disconnect(ws)

    return app


def pick_port() -> int:
    env = os.environ.get("BUTTER_PORT", "")
    if env.isdigit():
        return int(env)
    return find_free_port(7860, 7960)


def main() -> None:
    import uvicorn

    port = pick_port()
    host = os.environ.get("BUTTER_HOST", "127.0.0.1")
    print(f"BUTTER_READY http://{host}:{port}", flush=True)
    uvicorn.run("butter.api.app:app", host=host, port=port, log_level="info", ws="auto")


app = create_app()
