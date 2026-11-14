#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple Store 账单读写客户端 —— 复刻 src/apple_auth/store_client.py

来源: payload.bin 偏移 0x14dcb70-0x14dd500（常量）+ 0x14c97a9（fetch_billing_worker）
      0x14c8125（billing_worker）

════════ 核心机制：Graviton 协议 ════════
所有业务调用都是 POST /shop/accounthomex，form-urlencoded，靠 a/m/ds 三个参数寻址：

    a  = 动作序列（JSON 数组，每次调用递增）
    m  = 模型路径，如 home.dashboards
    ds = 数据集

请求头：
    syntax: graviton
    modelVersion: v2
    x-aos-model-page: RetailHome          ← 注意不是 idmsSignInPage
    x-aos-stk: <从 signIn 页取的 stk>
    x-aos-ui-fetch-call-1: <fetch_id>     ← 每次随机 8 位小写+数字
    X-Requested-With: Fetch
    Content-Type: application/x-www-form-urlencoded

════════ 关键模型路径 ════════
home.dashboards                                             读账单概览
home.customerAccount.billingInfo                            账单详情
home.customerAccount.billingInfo.editBillingDetailsOverlay  编辑面板
...editBillingDetailsOverlay.editBillingAddressInfo.editAddress.city / .state
    / .countryCode / .street / .postalCode / .street2
...editBillingContactInfo.editAddress.firstName / .lastName / .fullDaytimePhone
...editPaymentDetails.displayCardType
...editPaymentDetails.cardInputs.cardInput.cardNumberForBinDetection
    / .selectCardType / .expiration / .cardNumber
...editBillingDetailsOverlay.editPaymentDetails            checkCreditCardType
...editBillingDetailsOverlay                               saveBillingDetails
home.customerAccount.billingInfo.removeBillingDetailsOverlay

════════ 卡号加密 ════════
_encrypt_card(card_number, pub_key_b64, key_hash)
    → RSA-OAEP(MGF1-SHA256) 加密
    → JSON: {"cipherText": b64, "publicKeyHash": key_hash}
RSA 公钥从 edit_billing 返回的 config 里取（publicKey / publicKeyHash）
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import string
from urllib.parse import urlparse

from curl_cffi import requests as creq

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ══════════ 常量（store_client.py）══════════
STORE_BASE = "https://secure.store.apple.com"
STORE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
STORE_LANG = "en-US,en;q=0.9"
MODEL_PAGE = "RetailHome"

# 地址库
US_LOCATIONS = [
    ("CA", "90210", "Beverly Hills"), ("CA", "94102", "San Francisco"),
    ("CA", "90001", "Los Angeles"), ("TX", "75201", "Dallas"),
    ("TX", "77002", "Houston"), ("TX", "78201", "San Antonio"),
    ("FL", "33101", "Miami"), ("FL", "32099", "Jacksonville"),
    ("FL", "33401", "West Palm Beach"), ("IL", "60601", "Chicago"),
    ("IL", "60290", "Chicago"), ("IL", "62701", "Springfield"),
    ("WA", "98101", "Seattle"), ("WA", "98004", "Bellevue"),
    ("WA", "99201", "Spokane"),
]
CA_LOCATIONS = [
    ("ON", "M5H2N2", "Toronto"), ("ON", "K1A0A9", "Ottawa"),
    ("ON", "N2A2S6", "Kitchener"), ("BC", "V6B1A1", "Vancouver"),
    ("AB", "T2P1J9", "Calgary"), ("QC", "H2Y1C6", "Montreal"),
    ("MB", "R3C0P8", "Winnipeg"), ("NS", "B3H2Y9", "Halifax"),
]
GB_LOCATIONS = [
    ("Greater London", "SW1A 1AA", "London"),
    ("Greater Manchester", "M1 1AE", "Manchester"),
    ("West Midlands", "B1 1AA", "Birmingham"),
    ("West Yorkshire", "LS1 1UR", "Leeds"),
    ("Merseyside", "L1 8JQ", "Liverpool"),
    ("South Yorkshire", "S1 2HE", "Sheffield"),
    ("Bristol", "BS1 4DJ", "Bristol"),
    ("Edinburgh", "EH1 1YZ", "Edinburgh"),
    ("Cardiff", "CF10 1EP", "Cardiff"),
    ("Belfast", "BT1 1AA", "Belfast"),
]
AU_LOCATIONS = [
    ("NSW", "2000", "Sydney"), ("VIC", "3000", "Melbourne"),
    ("QLD", "4000", "Brisbane"), ("SA", "5000", "Adelaide"),
    ("WA", "6000", "Perth"), ("TAS", "7000", "Hobart"),
    ("NT", "0800", "Darwin"), ("ACT", "2600", "Canberra"),
]
FIRST_NAMES = ["James", "John", "Robert", "Michael", "William", "David",
               "Richard", "Joseph", "Thomas", "Charles", "Mary", "Patricia",
               "Jennifer", "Linda", "Barbara", "Elizabeth", "Susan", "Jessica", "Sarah"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
              "Miller", "Davis", "Wilson", "Anderson", "Taylor", "Thomas",
              "Jackson", "White"]
