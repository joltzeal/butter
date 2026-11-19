#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple Store 登录 —— 严格按 烽火账单辅助工具.exe 的实现复刻

来源: payload.bin (Nuitka 载荷) 中 src/apple_auth/idmsa_client.py + store_client.py
      所有常量、顺序、请求头均从字节码常量表还原。

════════ 真实顺序（IdmsaClient.login）════════
step0_init_session()      GET  account.apple.com/appleauth/auth/authorize/signin
                               skVersion=7  authVersion=8.0.2
                               Sec-Fetch-Site: none / Mode: navigate / Dest: document
                          → 正则 "sessionId"\\s*:\\s*"([^"]+)"  → cookies aasp/scnt
step1_federate()          POST /appleauth/auth/federate?isRememberMeEnabled=true
                          → 记录 HC-Bits / HC-Challenge
step2_signin_init()       POST /appleauth/auth/signin/init   protocols=[s2k, s2k_fo]
step3_signin_complete()   compute_proofs → mint_hashcash → X-APPLE-HC
                          POST /appleauth/auth/signin/complete
                          → 409 + authType=sa 才是正常 2FA 分支
step_acquire_as_disa()    ★ GET /shop/account/home → 302 → ssi
                          GET /shop/signIn/account?ssi= → x-aos-stk
                          POST /shop/signIn/idms/authx (grantCode=)
                          → Set-Cookie: as_disa=(正则) / as_sfa
step4_get_sct()           ★ GET /appleauth/auth/questions/reset/iforgot
                              X-Apple-App-Id: WIDGET_KEY
                          → Location / 响应里取 sct
login_for_store()         = login() + myacinfo 校验

════════ 关键常量（constants.py 还原）════════
WIDGET_KEY_STORE   = a797929d224abb1cc663bb187bbcd02f7172ca3a84df470380522a7c6092118b
WIDGET_KEY_ACCOUNT = af1139274f266b22b68c2a3e7ad932cb3c0bbe854e13a79af78dcc73136882c3
IDMSA_BASE         = https://idmsa.apple.com
IFORGOT_BASE       = https://iforgot.apple.com
APPLEID_BASE       = https://appleid.apple.com
ACCOUNT_APPLE_BASE = https://account.apple.com
X-Apple-Domain-Id  = 42           ← 不是 39
UA                 = Chrome/145 Windows
Accept-Language    = zh-CN,zh;q=0.9
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import string
import time
from urllib.parse import urlencode, urlparse, parse_qs

from curl_cffi import requests as creq

# ══════════════════ 常量 ══════════════════
WIDGET_KEY_STORE = "a797929d224abb1cc663bb187bbcd02f7172ca3a84df470380522a7c6092118b"
WIDGET_KEY_ACCOUNT = "af1139274f266b22b68c2a3e7ad932cb3c0bbe854e13a79af78dcc73136882c3"

IDMSA_BASE = "https://idmsa.apple.com"
IFORGOT_BASE = "https://iforgot.apple.com"
APPLEID_BASE = "https://appleid.apple.com"
ACCOUNT_APPLE_BASE = "https://account.apple.com"
STORE_BASE = "https://secure.store.apple.com"

DOMAIN_ID = "39"   # 实测固定 39 可用；页面 domainId 不可用作请求头
AUTH_VERSION = "8.0.2"
SK_VERSION = "7"
LOCALE = "zh-CN"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
SEC_CH_UA = '"Google Chrome";v="152", "Chromium";v="152", "Not(A:Brand";v="24"'
ACCEPT_LANG = "en-US,en;q=0.9"

SRP_N_HEX = (
    "AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050"
    "A37329CBB4A099ED8193E0757767A13DD52312AB4B03310DCD7F48A9DA04FD50"
    "E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B8"
    "55F97993EC975EEAA80D740ADBF4FF747359D041D5C33EA71D281E446B14773B"
    "CA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87748"
    "544523B524B0D57D5EA77A2775D2ECFA032CFBDBF52FB3786160279004E57AE6"
    "AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DBFBB6"
    "94B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E4AFF73"
)
SRP_N = int(SRP_N_HEX, 16)
SRP_k_HEX = "05b9e8ef059c6b32ea59fc1d322d37f04aa30bae5aa9003b8321e21ddb04e300"


def _i2b(n: int, size: int = 256) -> bytes:
    return int(n).to_bytes(size, "big")


def _sha256(*chunks: bytes) -> bytes:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.digest()


