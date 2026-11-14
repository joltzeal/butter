"""Apple Store 登录调试 —— 让 curl_cffi 自己管 header，只处理加密。

`impersonate` 会把 UA / sec-ch-ua / sec-fetch-* / accept 这些按浏览器指纹自动带上，
所以这里只显式传真正属于业务的头：token、OAuth 参数、表单类型。

只做三件“需要算”的事：
  1. SHLD 工作量证明   challenge == swap_tail4(SHA384(salt + str(n)))
  2. SRP-6a            A / M1 / M2
  3. hashcash          X-Apple-HC

    uv run python scripts/test.py
"""

import asyncio
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
NAV = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
)
JSONA = "application/json, text/javascript, */*; q=0.01"

T0 = time.perf_counter()

origin = ""        # https://secureN.store.apple.com
signin_url = ""    # 302 的 Location 原文
ssi = ""           # signin_url 里 ?ssi= 后面那段
stk = ""           # signIn 页 init_data 的 x-aos-stk
syntax = "graviton"
model_version = "v2"
frame = ""         # auth-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXX
attrs = ""         # X-Apple-Auth-Attributes
sid = ""           # X-Apple-ID-Session-Id
scnt = ""
hc_bits = 0
hc_challenge = ""
fp = ""            # X-Apple-I-FD-Client-Info 的 F


def say(text: str) -> None:
    print(f"[{time.perf_counter() - T0:6.2f}s] {text}", flush=True)


def tok(n: int) -> str:
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


def absorb(resp) -> None:
    """把会轮换的值记下来，下一步直接用。"""
    global attrs, sid, scnt, hc_bits, hc_challenge
    attrs = resp.headers.get("x-apple-auth-attributes") or attrs
    sid = resp.headers.get("x-apple-id-session-id") or sid
    scnt = resp.headers.get("scnt") or scnt
    bits = resp.headers.get("x-apple-hc-bits")
    if bits:
        hc_bits = int(bits)
    challenge = resp.headers.get("x-apple-hc-challenge")
    if challenge:
        hc_challenge = challenge


def oauth_headers() -> dict:
    """IDMSA 业务头：真正必须手写的就是这些 token 和 OAuth 参数。"""
    return {
        "Accept": JSONA,
        "Content-Type": "application/json",
        "X-Apple-Auth-Attributes": attrs,
        "X-Apple-Domain-Id": "35",
        "X-Apple-Frame-Id": frame,
        "X-Apple-I-FD-Client-Info": json.dumps(
            {"U": UA, "L": "en-US", "Z": "GMT-06:00", "V": "1.1", "F": fp},
            separators=(",", ":"),
        ),
        "X-Apple-ID-Session-Id": sid,
        "X-Apple-Locale": "en_US",
        "X-Apple-OAuth-Client-Id": WIDGET,
        "X-Apple-OAuth-Client-Type": "firstPartyAuth",
        "X-Apple-OAuth-Redirect-URI": origin,
        "X-Apple-OAuth-Response-Mode": "web_message",
        "X-Apple-OAuth-Response-Type": "code",
        "X-Apple-OAuth-State": frame,
        "X-Apple-Widget-Key": WIDGET,
        "scnt": scnt,
    }


def look(resp) -> None:
    print(f"    < {resp.status_code}  len={len(resp.content or b'')}", flush=True)
    for key in sorted(resp.headers.keys()):
        if key.lower() in {
            "content-security-policy", "strict-transport-security", "report-to",
            "reporting-endpoints", "vary", "x-xss-protection", "x-content-type-options",
            "connection", "server", "x-frame-options",
        }:
            continue
        value = str(resp.headers.get(key))
        if len(value) > 140:
            value = value[:70] + f"...({len(value)})"
        print(f"    < {key}: {value}", flush=True)
    for raw in resp.headers.get_list("set-cookie"):
        print(f"    < set-cookie: {raw[:140]}", flush=True)


