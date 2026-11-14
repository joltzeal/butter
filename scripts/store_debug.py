#!/usr/bin/env python3
"""Apple Store 登录 / 账单 调试脚本 —— 纯 curl_cffi 实现。

每个请求都打印：完整 curl、响应状态、Set-Cookie、X-Apple-* 头。
所有 token / cookie / 主机名均来自响应，无硬编码。

用法:
    uv run python scripts/store_debug.py                    # 完整流程
    uv run python scripts/store_debug.py --step signin      # 只到 signIn 页
    uv run python scripts/store_debug.py --step code        # 只到 2FA 通过
    uv run python scripts/store_debug.py --variants         # 多种 cookie 组合打 authx

环境变量（都有默认值，不写死账号）:
    APPLE_EMAIL / APPLE_PASSWORD / APPLE_OTP_URL / APPLE_PROXY
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.request
from pathlib import Path

from curl_cffi.requests import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from butter.apple_auth import hashcash  # noqa: E402
from butter.apple_auth.srp_client import AppleSRPClient, _from_b64, pad  # noqa: E402

# ----------------------------------------------------------------------- setup
EMAIL = os.environ["APPLE_EMAIL"]
PASSWORD = os.environ["APPLE_PASSWORD"]
OTP_URL = os.environ.get(
    "APPLE_OTP_URL", ""
)
PROXY = os.environ.get("APPLE_PROXY", "socks5h://127.0.0.1:7891")

IDMSA = "https://idmsa.apple.com/appleauth/auth"
WIDGET = "a797929d224abb1cc663bb187bbcd02f7172ca3a84df470380522a7c6092118b"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"'
NAV = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
)
JSONA = "application/json, text/javascript, */*; q=0.01"

T0 = time.perf_counter()
SKIP_JSLOG = os.environ.get("APPLE_SKIP_JSLOG") == "1"


def tick() -> str:
    return f"{time.perf_counter() - T0:6.2f}s"


def say(text: str) -> None:
    print(f"[{tick()}] {text}", flush=True)


def banner(text: str) -> None:
    print(f"\n{'=' * 78}\n[{tick()}] {text}\n{'=' * 78}", flush=True)


def tok(n: int) -> str:
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


def new_frame_id() -> str:
    return f"auth-{tok(8)}-{tok(4)}-{tok(4)}-{tok(4)}-{tok(8)}"


def new_fingerprint() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    return "sla44j1e3NlY5BNlY5BS" + "".join(secrets.choice(alphabet) for _ in range(96))


def get_otp() -> str:
    with urllib.request.urlopen(OTP_URL, timeout=25) as resp:
        body = resp.read().decode("utf-8", "replace")
    match = re.search(r"(\d{6})", body)
    return match.group(1) if match else ""


# --------------------------------------------------------------- curl_cffi I/O
class Session:
    """curl_cffi AsyncSession + 请求/响应全量日志。"""

    def __init__(self) -> None:
        self.http = AsyncSession(
            impersonate="chrome142",
            timeout=40,
            proxies={"http": PROXY, "https": PROXY} if PROXY else None,
            verify=True,
        )

    async def close(self) -> None:
        await self.http.close()

    async def call(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict | None = None,
        json_body: dict | None = None,
        data: str | None = None,
        cookies: dict | None = None,
        allow_redirects: bool = False,
        label: str = "",
    ):
        # Let curl_cffi encode query params; hand-rolled strings broke
        # redirect_uri (the "://" survived into the query unescaped).
        shown = url
        if params:
            pairs = "&".join(f"{k}={v}" for k, v in params.items())
            shown = f"{url}?{pairs}"
        self._print_request(method, shown, headers, data, json_body, label)
        resp = await self.http.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            data=data,
            json=json_body,
            cookies=cookies,
            allow_redirects=allow_redirects,
        )
        self._print_response(resp)
        return resp

    def _print_request(
        self,
        method: str,
        url: str,
        headers: dict,
        data: str | None,
        json_body: dict | None,
        label: str,
    ) -> None:
        print(f"\n--- {label or method} → {method.upper()} {url}", flush=True)
        for key in sorted(headers):
            value = str(headers[key])
            if len(value) > 120:
                value = value[:60] + f"…({len(value)})"
            print(f"    > {key}: {value}", flush=True)
        if data is not None:
            print(f"    > body: {data}", flush=True)
        elif json_body is not None:
            print(f"    > body: {json.dumps(json_body, ensure_ascii=False)}", flush=True)

    def _print_response(self, resp) -> None:
        print(f"    < {resp.status_code}  len={len(resp.content or b'')}", flush=True)
        skip = {"content-security-policy", "strict-transport-security", "report-to",
                "reporting-endpoints", "vary", "x-xss-protection", "x-content-type-options"}
        for key in sorted(resp.headers.keys()):
            if key.lower() in skip:
                continue
            value = str(resp.headers.get(key))
            if len(value) > 130:
                value = value[:70] + f"…({len(value)})"
            print(f"    < {key}: {value}", flush=True)
        for raw in resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []:
            print(f"    < set-cookie: {raw[:130]}", flush=True)


def jar(session: AsyncSession) -> dict[str, str]:
    """当前 curl_cffi cookie jar 的扁平视图。"""
    return dict(session.cookies.get_dict())


def seed_page_cookies(session: AsyncSession) -> dict[str, str]:
    """signIn 页加载后，页面脚本会写这几个 cookie；值都是本地生成的描述符。"""
    import uuid

    descriptor = "2|us|us||en_US|consumer|internet|0|0|1"
    values = {
        "as_sfa": base64.urlsafe_b64encode(descriptor.encode()).decode().rstrip("="),
        "as_rumid": str(uuid.uuid4()),
        "geo": "US",
        "pxro": "1",
        "s_cc": "true",
        "s_fid": "%016X-%016X" % (uuid.uuid4().int >> 64, uuid.uuid4().int >> 64),
        "s_vi": f"[CS]v1|{uuid.uuid4().hex[:16].upper()}.{uuid.uuid4().hex[:16].upper()}[CE]",
    }
    for name, value in values.items():
        session.cookies.set(name, value, domain=".apple.com", path="/")
    return values


# ------------------------------------------------------------------ flow state
class Flow:
    def __init__(self) -> None:
        self.origin = ""          # https://secureN.store.apple.com
        self.signin_url = ""      # 302 的 Location 原文
        self.ssi = ""             # signin_url 里 ?ssi= 之后的部分
        self.stk = ""             # signIn 页 init_data 的 x-aos-stk
        self.syntax = "graviton"
        self.model_version = "v2"
        self.frame = ""
        self.attrs = ""
        self.sid = ""
        self.scnt = ""
        self.hc_bits = 0
        self.hc_challenge = ""
        self.fingerprint = new_fingerprint()

    def absorb(self, resp) -> None:
        for header, attr in (
            ("x-apple-auth-attributes", "attrs"),
            ("x-apple-id-session-id", "sid"),
            ("scnt", "scnt"),
        ):
            value = resp.headers.get(header)
            if value:
                setattr(self, attr, value)
        bits = resp.headers.get("x-apple-hc-bits")
        if bits:
            self.hc_bits = int(bits)
        challenge = resp.headers.get("x-apple-hc-challenge")
        if challenge:
            self.hc_challenge = challenge


# --------------------------------------------------------------------- headers
def nav_headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "accept": NAV,
        "accept-language": "en-US,en;q=0.9",
        "priority": "u=0, i",
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin" if referer else "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": UA,
    }
    if referer:
        headers["referer"] = referer
    return headers


def idmsa_headers(flow: Flow, accept: str = JSONA, extra: dict | None = None) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Origin": "https://idmsa.apple.com",
        "Referer": "https://idmsa.apple.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-Apple-Auth-Attributes": flow.attrs,
        "X-Apple-Domain-Id": "35",
        "X-Apple-Frame-Id": flow.frame,
        "X-Apple-I-FD-Client-Info": json.dumps(
            {
                "U": UA,
                "L": "en-US",
                "Z": "GMT-06:00",
                "V": "1.1",
                "F": flow.fingerprint,
            },
            separators=(",", ":"),
        ),
        "X-Apple-ID-Session-Id": flow.sid,
        "X-Apple-Locale": "en_US",
        "X-Apple-OAuth-Client-Id": WIDGET,
        "X-Apple-OAuth-Client-Type": "firstPartyAuth",
        "X-Apple-OAuth-Redirect-URI": flow.origin,
        "X-Apple-OAuth-Response-Mode": "web_message",
        "X-Apple-OAuth-Response-Type": "code",
        "X-Apple-OAuth-State": flow.frame,
        "X-Apple-Widget-Key": WIDGET,
        "X-Requested-With": "XMLHttpRequest",
        "scnt": flow.scnt,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }
    if extra:
        headers.update(extra)
    return headers


# ----------------------------------------------------------------------- steps
async def step1(io: Session, flow: Flow) -> None:
    banner("① GET secure.store/shop/account/home → 303 → secureN.store")
    resp = await io.call(
        "GET",
        "https://secure.store.apple.com/shop/account/home",
        headers=nav_headers(),
        label="① 入口",
    )
    location = resp.headers.get("location") or ""
    if resp.status_code != 303 or "/shop/" not in location:
        raise SystemExit(f"第 1 步失败: {resp.status_code} location={location!r}")
    flow.origin = location.split("/shop/")[0]
    say(f"① origin = {flow.origin}")


async def step2(io: Session, flow: Flow) -> None:
    banner("② GET {origin}/shop/account/home → 302 → Location(signIn 页, 只带 ssi)")
    resp = await io.call(
        "GET", f"{flow.origin}/shop/account/home", headers=nav_headers(), label="② 取 ssi"
    )
    location = resp.headers.get("location") or ""
    if resp.status_code != 302 or "ssi=" not in location:
        raise SystemExit(f"第 2 步失败: {resp.status_code} location={location!r}")
    flow.signin_url = location
    flow.ssi = location.partition("?ssi=")[2]
    say(f"② signIn 页 = {location[:70]}…")
    say(f"② ssi len={len(flow.ssi)}  {flow.ssi[:32]}…")


async def step3(io: Session, flow: Flow) -> None:
    banner("③ GET signIn 页 → 读 init_data 的 x-aos-stk / syntax / modelVersion")
    resp = await io.call("GET", flow.signin_url, headers=nav_headers(), label="③ signIn 页")
    if resp.status_code != 200:
        raise SystemExit(f"第 3 步失败: {resp.status_code}")
    html = resp.text or ""
    match = re.search(r'"x-aos-stk"\s*:\s*"([^"]+)"', html)
    if not match:
        raise SystemExit("第 3 步失败: init_data 里没有 x-aos-stk")
    flow.stk = match.group(1)
    for key, attr in (("modelVersion", "model_version"), ("syntax", "syntax")):
        found = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html)
        if found:
            setattr(flow, attr, found.group(1))
    say(f"③ len={len(html)} stk={flow.stk}  ({len(flow.stk)} 字符)")
    say(f"③ syntax={flow.syntax} modelVersion={flow.model_version}")

    seeded = seed_page_cookies(io.http)
    say(f"③ 页面脚本 cookie 已写入: {', '.join(sorted(seeded))}")


async def step4(io: Session, flow: Flow) -> None:
    banner("④ SHLD 工作量证明: challenge == swap_tail4(SHA384(salt + str(n)))")
    url = f"{flow.origin}/shop/shld/work/v3/q?jr=100"
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": UA,
        "referer": flow.signin_url,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    resp = await io.call("GET", url, headers=headers, label="④ SHLD 取挑战")
    if resp.status_code != 200:
        say(f"④ 跳过（{resp.status_code}）")
        return
    payload = json.loads(resp.text)
    salt = payload["salt"]
    wanted = payload["challenge"]
    started = time.perf_counter()
    answer = None
    for candidate in range(3_000_000):
        digest = hashlib.sha384(f"{salt}{candidate}".encode()).digest()
        if (digest[:-4] + bytes(reversed(digest[-4:]))).hex() == wanted:
            answer = candidate
            break
    if answer is None:
        say("④ 未解出")
        return
    payload["number"] = answer
    payload["took"] = int((time.perf_counter() - started) * 1000)
    payload.setdefault("flagskv", {"patSkip": True})
    payload.setdefault(
        "jsa", {"s": 100, "f": ["w", "s", "S", "P"], "d": {"u": "c", "p": 1, "r": "xxxxxxo"}}
    )
    say(f"④ 解出 n={answer}  耗时 {payload['took']}ms")
    posted = await io.call(
        "POST",
        url,
        headers={**headers, "content-type": "text/plain;charset=UTF-8", "origin": flow.origin},
        data=json.dumps(payload, separators=(",", ":")),
        label="④ SHLD 提交答案",
    )
    cookies = jar(io.http)
    say(f"④ → {posted.status_code}  shld_bt_ck={len(cookies.get('shld_bt_ck', ''))}")


async def step5(io: Session, flow: Flow) -> None:
    banner("⑤ GET idmsa authorize/signin → attrs / session-id / scnt")
    flow.frame = new_frame_id()
    params = {
        "frame_id": flow.frame,
        "language": "en_US",
        "skVersion": "7",
        "iframeId": flow.frame,
        "client_id": WIDGET,
        "redirect_uri": flow.origin,
        "response_type": "code",
        "response_mode": "web_message",
        "state": flow.frame,
        "authVersion": "latest",
    }
    resp = await io.call(
        "GET",
        f"{IDMSA}/authorize/signin",
        headers={
            "Accept": NAV,
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Referer": f"{flow.origin}/",
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": UA,
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        },
        params=params,
        allow_redirects=True,
        label="⑤ authorize",
    )
    flow.absorb(resp)
    say(
        f"⑤ {resp.status_code} attrs={len(flow.attrs)} sid={len(flow.sid)} "
        f"scnt={len(flow.scnt)} frame={flow.frame}"
    )


async def step6(io: Session, flow: Flow) -> None:
    banner("⑥ POST verify/device/key/challenge")
    resp = await io.call(
        "POST",
        f"{IDMSA}/verify/device/key/challenge",
        headers=idmsa_headers(flow),
        json_body={"passkeyAutofill": False},
        label="⑥ device",
    )
    flow.absorb(resp)
    say(f"⑥ {resp.status_code}")


async def step7(io: Session, flow: Flow) -> dict:
    banner("⑦ POST signin/init（SRP A）")
    client = AppleSRPClient(EMAIL)
    resp = await io.call(
        "POST",
        f"{IDMSA}/signin/init",
        headers=idmsa_headers(flow),
        json_body={
            "a": base64.b64encode(pad(client.A)).decode(),
            "accountName": EMAIL,
            "protocols": ["s2k", "s2k_fo"],
        },
        label="⑦ init",
    )
    if resp.status_code != 200:
        raise SystemExit(f"第 7 步失败: {resp.status_code} {(resp.text or '')[:200]}")
    flow.absorb(resp)
    payload = resp.json()
    payload["_client"] = client
    say(
        f"⑦ {resp.status_code} protocol={payload.get('protocol')} "
        f"iteration={payload.get('iteration')} hc={flow.hc_bits}"
    )
    return payload


async def step8(io: Session, flow: Flow, payload: dict) -> None:
    banner("⑧ POST signin/complete（SRP M1/M2 + hashcash）")
    client: AppleSRPClient = payload["_client"]
    proof = client.compute_proofs(
        _from_b64(payload["salt"]),
        int(payload["iteration"]),
        payload["protocol"],
        PASSWORD,
        payload["b"],
    )
    extra: dict[str, str] = {}
    if flow.hc_challenge and flow.hc_bits:
        extra["X-Apple-HC"] = hashcash.solve_header(flow.hc_challenge, flow.hc_bits)
        say(f"⑧ hashcash 解出  bits={flow.hc_bits}")
    resp = await io.call(
        "POST",
        f"{IDMSA}/signin/complete?isRememberMeEnabled=true",
        headers=idmsa_headers(flow, extra=extra),
        json_body={
            "accountName": EMAIL,
            "rememberMe": False,
            "m1": proof["m1"],
            "c": payload.get("c", ""),
            "m2": proof["m2"],
        },
        label="⑧ complete",
    )
    flow.absorb(resp)
    say(
        f"⑧ {resp.status_code} rscd={resp.headers.get('x-apple-i-rscd')} "
        f"trust-eligible={resp.headers.get('x-apple-twosv-trust-eligible')}"
    )


async def step8b(io: Session, flow: Flow) -> None:
    banner("⑧b POST jslog —— aa cookie 就由这个端点下发")
    resp = await io.call(
        "POST",
        f"{IDMSA}/jslog",
        headers={
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Content-type": "application/json",
            "Origin": "https://idmsa.apple.com",
            "Referer": "https://idmsa.apple.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": UA,
            "X-Apple-Widget-Key": WIDGET,
            "scnt": flow.scnt,
            "x-csrf-token": "",
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        },
        json_body={
            "type": "INFO",
            "title": "sign-in : HTTP - 409",
            "message": "APPLE ID : sign-in failed",
            "iframeId": flow.frame,
            "details": json.dumps({"pageVisibilityState": "visible"}, separators=(",", ":")),
        },
        label="⑧b jslog",
    )
    cookies = jar(io.http)
    say(f"⑧b {resp.status_code}  aa={cookies.get('aa', 'MISSING')}")
    say(f"⑧b jar 全部: {', '.join(sorted(cookies))}")
    say(f"⑧b aasp={'len=' + str(len(cookies.get('aasp', ''))) if cookies.get('aasp') else 'MISSING'}")


async def step9(io: Session, flow: Flow) -> None:
    banner("⑨ GET /appleauth/auth（Accept: text/html）→ 2FA 会话")
    resp = await io.call(
        "GET",
        IDMSA,
        headers=idmsa_headers(flow, accept="text/html"),
        label="⑨ 2FA 状态",
    )
    flow.absorb(resp)
    say(f"⑨ {resp.status_code} len={len(resp.content or b'')} attrs={len(flow.attrs)}")


async def step10(io: Session, flow: Flow) -> None:
    banner("⑩ POST verify/trusteddevice/securitycode")
    code = get_otp()
    if not code:
        raise SystemExit("取不到 OTP")
    say(f"⑩ OTP = {code}")
    resp = await io.call(
        "POST",
        f"{IDMSA}/verify/trusteddevice/securitycode",
        headers=idmsa_headers(flow, extra={"X-Apple-App-Id": WIDGET}),
        json_body={"securityCode": {"code": code}},
        label="⑩ securitycode",
    )
    flow.absorb(resp)
    cookies = jar(io.http)
    say(
        f"⑩ {resp.status_code}  myacinfo={len(cookies.get('myacinfo', ''))} "
        f"aa={cookies.get('aa', 'MISSING')}"
    )


def authx_headers(flow: Flow) -> dict[str, str]:
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "modelversion": flow.model_version,
        "origin": flow.origin,
        "priority": "u=1, i",
        "referer": flow.signin_url,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "syntax": flow.syntax,
        "user-agent": UA,
        "x-aos-model-page": "idmsSignInPage",
        "x-aos-stk": flow.stk,
        "x-requested-with": "Fetch",
    }


NOT_IN_MATERIAL = {"aa", "aasp", "acn01", "idp01", "as_xs", "speedbump-token", "as_cn", "as_disa"}


async def step11(io: Session, flow: Flow, cookies: dict | None = None, label: str = "⑪ authx") -> int:
    banner(f"{label} POST /shop/signIn/idms/authx?ssi=… —— 兑换 as_disa")
    if cookies is None:
        cookies = {k: v for k, v in jar(io.http).items() if k not in NOT_IN_MATERIAL}
    say(f"{label} cookie 清单 ({len(cookies)}): {', '.join(sorted(cookies))}")
    resp = await io.call(
        "POST",
        f"{flow.origin}/shop/signIn/idms/authx?ssi={flow.ssi}",
        headers=authx_headers(flow),
        data="grantCode=",
        cookies=cookies,
        label=label,
    )
    ctype = resp.headers.get("content-type", "")
    say(f"{label} → {resp.status_code}  ctype={ctype}  len={len(resp.content or b'')}")
    if resp.status_code == 200:
        try:
            say(f"{label} body: {json.dumps(resp.json(), ensure_ascii=False)[:220]}")
        except Exception:
            say(f"{label} body: {(resp.text or '')[:220]}")
    else:
        plain = re.sub(r"<[^>]+>", " ", resp.text or "")
        say(f"{label} body: {re.sub(r'\\s+', ' ', plain).strip()[:220]}")
    current = jar(io.http)
    for key in ("as_disa", "as_ltn_us", "as_cn", "as_rec", "myacinfo"):
        value = current.get(key, "")
        say(f"    {key:12s} {'len=' + str(len(value)) if value else 'MISSING'}")
    return resp.status_code


async def step12(io: Session, flow: Flow) -> None:
    banner("⑫ GET account/home → 应出现 RetailHome")
    resp = await io.call(
        "GET",
        f"{flow.origin}/shop/account/home",
        headers=nav_headers(referer=flow.signin_url),
        allow_redirects=True,
        label="⑫ 账户页",
    )
    model = re.search(r'"x-aos-model-page"\s*:\s*"([^"]+)"', resp.text or "")
    say(f"⑫ {resp.status_code} model={model.group(1) if model else '?'}")


# -------------------------------------------------------------------- drivers
async def prepare(io: Session, flow: Flow, until_step: str) -> None:
    await step1(io, flow)
    await step2(io, flow)
    await step3(io, flow)
    if until_step == "signin":
        return
    await step4(io, flow)
    await step5(io, flow)
    await step6(io, flow)
    payload = await step7(io, flow)
    await step8(io, flow, payload)
    await step9(io, flow)
    if not SKIP_JSLOG:
        await step8b(io, flow)


async def run_full(until_step: str) -> None:
    io = Session()
    flow = Flow()
    try:
        await prepare(io, flow, until_step)
        if until_step in ("signin", "otp"):
            return
        await step10(io, flow)
        if until_step == "code":
            return
        status = await step11(io, flow)
        if status == 200:
            await step12(io, flow)
        else:
            say("authx 未通过 —— 试 --variants 看它到底要哪套 cookie")
    finally:
        await io.close()


async def run_variants() -> None:
    io = Session()
    flow = Flow()
    try:
        await prepare(io, flow, "all")
        await step10(io, flow)

        current = jar(io.http)
        subsets = {
            "材料17项": {
                k: v
                for k, v in current.items()
                if k
                in {
                    "dssid2", "dssf", "as_pcts", "as_dc", "shld_bt_m", "sh_spksy",
                    "as_sfa", "geo", "s_fid", "s_cc", "pxro", "dslang", "site",
                    "shld_bt_ck", "as_rumid", "s_vi", "myacinfo",
                }
            },
            "全量": dict(current),
            "仅myacinfo": {"myacinfo": current.get("myacinfo", "")},
            "无myacinfo": {k: v for k, v in current.items() if k != "myacinfo"},
            "加aa": dict(current),
        }
        for name, cookies in subsets.items():
            status = await step11(io, flow, cookies, label=f"⑪ authx[{name}]")
            if status == 200:
                say(f"★★★ [{name}] 成功")
                await step12(io, flow)
                return
            await asyncio.sleep(1.5)
        say("全部组合都是 541")
    finally:
        await io.close()


import asyncio  # noqa: E402  (kept near drivers for readability)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apple Store 登录调试（纯 curl_cffi）")
    parser.add_argument(
        "--step", default="all", choices=["signin", "otp", "code", "all"], help="跑到哪一步停"
    )
    parser.add_argument("--variants", action="store_true", help="多种 cookie 组合打 authx")
    args = parser.parse_args()
    if args.variants:
        asyncio.run(run_variants())
    else:
        asyncio.run(run_full(args.step))


if __name__ == "__main__":
    main()