def generate_oauth_state(number: int = 3) -> str:
    """0x14d5a2c _generate_oauth_state: 'auth-' + n×4 段随机小写+数字"""
    chars = string.ascii_lowercase + string.digits
    parts = ["auth"]
    for _ in range(number):
        parts.append("".join(secrets.choice(chars) for _ in range(4)))
    return "-".join(parts)


def _gen_frame_id() -> str:
    """authorize 页实测格式：auth-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxx（首 8 + 4×4 + 8 段）"""
    chars = string.ascii_lowercase + string.digits
    first = "".join(secrets.choice(chars) for _ in range(8))
    mid = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    last = "".join(secrets.choice(chars) for _ in range(8))
    return "-".join(["auth", first] + mid + [last])


def srp_proofs(username: str, password: str, salt_b64: str, iterations: int,
               server_B_b64: str, a_int: int, protocol: str = "s2k") -> tuple[str, str]:
    """Compute Apple's SRP M1/M2 proofs.

    Apple uses a private SRP-6a variant: ``k`` is ``H(N) XOR H(pad(g))`` rather
    than the RFC's ``H(N | pad(g))``, and ``u`` hashes the *unpadded* A and B.
    Both details are load-bearing — the server answers -20101 otherwise.
    """
    salt = base64.b64decode(salt_b64)
    b_bytes = base64.b64decode(server_B_b64)
    A_int = pow(2, a_int, SRP_N)
    A_bytes = _i2b(A_int)

    p0 = _sha256(password.encode("utf-8"))
    if iterations:
        key = p0 if protocol == "s2k" else p0.hex().encode()
        P = hashlib.pbkdf2_hmac("sha256", key, salt, iterations, 32)
    else:
        P = p0

    x = int.from_bytes(_sha256(salt, _sha256(b":" + P)), "big")
    k = int(SRP_k_HEX, 16)
    B = int.from_bytes(b_bytes, "big")
    u = int.from_bytes(_sha256(A_bytes, b_bytes), "big")
    S = pow((B - k * pow(2, x, SRP_N)) % SRP_N, a_int + u * x, SRP_N)
    K = _sha256(_i2b(S))

    hN_xor_hg = bytes(a ^ b for a, b in zip(_sha256(_i2b(SRP_N)), _sha256(_i2b(2))))
    M1 = _sha256(hN_xor_hg, _sha256(username.lower().encode()), salt, A_bytes, b_bytes, K)
    M2 = _sha256(A_bytes, M1, K)
    return base64.b64encode(M1).decode(), base64.b64encode(M2).decode()


class SessionState:
    """session_manager.SessionState"""

    def __init__(self):
        self.session_id = None
        self.scnt = None
        self.auth_attributes = None
        self.hc_bits = None
        self.hc_challenge = None
        self.account_country = None
        self.as_disa = None
        self.as_sfa = None
        self.myacinfo = None
        self.sct = None
        self.stk = None
        self.ssi = None
        self.domain_id = None
        self.shld_bt_ck = None
        self.oauth_state = None
        self.frame_id = None

    def absorb(self, r, stage: str = "?"):
        h = {k.lower(): v for k, v in (r.headers or {}).items()}
        if h.get("scnt"):
            self.scnt = h["scnt"]
        if h.get("x-apple-id-session-id"):
            self.session_id = h["x-apple-id-session-id"]
        if h.get("x-apple-auth-attributes"):
            self.auth_attributes = h["x-apple-auth-attributes"]
        # 只在 2xx 响应里采信 HC，400/401 的 HC 是干扰值
        if 200 <= getattr(r, "status_code", 0) < 300:
            if h.get("x-apple-hc-bits"):
                self.hc_bits = h["x-apple-hc-bits"]
            if h.get("x-apple-hc-challenge"):
                self.hc_challenge = h["x-apple-hc-challenge"]
        if h.get("x-apple-id-account-country"):
            self.account_country = h["x-apple-id-account-country"]
        return h