async def main() -> None:
    global origin, signin_url, ssi, stk, syntax, model_version, frame, fp

    fp = "sla44j1e3NlY5BNlY5BS" + "".join(
        secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
        for _ in range(96)
    )

    s = AsyncSession(
        impersonate="chrome142",
        timeout=40,
        proxies={"http": PROXY, "https": PROXY} if PROXY else None,
    )

    try:
        # ① 303 → secureN.store
        say("① GET secure.store/shop/account/home")
        r = await s.get(
            "https://secure.store.apple.com/shop/account/home", allow_redirects=False
        )
        look(r)
        origin = (r.headers.get("location") or "").split("/shop/")[0]
        say(f"① origin = {origin}")
        if not origin:
            return

        # ② 302 → signIn 页，Location 里就是 ssi
        say("② GET {origin}/shop/account/home")
        r = await s.get(f"{origin}/shop/account/home", allow_redirects=False)
        look(r)
        signin_url = r.headers.get("location") or ""
        ssi = signin_url.partition("?ssi=")[2]
        say(f"② ssi len={len(ssi)}")
        if not ssi:
            return

        # ③ signIn 页 → x-aos-stk
        say("③ GET signIn 页")
        r = await s.get(signin_url, allow_redirects=False)
        look(r)
        html = r.text or ""
        found = re.search(r'"x-aos-stk"\s*:\s*"([^"]+)"', html)
        stk = found.group(1) if found else ""
        m = re.search(r'"modelVersion"\s*:\s*"([^"]+)"', html)
        if m:
            model_version = m.group(1)
        m = re.search(r'"syntax"\s*:\s*"([^"]+)"', html)
        if m:
            syntax = m.group(1)
        say(f"③ stk={stk}  ({len(stk)} 字符)  syntax={syntax} model={model_version}")
        if not stk:
            return

        # ④ 页面脚本会写的 cookie（值本身是本地生成的描述符，不用算）
        import uuid

        for name, value in {
            "as_sfa": base64.urlsafe_b64encode(
                b"2|us|us||en_US|consumer|internet|0|0|1"
            ).decode().rstrip("="),
            "as_rumid": str(uuid.uuid4()),
            "geo": "US",
            "pxro": "1",
            "s_cc": "true",
            "s_fid": "%016X-%016X" % (uuid.uuid4().int >> 64, uuid.uuid4().int >> 64),
            "s_vi": f"[CS]v1|{uuid.uuid4().hex[:16].upper()}.{uuid.uuid4().hex[:16].upper()}[CE]",
        }.items():
            s.cookies.set(name, value, domain=".apple.com", path="/")
        say(f"④ cookie: {', '.join(sorted(dict(s.cookies.get_dict())))}")

        # ⑤ SHLD 工作量证明
        say("⑤ SHLD 工作量证明")
        url = f"{origin}/shop/shld/work/v3/q?jr=100"
        r = await s.get(url, allow_redirects=False, headers={"Referer": signin_url})
        look(r)
        payload = json.loads(r.text)
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
            say("⑤ 未解出")
            return
        payload["number"] = answer
        payload["took"] = int((time.perf_counter() - started) * 1000)
        payload.setdefault("flagskv", {"patSkip": True})
        payload.setdefault(
            "jsa", {"s": 100, "f": ["w", "s", "S", "P"], "d": {"u": "c", "p": 1, "r": "xxxxxxo"}}
        )
        say(f"⑤ n={answer}  {payload['took']}ms")
        r = await s.post(
            url,
            data=json.dumps(payload, separators=(",", ":")),
            headers={
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": origin,
                "Referer": signin_url,
            },
            allow_redirects=False,
        )
        look(r)
        say(f"⑤ → {r.status_code}  shld_bt_ck={len(s.cookies.get('shld_bt_ck') or '')}")

        # ⑥ authorize/signin → attrs / sid / scnt
        say("⑥ GET authorize/signin")
        frame = f"auth-{tok(8)}-{tok(4)}-{tok(4)}-{tok(4)}-{tok(8)}"
        r = await s.get(
            f"{IDMSA}/authorize/signin",
            params={
                "frame_id": frame,
                "language": "en_US",
                "skVersion": "7",
                "iframeId": frame,
                "client_id": WIDGET,
                "redirect_uri": origin,
                "response_type": "code",
                "response_mode": "web_message",
                "state": frame,
                "authVersion": "latest",
            },
            headers={"Referer": f"{origin}/", "Accept": NAV},
            allow_redirects=True,
        )
        look(r)
        absorb(r)
        say(f"⑥ {r.status_code} attrs={len(attrs)} sid={len(sid)} scnt={len(scnt)}")

        # ⑦ device key challenge
        say("⑦ POST verify/device/key/challenge")
        r = await s.post(
            f"{IDMSA}/verify/device/key/challenge",
            json={"passkeyAutofill": False},
            headers=oauth_headers(),
            allow_redirects=False,
        )
        look(r)
        absorb(r)
        say(f"⑦ {r.status_code}")

        # ⑧ signin/init（SRP A）
        say("⑧ POST signin/init")
        srp = AppleSRPClient(EMAIL)
        r = await s.post(
            f"{IDMSA}/signin/init",
            json={
                "a": base64.b64encode(pad(srp.A)).decode(),
                "accountName": EMAIL,
                "protocols": ["s2k", "s2k_fo"],
            },
            headers=oauth_headers(),
            allow_redirects=False,
        )
        look(r)
        if r.status_code != 200:
            say(f"⑧ 失败 {r.status_code} {(r.text or '')[:200]}")
            return
        absorb(r)
        init = r.json()
        say(f"⑧ {init['protocol']} {init['iteration']}  hc_bits={hc_bits}")

        # ⑨ signin/complete（SRP M1/M2 + hashcash）
        say("⑨ POST signin/complete")
        proof = srp.compute_proofs(
            _from_b64(init["salt"]),
            int(init["iteration"]),
            init["protocol"],
            PASSWORD,
            init["b"],
        )
        extra = oauth_headers()
        if hc_challenge and hc_bits:
            extra["X-Apple-HC"] = hashcash.solve_header(hc_challenge, hc_bits)
            say(f"⑨ hashcash bits={hc_bits}")
        r = await s.post(
            f"{IDMSA}/signin/complete?isRememberMeEnabled=true",
            json={
                "accountName": EMAIL,
                "rememberMe": False,
                "m1": proof["m1"],
                "c": init.get("c", ""),
                "m2": proof["m2"],
            },
            headers=extra,
            allow_redirects=False,
        )
        look(r)
        absorb(r)
        say(
            f"⑨ {r.status_code} rscd={r.headers.get('x-apple-i-rscd')} "
            f"trust-eligible={r.headers.get('x-apple-twosv-trust-eligible')}"
        )

        # ⑩ 2FA 会话（Accept: text/html）
        say("⑩ GET /appleauth/auth")
        r = await s.get(
            IDMSA, headers={**oauth_headers(), "Accept": "text/html"}, allow_redirects=False
        )
        look(r)
        absorb(r)
        say(f"⑩ {r.status_code} len={len(r.content or b'')} attrs={len(attrs)}")

        # ⑪ 2FA 验证码
        say("⑪ POST verify/trusteddevice/securitycode")
        with urllib.request.urlopen(OTP_URL, timeout=25) as handle:
            text = handle.read().decode("utf-8", "replace")
        found = re.search(r"(\d{6})", text)
        code = found.group(1) if found else ""
        say(f"⑪ OTP={code}")
        r = await s.post(
            f"{IDMSA}/verify/trusteddevice/securitycode",
            json={"securityCode": {"code": code}},
            headers={**oauth_headers(), "X-Apple-App-Id": WIDGET},
            allow_redirects=False,
        )
        look(r)
        absorb(r)
        say(
            f"⑪ {r.status_code}  myacinfo={len(s.cookies.get('myacinfo') or '')} "
            f"aa={s.cookies.get('aa') or 'MISSING'}"
        )

        say(f"⑪.5 dssid2 = {s.cookies.get('dssid2')}")
        say(f"⑪.5 当前 cookie ({len(dict(s.cookies.get_dict()))}): {', '.join(sorted(dict(s.cookies.get_dict())))}")

        # ⑫ 先试试能不能直接进账户页
        say("⑫ GET account/home（2FA 之后直接试）")
        r = await s.get(
            f"{origin}/shop/account/home",
            headers={"Referer": signin_url},
            allow_redirects=True,
        )
        look(r)
        _model = re.search(r'"x-aos-model-page"\s*:\s*"([^"]+)"', r.text or "")
        say(f"⑫ {r.status_code} model={_model.group(1) if _model else '?'}  url={r.url[:80]}")
        if _model and _model.group(1) == "RetailHome":
            say("★★★ 直接进去了")

        # ⑬ authx：myacinfo 换 as_disa
        say("⑬ POST authx")
        _ck = s.cookies.get("shld_bt_ck") or ""
        say(f"⑬ 发送 shld_bt_ck len={len(_ck)}  ts={_ck.split('|')[1] if '|' in _ck else '?'}")
        say(f"⑬ authx 目标 ssi len={len(ssi)}  {ssi[:50]}…")
        say(f"⑬ signin_url={signin_url[:90]}…")
        _jar = dict(s.cookies.get_dict())
        say(f"⑬ 全部 cookie ({len(_jar)}): {', '.join(sorted(_jar))}")
        r = await s.post(
            f"{origin}/shop/signIn/idms/authx",
            params={"ssi": ssi},
            data="grantCode=",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": origin,
                "Referer": signin_url,
                "syntax": syntax,
                "modelversion": model_version,
                "x-aos-model-page": "idmsSignInPage",
                "x-aos-stk": stk,
                "x-requested-with": "Fetch",
            },
            allow_redirects=False,
        )
        look(r)
        say(
            f"⑬ {r.status_code}  ctype={r.headers.get('content-type')}  "
            f"len={len(r.content or b'')}"
        )
        if r.status_code == 200:
            say(f"⑬ body: {json.dumps(r.json(), ensure_ascii=False)[:220]}")
        else:
            plain = re.sub(r"<[^>]+>", " ", r.text or "")
            say(f"⑬ body: {re.sub(r'\s+', ' ', plain).strip()[:200]}")
        for key in ("as_disa", "as_ltn_us", "as_cn", "as_rec", "myacinfo"):
            value = s.cookies.get(key) or ""
            say(f"    {key:12s} {'len=' + str(len(value)) if value else 'MISSING'}")

        if r.status_code != 200:
            return

        # ⑭ 账户页
        say("⑭ GET account/home")
        r = await s.get(
            f"{origin}/shop/account/home", headers={"Referer": signin_url}, allow_redirects=True
        )
        look(r)
        model = re.search(r'"x-aos-model-page"\s*:\s*"([^"]+)"', r.text or "")
        say(f"⑭ {r.status_code} model={model.group(1) if model else '?'}")
    finally:
        await s.close()


if __name__ == "__main__":
    asyncio.run(main())
