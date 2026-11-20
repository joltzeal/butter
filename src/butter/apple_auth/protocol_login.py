"""Login through the verified protocol modules.

``services.login`` drives this chain directly. The earlier async client
predates the fixes recorded in ``PROTOCOL.md`` (the missing ``Accept`` header,
the ``X-Apple-Domain-Id`` mismatch, SHLD ``jr``), so it answers 400/541 on live
traffic. This adapter runs the synchronous, verified client in a worker thread
and reports back through the same ``LoginOutcome`` shape.

Addressing rules it enforces, all from PROTOCOL.md:

* ``X-Apple-Domain-Id`` is fixed at 39, never the page's ``domainId``.
* ``redirect_uri`` must be the real ``secureN`` host, resolved from account/home.
* ``X-Apple-Auth-Attributes`` only rides after complete; sending it on init is 404.
* SHLD needs ``jr=30``; ``shld_bt_ck`` is a prerequisite for authx.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .apple_exe_replica import IdmsaClient as SyncIdmsaClient
from .apple_exe_replica import fetch_code

LOGGER = logging.getLogger("butter.login")


class ProtocolLoginError(RuntimeError):
    """A stage of the verified login chain failed."""

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


def _run_sync(email: str, password: str, proxy: str | None,
              code_url: str | None, code: str | None,
              progress, defer_store: bool = False,
              resume=None) -> dict[str, Any]:
    """Blocking login. Returns a dict the async caller turns into a LoginOutcome."""

    def step(name: str) -> None:
        if progress:
            progress(name)

    # Resuming after a code: the parked client still owns the 2FA challenge, so
    # replaying steps 0-3 would issue a *new* OTP push and invalidate the code
    # the operator was given.
    if resume is not None:
        client = resume
        return _finish(client, code, progress, step, defer_store)

    client = SyncIdmsaClient(proxy=proxy, verbose=False)

    step("connect")
    try:
        client.step0_init_session()
        client.step_challenge()
        client.step1_federate(email)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolLoginError("connect", str(exc)) from exc

    step("init")
    try:
        init_data = client.step2_signin_init(email, password)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolLoginError("init", str(exc)) from exc
    if not init_data or "salt" not in init_data:
        raise ProtocolLoginError("init", f"init 无 salt: {init_data!r}"[:200])

    step("complete")
    try:
        complete = client.step3_signin_complete(email, password)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolLoginError("complete", str(exc)) from exc
    status = getattr(complete, "status_code", 0)

    # 200 means no second factor; 409 means a code is required.
    if status == 200:
        if not defer_store:
            step("store")
            client.step_acquire_as_disa()
        return {
            "ok": True,
            "hsa2_required": False,
            "myacinfo": client.state.myacinfo or "",
            "as_disa": client.state.as_disa or "",
            "stk": client.state.stk or "",
            "store_base": client.store_base,
            "session": client.s,
            "client": client,
            "store_pending": defer_store,
            "message": "登录成功",
        }

    if status not in (409, 400) and status >= 400:
        raise ProtocolLoginError("complete", f"status={status}")

    step("hsa2")
    # Fetch the code *before* the auth prefetch: the two calls are independent
    # and the code endpoint is the second-slowest hop (~2s).
    if not code and code_url:
        # Short budget: with no code in hand the operator is blocked, and the
        # dialog can only open once this returns. A device-OTP account with no
        # SMS never produces a code here at all.
        try:
            code = fetch_code(code_url)
        except Exception as exc:  # noqa: BLE001
            raise ProtocolLoginError("hsa2", f"取验证码失败: {exc}") from exc
    client.prefetch_auth()
    if not code:
        return {
            "ok": False,
            "hsa2_required": True,
            "session": client.s,
            "client": client,
            "message": "需要两步验证码",
        }

    return _finish(client, code, progress, step, defer_store)


def _finish(client, code: str, progress, step, defer_store: bool) -> dict[str, Any]:
    """Verify the code on the parked client, then finish the chain."""
    try:
        verify = client.verify_security_code(code)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolLoginError("hsa2", str(exc)) from exc
    if getattr(verify, "status_code", 0) not in (200, 204):
        raise ProtocolLoginError(
            "hsa2", f"验证码被拒 (status={getattr(verify, 'status_code', 0)})，可能是过期或已用过"
        )

    step("trust")
    try:
        client.trust_browser()
    except Exception as exc:  # noqa: BLE001
        raise ProtocolLoginError("trust", str(exc)) from exc

    # ``defer_store`` skips the authx call: it is the single slowest hop
    # (~9s, Apple minting as_disa server-side) and is not needed to consider the
    # account logged in. The caller runs it in the background afterwards.
    if not defer_store:
        step("store")
        try:
            client.step_acquire_as_disa()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("[login] store 握手失败: %s", exc)

    return {
        "ok": bool(client.state.myacinfo),
        "hsa2_required": False,
        "myacinfo": client.state.myacinfo or "",
        "as_disa": client.state.as_disa or "",
        "stk": client.state.stk or "",
        "store_base": client.store_base,
        "session": client.s,
        "client": client,
        "store_pending": defer_store,
        "message": "登录成功" if client.state.myacinfo else "登录未拿到 myacinfo",
    }


async def protocol_login(
    email: str,
    password: str,
    *,
    proxy: str | None = None,
    code_url: str | None = None,
    code: str | None = None,
    progress=None,
    defer_store: bool = False,
    resume=None,
) -> dict[str, Any]:
    """Async wrapper around the verified synchronous chain."""
    return await asyncio.to_thread(
        _run_sync, email, password, proxy, code_url, code, progress, defer_store, resume
    )