class IdmsaClient:
    """idmsa_client.IdmsaClient"""

    def __init__(self, proxy: str | None = None, verbose: bool = False,
                 impersonate: str = "chrome152_macos"):
        kw = {"impersonate": impersonate}
        if proxy:
            kw["proxy"] = proxy
        self.s = creq.Session(**kw)
        self.state = SessionState()
        self.verbose = verbose
        self.proxy = proxy
        self.store_base = STORE_BASE
        self.widget_key = WIDGET_KEY_STORE
        self.oauth_state = _gen_frame_id()
        self.frame_id = self.oauth_state
        self.state.oauth_state = self.oauth_state
        self.state.frame_id = self.frame_id
        self.redirect_uri = STORE_BASE   # exe 里由调用方传入；store 场景用 store base

    # ---------- 通用 ----------
    def _log(self, msg: str):
        if self.verbose:
            print(f"    {msg}")

    def common_headers(self, extra: dict | None = None) -> dict:
        """
        严格按 constants.COMMON_HEADERS 还原（0x14d41ea 起）：
            User-Agent     Chrome/145 Windows
            sec-ch-ua      "Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"
            sec-ch-ua-mobile   ?0
            sec-ch-ua-platform "Windows"
            Accept-Language    zh-CN,zh;q=0.9
            Accept-Encoding    gzip, deflate, br, zstd
            Origin / Referer   https://idmsa.apple.com /
            Sec-Fetch-Site same-origin / Mode cors / Dest empty
            X-Apple-Domain-Id  (COMMON_HEADERS 里是 11，get_idmsa_headers 覆盖为下发值)
            X-Apple-Privacy-Consent / -Accepted  = true
            X-Requested-With XMLHttpRequest
        """
        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": ACCEPT_LANG,
            "User-Agent": UA,
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Origin": IDMSA_BASE,
            "Referer": IDMSA_BASE + "/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "X-Apple-Domain-Id": self.state.domain_id or DOMAIN_ID,
            "X-Apple-Widget-Key": self.widget_key,
            "X-Apple-OAuth-Client-Id": self.widget_key,
            "X-Apple-OAuth-Client-Type": "firstPartyAuth",
            "X-Apple-OAuth-Redirect-URI": self.redirect_uri,
            "X-Apple-OAuth-Response-Type": "code",
            "X-Apple-OAuth-Response-Mode": "web_message",
            "X-Apple-OAuth-State": self.oauth_state,
            "X-Apple-Frame-Id": self.frame_id,
            "X-Apple-Locale": "en_US",
            "X-Requested-With": "XMLHttpRequest",
        }
        ck = self._cookies()
        if self.state.session_id:
            h["X-Apple-ID-Session-Id"] = self.state.session_id
        elif ck.get("aasp"):
            h["X-Apple-ID-Session-Id"] = ck["aasp"]
        if ck.get("scnt"):
            h["scnt"] = ck["scnt"]
        # Auth-Attributes 只在 complete/2FA 之后带；init 阶段带了会 404
        if getattr(self, "_use_attrs", False) and self.state.auth_attributes:
            h["X-Apple-Auth-Attributes"] = self.state.auth_attributes
        if getattr(self, "_use_fd", False):
            try:
                from .apple_fd_client_info import build_client_info
                h["X-Apple-I-FD-Client-Info"] = build_client_info(UA, "en-US")
            except Exception:
                pass
        if extra:
            h.update(extra)
        return h

    # ══════════════ step0 ══════════════
    def _warmup_store(self):
        """先访问 store account/home，让服务端分配 secureN + ssi，否则后续 init 会 404"""
        r = self.s.get(self.store_base + "/shop/account/home",
                       headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": ACCEPT_LANG,
                                "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Dest": "document"},
                       allow_redirects=False, timeout=30)
        loc = r.headers.get("location") or ""
        m = re.match(r"(https://[^/]+)", loc)
        if m:
            self.store_base = m.group(1)
        m2 = re.search(r"[?&]ssi=([^&\s]+)", loc)
        # 303 只是第一跳，跟着走第二跳才拿到 ssi
        if not m2 and loc:
            r2 = self.s.get(loc, headers={"Accept": "text/html",
                                          "Accept-Language": ACCEPT_LANG,
                                          "Sec-Fetch-Site": "cross-site",
                                          "Sec-Fetch-Mode": "navigate",
                                          "Sec-Fetch-Dest": "document"},
                            allow_redirects=False, timeout=30)
            loc2 = r2.headers.get("location") or ""
            m2 = re.search(r"[?&]ssi=([^&\s]+)", loc2)
            mm = re.match(r"(https://[^/]+)", loc2)
            if mm:
                self.store_base = mm.group(1)
            self._log(f"[warmup2] {r2.status_code} -> {self.store_base}")
        if m2:
            self.state.ssi = m2.group(1)
        self.redirect_uri = self.store_base
        self._log(f"[warmup] {r.status_code} -> {self.store_base} ssi={'OK' if self.state.ssi else 'NONE'}")
        return r

    def _resolve_store_base(self):
        """解析出真实 secureN 域名，redirect_uri 必须与之一致"""
        r = self.s.get(self.store_base + "/shop/account/home",
                       headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                "Accept-Language": ACCEPT_LANG,
                                "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Dest": "document"},
                       allow_redirects=False, timeout=30)
        loc = r.headers.get("location") or ""
        m = re.match(r"(https://[^/]+)", loc)
        if m:
            self.store_base = m.group(1)
        self._log(f"[resolve] {r.status_code} -> {self.store_base}")
        return self.store_base

    def step0_init_session(self):
        # redirect_uri 必须是真实 secureN 域名，且与 authorize 的 client 配置一致
        self._resolve_store_base()
        self.redirect_uri = self.store_base
        url = IDMSA_BASE + "/appleauth/auth/authorize/signin"
        q = {
            "frame_id": self.frame_id,
            "language": "en_US",
            "skVersion": SK_VERSION,
            "iframeId": self.frame_id,
            "client_id": self.widget_key,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "response_mode": "web_message",
            "state": self.oauth_state,
            "authVersion": AUTH_VERSION,
        }
        h = {
            "Accept": "text/html",
            "Accept-Language": ACCEPT_LANG,
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
            "Referer": self.redirect_uri.rstrip("/") + "/",
        }
        r = self.s.get(url + "?" + urlencode(q), headers=h, timeout=30)
        self.state.absorb(r, "step0")
        # 注意：authorize 页里的 domainId(如 35) 不能用于请求头，
        # 实测它只影响页面资源版本；请求头必须用 39（exe get_idmsa_headers 里也是写死）
        self.state.domain_id = DOMAIN_ID
        self._log(f"[idmsa] domainId={self.state.domain_id} (redirect={self.redirect_uri})")
        # 正则取 sessionId
        m = re.search(r'"sessionId"\s*:\s*"([^"]+)"', r.text or "")
        if m:
            self.state.session_id = m.group(1)
        ck = self._cookies()
        if ck.get("aasp") and not self.state.session_id:
            self.state.session_id = ck["aasp"]
        # scnt 只认 set-cookie 里新下发的；jar 里残留的旧值会让 init 404
        sc = r.headers.get("set-cookie") or ""
        m_scnt = re.search(r"scnt=([^;]+)", sc)
        if m_scnt:
            self.state.scnt = m_scnt.group(1)
        else:
            self.state.scnt = None
        if self.state.scnt is None and ck.get("scnt"):
            # jar 里有但本次未重发，同样视为无效
            pass
        self._log(f"[idmsa] 0: status={r.status_code} session_id="
                  f"{'OK' if self.state.session_id else 'NONE'} scnt={bool(self.state.scnt)}")
        return r

    def step_challenge(self):
        """POST /verify/device/key/challenge —— 建立 passkey 2FA 上下文"""
        url = IDMSA_BASE + "/appleauth/auth/verify/device/key/challenge"
        h = self.common_headers({"Accept": "application/json, text/plain, */*",
                                 "Content-Type": "application/json"})
        r = self.s.post(url, headers=h, data='{"passkeyAutofill":false}', timeout=30)
        self.state.absorb(r, "challenge")
        ck = self._cookies()
        if ck.get("scnt"):
            self.state.scnt = ck["scnt"]
        self._log(f"[idmsa] challenge status={r.status_code}")
        return r

    # ══════════════ step1 ══════════════
    def step1_federate(self, email: str):
        url = IDMSA_BASE + "/appleauth/auth/federate?isRememberMeEnabled=true"
        # ``rememberMe: True`` is what makes Apple issue long-lived DES
        # refresh tokens. With False the IDMSA session dies within minutes and
        # every store call afterwards fails — the "frequent logout" symptom.
        payload = {"accountName": email, "rememberMe": True}
        h = self.common_headers({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json",
        })
        r = self.s.post(url, headers=h, data=json.dumps(payload), timeout=30)
        hd = self.state.absorb(r, "step1")
        self._log(f"[idmsa] 1: federate status={r.status_code} "
                  f"HC-Bits={self.state.hc_bits} HC-Challenge={self.state.hc_challenge}")
        return r

    # ══════════════ step2 ══════════════
    def step2_signin_init(self, email: str, password: str | None = None):
        a_bytes = secrets.token_bytes(256)
        a_int = int.from_bytes(a_bytes, "big")
        A_int = pow(2, a_int, SRP_N)
        a_b64 = base64.b64encode(_i2b(A_int)).decode()
        self._srp_a_int = a_int
        self._srp_a_b64 = a_b64

        url = IDMSA_BASE + "/appleauth/auth/signin/init"
        payload = {"a": a_b64, "accountName": email, "protocols": ["s2k", "s2k_fo"]}
        h = self.common_headers({"Content-Type": "application/json"})
        r = self.s.post(url, headers=h, data=json.dumps(payload), timeout=30)
        if r.status_code != 200:
            # 同一会话内重试，不重建 step0/step1（否则 scnt 与 domainId 失配 → 404）
            self._log(f"    init {r.status_code}，同会话重试")
            for i in range(2):
                time.sleep(1.0 + i)
                a_bytes = secrets.token_bytes(256)
                self._srp_a_int = int.from_bytes(a_bytes, "big")
                a_b64 = base64.b64encode(_i2b(pow(2, self._srp_a_int, SRP_N))).decode()
                self._srp_a_b64 = a_b64
                payload = {"a": a_b64, "accountName": email,
                           "protocols": ["s2k", "s2k_fo"]}
                h = self.common_headers({"Content-Type": "application/json"})
                r = self.s.post(url, headers=h, data=json.dumps(payload), timeout=30)
                self._log(f"    重试#{i+1} -> {r.status_code}")
                if r.status_code == 200:
                    break
        self.state.absorb(r, "step2")
        d = None
        try:
            d = r.json()
        except Exception:
            pass
        self._init_data = d
        self._log(f"[idmsa] 2: signin/init status={r.status_code} "
                  f"protocol={(d or {}).get('protocol')} iterations={(d or {}).get('iteration')}")
        return d

    # ══════════════ SRP ══════════════
    def compute_proofs(self, username: str, password: str, salt_b64: str,
                       iterations: int, server_B_b64: str, protocol: str = "s2k"):
        return srp_proofs(username, password, salt_b64, iterations, server_B_b64,
                          self._srp_a_int, protocol)

    def _compute_proofs_legacy(self, username: str, password: str, salt_b64: str,
                               iterations: int, server_B_b64: str, protocol: str = "s2k"):
        salt = base64.b64decode(salt_b64)
        b_bytes = base64.b64decode(server_B_b64)
        a_int = self._srp_a_int
        A_int = pow(2, a_int, SRP_N)
        A_bytes = _i2b(A_int)

        p0 = _sha256(password.encode("utf-8"))
        if iterations:
            key = p0 if protocol == "s2k" else p0.hex().encode()
            P = hashlib.pbkdf2_hmac("sha256", key, salt, iterations, 32)
        else:
            P = p0

        x = int.from_bytes(_sha256(salt, _sha256(b":" + P)), "big")
        k = int(SRP_k_HEX, 16)
        B = int.from_bytes(b_bytes, "big")
        u = int.from_bytes(_sha256(A_bytes, b_bytes), "big")
        S = pow((B - k * pow(2, x, SRP_N)) % SRP_N, a_int + u * x, SRP_N)
        K = _sha256(_i2b(S))

        hN_xor_hg = bytes(a ^ b for a, b in zip(_sha256(_i2b(SRP_N)), _sha256(_i2b(2))))
        M1 = _sha256(hN_xor_hg, _sha256(username.lower().encode()), salt, A_bytes, b_bytes, K)
        M2 = _sha256(A_bytes, M1, K)
        return base64.b64encode(M1).decode(), base64.b64encode(M2).decode()

    # ══════════════ step3 ══════════════
    def step3_signin_complete(self, email: str, password: str):
        self._use_attrs = True
        d = getattr(self, "_init_data", None) or {}
        m1, m2 = self.compute_proofs(
            email, password, d.get("salt", ""), int(d.get("iteration") or 0),
            d.get("b", ""), d.get("protocol") or "s2k")

        hc_stamp = None
        if self.state.hc_challenge and self.state.hc_bits:
            try:
                from .apple_hashcash import build_stamp
                self._log(f"HC 用于 stamp: {self.state.hc_challenge} bits={self.state.hc_bits}")
                hc_stamp = build_stamp(self.state.hc_challenge, self.state.hc_bits)
            except Exception as e:
                self._log(f"hashcash 失败: {e}")

        url = IDMSA_BASE + "/appleauth/auth/signin/complete?isRememberMeEnabled=true"
        payload = {"accountName": email, "rememberMe": True,
                   "m1": m1, "c": d.get("c"), "m2": m2}
        extra = {"Content-Type": "application/json",
                 "Accept": "application/json, text/javascript, */*; q=0.01"}
        if hc_stamp:
            extra["X-APPLE-HC"] = hc_stamp
        h = self.common_headers(extra)
        r = self.s.post(url, headers=h, data=json.dumps(payload), timeout=30)
        self.state.absorb(r, "step3")

        auth_type = None
        try:
            auth_type = r.json().get("authType")
        except Exception:
            pass
        self._log(f"[idmsa] 3: signin/complete status={r.status_code} authType={auth_type}")
        self.need_2fa = (r.status_code == 409)
        self.auth_type = auth_type
        if hc_stamp:
            self._log(f"    X-APPLE-HC={hc_stamp}")
        return r

    # ══════════════ 2FA ══════════════
    def prefetch_auth(self):
        self._use_attrs = True
        """complete 409 后必须先 GET /appleauth/auth，2FA 接口才认当前 scnt"""
        self._use_fd = True
        h = self.common_headers({"Accept": "text/html"})
        r = self.s.get(IDMSA_BASE + "/appleauth/auth", headers=h, timeout=30)
        self.state.absorb(r, "auth-prefetch")
        ck = self._cookies()
        if ck.get("scnt"):
            self.state.scnt = ck["scnt"]
        self._log(f"[idmsa] auth-prefetch status={r.status_code} len={len(r.text or '')}")
        return r

    def verify_security_code(self, code: str):
        self._use_attrs = True
        url = IDMSA_BASE + "/appleauth/auth/verify/trusteddevice/securitycode"
        self._use_fd = True          # 2FA 必须带 FD 指纹
        h = self.common_headers({"Accept": "application/json, text/plain, */*",
                                 "Content-Type": "application/json",
                                 "X-Apple-App-Id": WIDGET_KEY_STORE})
        h["Content-Type"] = "application/json"
        if self.state.scnt:
            h["scnt"] = self.state.scnt
        r = self.s.post(url, headers=h,
                        data=json.dumps({"securityCode": {"code": str(code)}}), timeout=30)
        self.state.absorb(r, "securitycode")
        self._log(f"[idmsa] verify/trusteddevice status={r.status_code}")
        return r

    def trust_browser(self):
        self._use_attrs = True
        url = IDMSA_BASE + "/appleauth/auth/2sv/trust"
        self._use_fd = True
        h = self.common_headers({"Accept": "application/json, text/plain, */*",
                                 "Content-Type": "application/json",
                                 "X-Apple-App-Id": WIDGET_KEY_STORE})
        if self.state.scnt:
            h["scnt"] = self.state.scnt
        r = self.s.post(url, headers=h, timeout=30)
        self.state.absorb(r, "2sv/trust")
        ck = self._cookies()
        self.state.myacinfo = ck.get("myacinfo")
        self._log(f"[idmsa] 2sv/trust status={r.status_code} "
                  f"myacinfo={'OK' if self.state.myacinfo else 'NONE'}")
        return r

    # ══════════════ step_acquire_as_disa ★ ══════════════
    def step_acquire_as_disa(self):
        """
        0x14d6b22 — 这是 authx 能成功的关键。
        GET account/home → ssi → GET signIn 页取 stk → POST authx → as_disa
        """
        # 0) 已经有可用的 as_disa 就不再签发一次：重复 authx 会 541，而且
        #    每次都要服务端跑 9 秒。
        have = {c.name: c.value for c in self.s.cookies.jar}.get("as_disa")
        if have:
            probe = self.s.post(f"{self.store_base}/shop/accounthomex"
                                "?_a=fetchCustomerAccount&_m=home.customerAccount",
                                headers={"Accept": "*/*", "syntax": "graviton",
                                         "modelVersion": "v2", "X-Requested-With": "Fetch",
                                         "x-aos-model-page": "RetailHome"},
                                timeout=20)
            try:
                head = (probe.json() or {}).get("head") or {}
            except Exception:  # noqa: BLE001
                head = {}
            if probe.status_code < 400 and head.get("status") == 200:
                self.state.as_disa = have
                self._log("[idmsa] as_disa 仍有效，跳过 authx")
                return probe
            # The stored as_disa is dead but still in the jar, which makes
            # account/home answer 200 and swallow the ssi redirect. Drop the
            # store-side cookies so the documented 302 path can run.
            self._log("[idmsa] as_disa 已失效，清除 store 侧 cookie")
            for c in list(self.s.cookies.jar):
                if c.name.startswith("as_") or c.name == "shld_bt_ck":
                    try:
                        self.s.cookies.jar.clear(c.domain, c.path, c.name)
                    except Exception:  # noqa: BLE001
                        pass

        # 1) account/home 拿 ssi
        nav = {
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,image/apng,*/*;q=0.8,"
                       "application/signed-exchange;v=b3;q=0.7"),
            "Accept-Language": ACCEPT_LANG,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-User": "?1",
        }
        r = self.s.get(self.store_base + "/shop/account/home",
                       headers=nav, allow_redirects=False, timeout=30)
        loc = r.headers.get("location") or ""
        self._log(f"[idmsa] account/home status={r.status_code} loc={loc[:70]}")
        m = re.search(r"[?&]ssi=([^&\s]+)", loc)
        if not m and loc:
            # 303 → 需要跟第二跳
            r1b = self.s.get(loc, headers=dict(nav, **{"Sec-Fetch-Site": "cross-site",
                                                      "Referer": STORE_BASE + "/"}),
                             allow_redirects=False, timeout=30)
            loc = r1b.headers.get("location") or ""
            self._log(f"[idmsa] account/home 2nd hop {r1b.status_code} loc={loc[:70]}")
            m = re.search(r"[?&]ssi=([^&\s]+)", loc)
        if not m:
            # Already-authenticated sessions answer 200 on account/home and skip
            # the redirect that carries ssi. Follow the page and recover ssi from
            # wherever we land; the rest of the hop still works without it.
            self._log("[idmsa] account/home 未给出 ssi，改从落地页提取")
            landed = self.s.get(self.store_base + "/shop/account/home",
                                headers=nav, allow_redirects=True, timeout=30)
            m2 = re.search(r"[?&]ssi=([^&\s]+)", landed.url or "")
            if m2:
                ssi = m2.group(1)
            else:
                ssi = ""
        else:
            ssi = m.group(1)
        self.state.ssi = ssi
        base = self.store_base
        mm = re.match(r"(https://[^/]+)", loc)
        if mm:
            base = mm.group(1)

        # 2) signIn 页取 x-aos-stk
        # An empty ssi must not be sent as a bare query param.
        sign_in_url = f"{base}/shop/signIn/account" + (f"?ssi={ssi}" if ssi else "")
        # A bare ``text/html`` Accept makes the edge take a slow (~10s) path for
        # this 116 KB page; the full browser Accept list answers in ~0.3s.
        r2 = self.s.get(sign_in_url,
                        headers={
                            "Accept": ("text/html,application/xhtml+xml,application/xml;"
                                       "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"),
                            "Accept-Language": ACCEPT_LANG,
                            "Referer": base + "/",
                            "Sec-Fetch-Site": "same-origin",
                            "Sec-Fetch-Mode": "navigate",
                            "Sec-Fetch-Dest": "document",
                            "Upgrade-Insecure-Requests": "1",
                        },
                        timeout=30)
        # x-aos-stk / modelVersion / syntax / x-aos-model-page 都在 init_data.meta.h 里
        stk = self._parse_init_meta(r2.text or "")
        if not stk:
            for pat in (r'"x-aos-stk"\s*:\s*"([^"]+)"',
                        r'x-aos-stk["\s:]+([A-Za-z0-9_\-]+)'):
                mm = re.search(pat, r2.text or "")
                if mm:
                    stk = mm.group(1)
                    break
        self.state.stk = stk
        self._log(f"[idmsa] x-aos-stk={'OK' if stk else 'NONE'} len={len(stk or '')}")

        # 3) shld PoW —— 必须先拿 shld_bt_ck，否则 authx 一律 541
        try:
            from .apple_shld_v3 import run_shld
            ck = run_shld(self.s, base, ssi, verbose=self.verbose) if ssi else None
            if ck:
                self.state.shld_bt_ck = ck
            else:
                print("    [warn] shld_bt_ck 未获取，authx 可能 541")
        except Exception as e:
            print(f"    [warn] shld 执行失败: {type(e).__name__}: {e}")

        # 4) POST authx
        ax_h = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base,
            "Referer": sign_in_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "syntax": getattr(self, "_aos_meta", {}).get("syntax", "graviton"),
            "modelVersion": getattr(self, "_aos_meta", {}).get("modelVersion", "v2"),
            "X-Requested-With": "Fetch",
            "x-aos-model-page": getattr(self, "_aos_meta", {}).get(
                "x-aos-model-page", "idmsSignInPage"),
        }
        if stk:
            ax_h["x-aos-stk"] = stk
        authx_url = f"{base}/shop/signIn/idms/authx" + (f"?ssi={ssi}" if ssi else "")
        r3 = self.s.post(authx_url,
                         headers=ax_h, data="grantCode=", allow_redirects=False, timeout=30)
        self._log(f"[idmsa] authx status={r3.status_code}")

        as_disa = None
        sc = r3.headers.get("set-cookie") or ""
        mm = re.search(r"as_disa=([^;]+)", sc)
        if mm:
            as_disa = mm.group(1)
        ck = self._cookies()
        self.state.as_disa = as_disa or ck.get("as_disa")
        self.state.as_sfa = ck.get("as_sfa")
        self._log(f"[idmsa] as_disa={'OK' if self.state.as_disa else 'NONE'} "
                  f"as_sfa={'OK' if self.state.as_sfa else 'NONE'}")
        return r3

    def _parse_init_meta(self, html: str) -> str | None:
        """
        从 signIn 页 <script id="init_data"> 的 meta.h 里取 x-aos-stk，
        顺带把 modelVersion / syntax / x-aos-model-page 一起记下。
        实测路径：init_data.meta.h = {x-aos-model-page, modelVersion, x-aos-stk, syntax}
        """
        blk = re.search(r'<script id="init_data" type="application/json">(.*?)</script>',
                        html, re.S)
        if not blk:
            return None
        try:
            j = json.loads(blk.group(1))
        except Exception:
            return None
        meta = (j.get("meta") or {})
        h = meta.get("h") or {}
        self._aos_meta = {
            "x-aos-stk": h.get("x-aos-stk"),
            "modelVersion": h.get("modelVersion") or "v2",
            "syntax": h.get("syntax") or "graviton",
            "x-aos-model-page": h.get("x-aos-model-page") or "idmsSignInPage",
        }
        return self._aos_meta["x-aos-stk"]

    # ══════════════ step4_get_sct ★ ══════════════
    def step4_get_sct(self):
        url = IDMSA_BASE + "/appleauth/auth/questions/reset/iforgot"
        h = self.common_headers({"Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                 "X-Apple-App-Id": WIDGET_KEY_STORE,
                                 "Sec-Fetch-Mode": "navigate",
                                 "Sec-Fetch-Dest": "document"})
        r = self.s.get(url, headers=h, allow_redirects=False, timeout=30)
        self.state.absorb(r, "get_sct")
        sct = None
        loc = r.headers.get("location") or ""
        m = re.search(r"[?&]sct=([^&\s]+)", loc)
        if m:
            sct = m.group(1)
        if not sct:
            m = re.search(r'"?sct"?\s*[:=]\s*"?([A-Za-z0-9._\-]{10,})', r.text or "")
            if m:
                sct = m.group(1)
        self.state.sct = sct
        self._log(f"[idmsa] 4: sct {'OK' if sct else 'NONE'} | status={r.status_code}")
        return r

    # ══════════════ 主流程 ══════════════
    def login(self, email: str, password: str):
        self.step0_init_session()
        self.step_challenge()
        self.step1_federate(email)
        self.step2_signin_init(email, password)
        r3 = self.step3_signin_complete(email, password)
        if self.state.myacinfo:
            self.step_acquire_as_disa()
            self.step4_get_sct()
        return r3

    def login_for_store(self, email: str, password: str):
        r = self.login(email, password)
        self._log(f"[idmsa] Store login myacinfo="
                  f"{'OK' if self.state.myacinfo else 'NONE'}")
        return r

    # ---------- 工具 ----------
    def _cookies(self) -> dict:
        out = {}
        try:
            for c in self.s.cookies.jar:
                out[c.name] = c.value
        except Exception:
            try:
                out = self.s.cookies.get_dict()
            except Exception:
                pass
        return out


def fetch_code(url: str, retries: int = 2, interval: float = 1.2,
               timeout: float = 6.0) -> str | None:
    for i in range(retries):
        try:
            r = creq.get(url, impersonate="chrome", verify=False, timeout=timeout)
            m = re.search(r"\b(\d{6})\b", r.text or "")
            if m:
                return m.group(1)
        except Exception:
            pass
        if i < retries - 1:
            time.sleep(interval)
    return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--code-url", default=None)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    cli = IdmsaClient(proxy=a.proxy, verbose=True)
    r = cli.step0_init_session()
    cli.step1_federate(a.email)
    cli.step2_signin_init(a.email, a.password)
    r3 = cli.step3_signin_complete(a.email, a.password)
    print(f"\ncomplete: {r3.status_code} authType={getattr(cli,'auth_type',None)}")
    if cli.need_2fa:
        cli.prefetch_auth()
        code = fetch_code(a.code_url) if a.code_url else None
        print("code:", code)
        if code:
            cli.verify_security_code(code)
            cli.trust_browser()
    if cli.state.myacinfo:
        cli.step_acquire_as_disa()
        cli.step4_get_sct()
    print("\n最终状态:")
    for k in ("myacinfo", "as_disa", "as_sfa", "sct", "stk", "ssi", "account_country"):
        v = getattr(cli.state, k)
        print(f"  {k:16s} = {'OK' if v else 'NONE'} {str(v)[:40] if v else ''}")