# fetch_billing_worker 判定"是否绑卡"的字段集合（0x14c9120-0x14c91c0）。
# 只看 removeBillingDetails 会漏掉只显示卡尾号/支付方式的账号。
BILLING_INDICATORS = (
    "removeBillingDetails",
    "editBillingDetails",
    "billingInfo",
    "cardSuffix",
    "lastFour",
    "lastFourDigits",
    "primaryPaymentMethod",
    "paymentInfo",
    "billingDetails",
    "displayCardType",
)

STREETS = ["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Park Blvd",
           "Washington St", "Lake View Dr", "Pine St", "Elm Ave", "River Rd"]


def _rand_id(n: int = 8) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def random_phone(country: str = "US") -> str:
    if country == "GB":
        return "07" + "".join(random.choice(string.digits) for _ in range(9))
    if country == "AU":
        return "04" + "".join(random.choice(string.digits) for _ in range(8))
    return "".join(random.choice(string.digits) for _ in range(10))


def random_street() -> str:
    return f"{random.randint(100, 9999)} {random.choice(STREETS)}"


def normalize_expiry(value: str) -> str:
    """Return ``MM/YY`` from the shapes an operator might paste."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 4:
        return f"{digits[:2]}/{digits[2:]}"
    if len(digits) == 6:
        return f"{digits[:2]}/{digits[2:4]}"
    return value or ""


def detect_card_type(card_number: str) -> str:
    """_detect_card_type: 前缀判定"""
    n = re.sub(r"\D", "", card_number or "")
    if n.startswith("4"):
        return "VISA"
    if n[:2] in ("34", "37"):
        return "AMERICAN_EXPRESS"
    if n.startswith("6"):
        return "DISCOVER"
    if n.startswith("5"):
        return "MASTERCARD"
    return "VISA"


def bin_detection_str(card_number: str) -> str:
    return re.sub(r"\D", "", card_number or "")[:8]


def encrypt_card(card_number: str, pub_key_b64: str, key_hash: str) -> str:
    """
    _encrypt_card: RSA-OAEP(MGF1-SHA256) 加密卡号
    返回 {"cipherText": b64, "publicKeyHash": key_hash}
    """
    key_der = base64.b64decode(pub_key_b64)
    pub = serialization.load_der_public_key(key_der)
    ct = pub.encrypt(
        card_number.encode("utf-8"),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None),
    )
    return json.dumps({"cipherText": base64.b64encode(ct).decode(),
                       "publicKeyHash": key_hash}, separators=(",", ":"))


def is_session_expired(status: int, location: str = "", body: str = "") -> bool:
    """True when a store response means "the session is gone".

    Apple signals this three different ways: a 401, a 302 whose Location points
    at ``sorry?type=SESSIONEXPIRY``, or a 200 whose JSON head carries the same
    URL. Only the first two are status-visible, so the body check matters.
    """
    if status == 401:
        return True
    if "SESSIONEXPIRY" in (location or ""):
        return True
    return "SESSIONEXPIRY" in (body or "")


def find_in_dict(d, key):
    """_find_in_dict: 递归找第一个命中的 key"""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = find_in_dict(v, key)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = find_in_dict(v, key)
            if r is not None:
                return r
    return None



LOGGER = logging.getLogger("butter.store")


class StoreAuthError(RuntimeError):
    """The store rejected the identity session (authx not 200)."""


class StoreClient:
    """StoreClient —— 账单读写"""

    def __init__(self, session=None, proxy: str | None = None, base: str = STORE_BASE):
        if session is None:
            kw = {"impersonate": "chrome142"}
            if proxy:
                kw["proxy"] = proxy
            session = creq.Session(**kw)
        self.s = session
        self.base = (base or STORE_BASE).rstrip("/")
        self.stk = None
        self._call = 0
        # Store risk tokens, seeded from accounts.json so a saved session can
        # skip the authx handshake entirely.
        self.as_disa = ""
        self.as_sfa = ""
        self.ssi = ""

    # ---------- 基础 ----------
    def _headers(self, extra: dict | None = None) -> dict:
        """0x14dc960: 账单请求头"""
        self._call += 1
        h = {
            "User-Agent": STORE_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Accept-Language": STORE_LANG,
            "syntax": "graviton",
            "modelVersion": "v2",
            "x-aos-model-page": MODEL_PAGE,
            "X-Requested-With": "Fetch",
            "Origin": self.base,
            "Referer": self.base + "/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            f"x-aos-ui-fetch-call-{self._call}": _rand_id(8),
        }
        if self.stk:
            h["x-aos-stk"] = self.stk
        if extra:
            h.update(extra)
        return h

    def _parse_store_response(self, resp):
        try:
            return resp.json()
        except Exception:
            return None

    def _update_stk(self, data):
        if isinstance(data, str):
            m = re.search(r'"x-aos-stk"\s*:\s*"([^"]+)"', data)
            if m:
                self.stk = m.group(1)
        elif isinstance(data, dict):
            v = find_in_dict(data, "x-aos-stk") or find_in_dict(data, "stk")
            if v:
                self.stk = v

    def _inject_risk_cookies(self):
        """_inject_risk_cookies: as_sfa 明文是固定的"""
        raw = "2|us|us||en_US|consumer|internet|0|0|1"   # exe 中该串解码即此值
        self.s.cookies.set("as_sfa", base64.b64encode(raw.encode()).decode().rstrip("="),
                           domain=".apple.com", path="/")
        self.s.cookies.set("dssid2", getattr(self, "_dssid2", None) or
                           "%08x-%04x-%04x-%04x-%012x" % (
                               random.getrandbits(32), random.getrandbits(16),
                               random.getrandbits(16), random.getrandbits(16),
                               random.getrandbits(48)),
                           domain=".apple.com", path="/")
        self.s.cookies.set("dssf", "1", domain=".apple.com", path="/")
        self.s.cookies.set("sh_spksy", ".", domain=".apple.com", path="/")
        for k, v in (("aitspod", "1"), ("pxro", "2"), ("apldfltcid", "undefined")):
            self.s.cookies.set(k, v, domain=".apple.com", path="/")

    def _probe_session(self) -> bool:
        """One cheap RPC to see whether a restored ``as_disa`` still works."""
        try:
            r = self._post("fetchDashboard", "home.dashboards")
        except Exception as exc:  # noqa: BLE001 - retry the full handshake
            LOGGER.debug("[store] 会话探测异常: %s", exc)
            return False
        if r.status_code >= 400:
            return False
        try:
            payload = r.json()
        except Exception:  # noqa: BLE001 - HTML repost page means unauthenticated
            LOGGER.debug("[store] 会话探测: 非 JSON")
            return False
        head = (payload or {}).get("head") or {}
        if head.get("status") in (302, 541) or "SESSIONEXPIRY" in json.dumps(payload or {}):
            LOGGER.debug("[store] 会话探测: SESSIONEXPIRY")
            return False
        LOGGER.info("[store] 复用已保存的 store 会话")
        return True

    # ---------- 0) warmup + alive（exe fetch_billing_worker 的两步前置）----------
    def fast_probe(self, base_hint: str = "") -> str:
        """Skip warmup when a previously verified host is known.

        The ``secureN`` host matters: only the one that owns the session returns
        data, and the others answer 200 with empty panes (silently wrong). So the
        cached host is trusted, and only when it fails do we fall back to a full
        warmup walk.
        """
        candidate = base_hint or self.base
        if not candidate:
            return ""
        saved, self.base = self.base, candidate
        try:
            if self.alive_payload():
                return candidate
        except Exception:  # noqa: BLE001 - fall back to warmup
            LOGGER.debug("[store] fast_probe 失败，回退 warmup")
        self.base = saved or candidate
        return ""

    def warmup_with_retry(self, max_attempts: int = 4) -> str:
        """Pick a reachable ``secureN`` host before doing anything authenticated.

        ``fetch_billing_worker.warmup_with_retry`` walks candidate hosts from
        ``/shop/account/home`` and keeps the first one that is not a session
        error. Starting the RPC against a dead host reads as SESSIONEXPIRY even
        when the cookies are fine.
        """
        candidates: list[str] = []
        for url in (self.base, STORE_BASE):
            for m in re.finditer(r"https://secure(\d+)\.store\.apple\.com", url or ""):
                candidate = m.group(0)
                if candidate not in candidates:
                    candidates.append(candidate)
        if not candidates:
            candidates = [self.base]

        nav = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": STORE_LANG,
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
        }
        for entry in candidates[:max_attempts]:
            try:
                resp = self.s.get(f"{entry}/shop/account/home", headers=nav,
                                  allow_redirects=False, timeout=20)
            except Exception as exc:  # noqa: BLE001 - try the next host
                LOGGER.debug("[store] warmup %s 失败: %s", entry, exc)
                continue
            location = resp.headers.get("location") or ""
            if resp.status_code in (301, 302, 303, 307, 308):
                host = re.match(r"(https://[^/]+)", location)
                if host:
                    self.base = host.group(1)
                    LOGGER.info("[store] warmup 命中 %s", self.base)
                    return self.base
                continue
            if "SESSIONEXPIRY" not in (resp.text or ""):
                self.base = entry
                LOGGER.info("[store] warmup 命中 %s", entry)
                return entry
        LOGGER.warning("[store] warmup 未找到可用 host，沿用 %s", self.base)
        return self.base

    def alive_payload(self) -> bool:
        """Cheap authenticated call used to confirm the session before real work."""
        try:
            resp = self._post("fetchDashboard", "home.dashboards")
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("[store] alive 失败: %s", exc)
            return False
        if resp.status_code >= 400:
            return False
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001 - repost page / empty body
            return False
        head = (payload or {}).get("head") or {}
        if head.get("status") in (302, 541):
            return False
        return "SESSIONEXPIRY" not in json.dumps(payload or {})

    def prepare(self) -> bool:
        """warmup → authenticate → alive，账单调用前的固定前置。

        ``authenticate`` returns the freshly minted ``x-aos-stk``; without
        assigning it the following RPC still carries the stale token and the
        edge answers 403 before it ever looks at the session.
        """
        self.warmup_with_retry()
        ok = self.authenticate()
        if isinstance(ok, dict):
            self.stk = ok.get("stk") or self.stk
        elif not ok:
            return False
        if not self.stk:
            return False
        return self.alive_payload()

    # ---------- 1) authenticate ----------
    def authenticate(self):
        """
        0x14dd413 authenticate：
            GET  /shop/account/home       → 302 → ssi
            GET  /shop/signIn/account?ssi → x-aos-stk
            POST /shop/signIn/idms/authx  → as_disa / as_sfa
        """
        if self.as_disa and self._probe_session():
            return {"stk": self.stk, "status": "cached"}
        # Navigate before seeding risk cookies: a jar that already carries
        # as_sfa/dssid2 makes the edge answer 200 (landing page) instead of the
        # redirect that carries ssi.
        r = self.s.get(self.base + "/shop/account/home",
                       headers={"User-Agent": STORE_UA,
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": STORE_LANG,
                                "Sec-Fetch-Site": "none",
                                "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Dest": "document",
                                "Upgrade-Insecure-Requests": "1"},
                       allow_redirects=False, timeout=30)
        loc = r.headers.get("location") or ""
        m = re.search(r"[?&]ssi=([^&\s]+)", loc)
        ssi = m.group(1) if m else None
        mm = re.match(r"(https://[^/]+)", loc)
        if mm:
            self.base = mm.group(1)
        if not ssi:
            LOGGER.warning("[store] account/home 未给出 ssi (status=%s)", r.status_code)
            return False

        self._inject_risk_cookies()
        self.ssi = ssi
        sign_in = f"{self.base}/shop/signIn/account?ssi={ssi}"
        # Full browser Accept list: a bare text/html takes a ~10s edge path.
        r2 = self.s.get(sign_in, headers={"User-Agent": STORE_UA,
                                          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                                          "Referer": self.base + "/"}, timeout=30)
        for pat in (r'"x-aos-stk"\s*:\s*"([^"]+)"', r'x-aos-stk["\s:]+([A-Za-z0-9_\-]+)'):
            mm = re.search(pat, r2.text or "")
            if mm:
                self.stk = mm.group(1)
                break

        ax = {
            "User-Agent": STORE_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "syntax": "graviton",
            "modelVersion": "v2",
            "X-Requested-With": "Fetch",
            "x-aos-model-page": "idmsSignInPage",
            "Origin": self.base,
            "Referer": sign_in,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if self.stk:
            ax["x-aos-stk"] = self.stk
        ax_resp = self.s.post(f"{self.base}/shop/signIn/idms/authx?ssi={ssi}",
                              headers=ax, data="grantCode=", allow_redirects=False, timeout=30)
        ax_ck = ax_resp.headers.get("set-cookie") or ""
        for name in ("as_disa", "as_sfa"):
            m = re.search(rf"{name}=([^;]+)", ax_ck)
            if m:
                setattr(self, name, m.group(1))
        LOGGER.info("[store] authx status=%s stk=%s", ax_resp.status_code, (self.stk or "")[:12])
        if ax_resp.status_code != 200:
            # 541 == the store does not accept this identity session. Surfacing it
            # matters: the RPC afterwards answers 200 with empty panes, which used
            # to read as "this account has no billing".
            raise StoreAuthError(
                f"商店会话建立失败 (status={ax_resp.status_code})，需要重新登录"
            )
        return {"stk": self.stk, "status": ax_resp.status_code}

    def _gcall(self, action: str, model: str, data: str = ""):
        """Graviton call in ``?_a=&_m=`` query form.

        This is the shape the page's own ``a`` payload advertises::

            {"url": ".../shop/accounthomex?_a=fetchCustomerAccount&_m=home.customerAccount",
             "submit": true}

        Posting ``a=``/``m=`` in the body instead answers 200 with every pane
        replaced by "Information about … is currently unavailable" — which reads
        as "no billing" rather than an error.
        """
        url = f"{self.base}/shop/accounthomex?_a={action}&_m={model}"
        headers = self._headers({"Content-Type": "application/x-www-form-urlencoded"})
        return self.s.post(url, headers=headers, data=data, allow_redirects=False, timeout=30)

    def fetch_customer_account(self) -> dict:
        """``?_a=fetchCustomerAccount`` — where billing actually lives."""
        r = self._gcall("fetchCustomerAccount", "home.customerAccount")
        try:
            payload = r.json()
        except Exception:
            return {}
        return ((payload.get("body") or {}).get("home") or {}).get("customerAccount") or {}

    # ---------- 2) Graviton 调用 ----------
    def _post(self, action: str, model: str, ds: str = "home",
              extra: dict | None = None, params: dict | None = None):
        self._call += 1
        payload = {
            "a": json.dumps([action], separators=(",", ":")),
            "m": model,
            "ds": ds,
        }
        if extra:
            payload.update(extra)
        url = f"{self.base}/shop/accounthomex"
        r = self.s.post(url, headers=self._headers(params), data=payload,
                        allow_redirects=False, timeout=30)
        return r

    def fetch_dashboard(self, data: dict | None = None):
        """fetchDashboard: m=home.dashboards"""
        r = self._post("fetchDashboard", "home.dashboards", extra=data)
        return self._parse_store_response(r), r

    def edit_billing(self, data: dict | None = None):
        """editBillingDetails: m=home.customerAccount.billingInfo"""
        r = self._post("editBillingDetails", "home.customerAccount.billingInfo", extra=data)
        return self._parse_store_response(r), r

    def remove_billing(self):
        """removeBillingDetails"""
        r = self._post("removeBillingDetails",
                       "home.customerAccount.billingInfo", ds="home")
        return self._parse_store_response(r), r

    # ---------- 3) 账单写入 ----------
    def save_billing(
        self,
        card_number: str,
        card_expiry: str,
        pub_key_b64: str,
        key_hash: str,
        first_name: str = "",
        last_name: str = "",
        street: str = "",
        street2: str = "",
        city: str = "",
        state: str = "",
        zipcode: str = "",
        phone: str = "",
        country_code: str = "US",
        card_type: str = "",
        email: str = "",
    ) -> tuple[dict, object]:
        """Commit the whole billing overlay in one ``saveBillingDetails`` POST.

        Shape verified against a real browser request. Two quirks are load-bearing:

        * every field is addressed by its full model path in the form body — the
          per-field edit calls are not needed
        * ``displayCardType`` and ``cardNumberForBinDetection`` carry **literal
          strings** (``"editPaymentDetails.d.displayCardType=null"``), not values.

        ``cardNumber`` is the RSA-OAEP envelope as compact JSON.
        """
        base = "home.customerAccount.billingInfo.editBillingDetailsOverlay"
        addr = f"{base}.editBillingAddressInfo.editAddress"
        cont = f"{base}.editBillingContactInfo.editAddress"
        card = f"{base}.editPaymentDetails.cardInputs.cardInput"

        cipher = encrypt_card(card_number, pub_key_b64, key_hash)
        digits = re.sub(r"\D", "", card_number or "")
        card_type = card_type or detect_card_type(card_number)
        exp = normalize_expiry(card_expiry)

        form = {
            f"{addr}.city": city,
            f"{addr}.state": state,
            f"{addr}.countryCode": country_code,
            f"{addr}.street": street,
            f"{addr}.postalCode": zipcode,
            f"{addr}.street2": street2,
            f"{cont}.firstName": first_name,
            f"{cont}.lastName": last_name,
            f"{cont}.fullDaytimePhone": phone,
            # Literal payloads the page itself posts; they are not real values.
            f"{base}.editPaymentDetails.displayCardType": "editPaymentDetails.d.displayCardType=null",
            f"{card}.cardNumberForBinDetection": "cardInput.d.cardNumberForBinDetection=",
            f"{card}.selectCardType": card_type,
            f"{card}.expiration": exp,
            f"{card}.cardNumber": cipher,
        }
        if email:
            form[f"{cont}.emailAddress"] = email

        url = f"{self.base}/shop/accounthomex?_a=saveBillingDetails&_m={base}"
        headers = self._headers({"Content-Type": "application/x-www-form-urlencoded"})
        resp = self.s.post(url, headers=headers, data=form, allow_redirects=False, timeout=40)
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            payload = {"raw": (resp.text or "")[:400]}

        head = (payload or {}).get("head") or {}
        status = head.get("status")
        if resp.status_code >= 400 or status not in (200, 201, None):
            detail = head.get("data") or payload
            raise StoreAuthError(f"保存账单失败 (status={status or resp.status_code}): {detail}")
        LOGGER.info("[store] saveBillingDetails ok | %s *%s %s",
                    card_type, digits[-4:], exp)
        return payload, resp

    # ---------- 4) 查询 ----------
    @staticmethod
    @staticmethod
    def parse_customer_billing(customer_account: dict) -> dict:
        """Flatten ``customerAccount.billingInfo`` into UI fields.

        Shape (verified against a live account)::

            billingInfo.d.billingAddress.d  = {street, street2, city, state,
                                               postalCode, countryCode, companyName}
            billingInfo.d.billingContact.d  = {firstName, lastName,
                                               fullDaytimePhone, emailAddress}
            billingInfo.d.billingPaymentDetails.d = {displayCardType, cardSuffix, expiration}
        """
        info = customer_account.get("billingInfo") or {}

        def sub(key: str) -> dict:
            # The sub-blocks hang directly off billingInfo; billingInfo.d is null.
            return ((info.get(key) or {}).get("d") or {})

        address = sub("billingAddress")
        contact = sub("billingContact")
        # Payment sits one level deeper: billingPaymentDetails.paymentDetails.d
        pay = ((info.get("billingPaymentDetails") or {}).get("paymentDetails") or {}).get("d") or {}
        digits = re.sub(r"\D", "", str(pay.get("cardNumber") or ""))
        suffix = (
            str(pay.get("cardSuffix") or pay.get("lastFour")
                or pay.get("lastFourDigits") or "")
            or digits[-4:]
        )
        has_card = bool(pay) and (
            bool(suffix)
            or bool(pay.get("displayCardType"))
            or bool(pay.get("paymentType"))
            or bool(pay.get("paymentTypeLabel"))
            or bool(pay.get("cardExpiry"))
            or bool(pay.get("expiration"))
        )
        return {
            "has_card": has_card,
            "card_suffix": suffix,
            "expiry": str(pay.get("cardExpiry") or pay.get("expiration") or ""),
            "display_card_type": str(
                pay.get("displayCardType") or pay.get("paymentTypeLabel")
                or pay.get("paymentType") or ""
            ),
            "card_number": digits,
            "first_name": str(contact.get("firstName") or ""),
            "last_name": str(contact.get("lastName") or ""),
            "phone": str(contact.get("fullDaytimePhone") or ""),
            "email": str(contact.get("emailAddress") or ""),
            "company": str(address.get("companyName") or ""),
            "street": str(address.get("street") or ""),
            "street2": str(address.get("street2") or ""),
            "city": str(address.get("city") or "").rstrip(", "),
            "state": str(address.get("state") or ""),
            "postal_code": str(address.get("postalCode") or ""),
            "country_code": str(address.get("countryCode") or ""),
            "raw": {"billingInfo": info},
        }

    def fetch_billing_info(self) -> dict:
        """Read billing in a single RPC.

        ``fetchCustomerAccount`` already carries address / contact / payment, so
        the dashboard call and the per-pane edit calls the page makes are pure
        overhead here: one request, ~0.45s warm.
        """
        ca = self.fetch_customer_account()
        info = self.parse_customer_billing(ca)
        if not (ca.get("billingInfo") or {}).get("billingAddress"):
            err = (ca.get("error") or {})
            infos = (err.get("d") or {}).get("infos") or []
            if infos:
                info["error"] = str(infos[0])
        return info

    @staticmethod
    def account_error(dashboard: dict | None) -> str:
        """Surface an in-band error from ``customerAccount`` (e.g. unavailable).

        Apple answers ``head.status: 200`` and hides the failure inside
        ``body.home.customerAccount.error.infos``. Treating that as "no card"
        would silently report the wrong billing state.
        """
        body = (dashboard or {}).get("body") or {}
        ca = ((body.get("home") or {}).get("customerAccount") or {})
        err = ca.get("error") or {}
        infos = (err.get("d") or {}).get("infos") or []
        return str(infos[0]) if infos else ""

    def has_billing(self, dashboard_data: dict | None = None) -> tuple[bool, dict]:
        """Whether the account has a payment method attached.

        Mirrors ``fetch_billing_worker``: any one of :data:`BILLING_INDICATORS`
        being present counts. Checking only ``removeBillingDetails`` misses
        accounts that merely expose a card suffix.
        """
        data = dashboard_data
        if data is None:
            data, _ = self.fetch_dashboard()
        if not data:
            return False, {}
        found = {key: find_in_dict(data, key) for key in BILLING_INDICATORS}
        indicators = {key: value for key, value in found.items() if value is not None}
        return bool(indicators), indicators


if __name__ == "__main__":
    print("StoreClient 常量自检")
    print("  US 地址数:", len(US_LOCATIONS), "| GB:", len(GB_LOCATIONS))
    print("  卡类型检测:")
    for n in ("4111111111111111", "378282246310005", "5555555555554444", "6011111111111117"):
        print(f"    {n} -> {detect_card_type(n)}")
    _v = base64.b64encode(b"2|us|us||en_US|consumer|internet|0|0|1").decode().rstrip("=")
    _ref = "Mnx1c3x1c3x8ZW5fVVN8Y29uc3VtZXJ8aW50ZXJuZXR8MHwwfDE"
    print(f"  as_sfa: {_v}  (与 exe 一致: {_v == _ref})")
    print("  BIN:", bin_detection_str("4111 1111 1111 1111"))
