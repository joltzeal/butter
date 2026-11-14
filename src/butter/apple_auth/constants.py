"""Apple web constants.

Two sources, both authoritative:

* values recovered from the reference client's string pool, and
* values observed in a real Chrome session against appleid.apple.com
  (captured via Playwright: ``federate`` 200 + ``x-apple-hc-bits``).

Where the two disagreed, the live capture wins — see ``WIDGET_KEY_*`` and
``X-Apple-OAuth-Redirect-URI`` below.
"""

from __future__ import annotations

# --- endpoints -------------------------------------------------------------
IDMSA_BASE = "https://idmsa.apple.com"
IFORGOT_BASE = "https://iforgot.apple.com"
APPLEID_BASE = "https://appleid.apple.com"
ACCOUNT_APPLE_BASE = "https://account.apple.com"
STORE_BASE = "https://secure.store.apple.com"

# --- Apple web widget keys (public, shipped in the web pages) --------------
# account.apple.com / appleid.apple.com sign-in widget
WIDGET_KEY = "af1139274f266b22b68c2a3e7ad932cb3c0bbe854e13a79af78dcc73136882c3"
# The sign-in flow uses the same key on account.apple.com; the store domain uses
# its own key. Keeping them as separate names avoids the earlier bug where a
# store key was sent to the IDMSA endpoint (-> 400 empty body).
WIDGET_KEY_ACCOUNT = WIDGET_KEY
WIDGET_KEY_STORE = "a797929d224abb1cc663bb187bbcd02f7172ca3a84df470380522a7c6092118b"

# OAuth redirect used by the account (IDMSA) flow; the store flow overrides it.
# The store sign-in widget authenticates under domain id 35 (Apple ID) / 39
# (store); captured requests from secure*.store.apple.com carry 35.
STORE_DOMAIN_ID = "35"
# The v3 store sign-in widget (``a797929d…`` client) authenticates under 39.
STORE_DOMAIN_ID_STORE = "39"
OAUTH_REDIRECT_ACCOUNT = ACCOUNT_APPLE_BASE
OAUTH_REDIRECT_STORE = STORE_BASE

# --- SRP group (RFC 5054 3072-bit, hex without padding) --------------------
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
SRP_g = 2
SRP_k_HEX = "05b9e8ef059c6b32ea59fc1d322d37f04aa30bae5aa9003b8321e21ddb04e300"

# --- client impedance ------------------------------------------------------
# macOS / Chrome 157 matches the capture that produced a successful federate.
# A Windows UA with macOS TLS (curl_cffi) is an impedance mismatch Apple scores.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)
UA_ALT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Chromium";v="157", "Not=A?Brand";v="99"'

def current_user_agent() -> str:
    """Prefer the UA that came with a pinned fingerprint, if any."""
    from .fingerprint import pinned_user_agent

    return pinned_user_agent() or UA


COMMON_HEADERS: dict[str, str] = {
    "User-Agent": UA,
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Origin": "https://idmsa.apple.com",
    "Referer": "https://idmsa.apple.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "X-Apple-Domain-Id": "11",
    "X-Apple-Widget-Key": WIDGET_KEY,
    "X-Apple-OAuth-Client-Id": WIDGET_KEY,
    "X-Apple-OAuth-Client-Type": "firstPartyAuth",
    "X-Apple-OAuth-Redirect-URI": OAUTH_REDIRECT_ACCOUNT,
    "X-Apple-OAuth-Response-Type": "code",
    "X-Apple-OAuth-Response-Mode": "web_message",
    "X-Apple-Privacy-Consent": "true",
    "X-Apple-Privacy-Consent-Accepted": "true",
    "X-Requested-With": "XMLHttpRequest",
}

STORE_HEADERS: dict[str, str] = {
    "User-Agent": UA,
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "*/*",
    "syntax": "graviton",
    "modelVersion": "v2",
    "x-aos-model-page": "RetailHome",
    "X-Requested-With": "Fetch",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

# Store RPC model keys ------------------------------------------------------
BILLING_INFO = "home.customerAccount.billingInfo"
BILLING_OVERLAY = "home.customerAccount.billingInfo.editBillingDetailsOverlay"
BILLING_OVERLAY_REMOVE = "home.customerAccount.billingInfo.removeBillingDetailsOverlay"

ADDR_PREFIX = f"{BILLING_OVERLAY}.editBillingAddressInfo.editAddress"
CONTACT_PREFIX = f"{BILLING_OVERLAY}.editBillingContactInfo.editAddress"
PAY_PREFIX = f"{BILLING_OVERLAY}.editPaymentDetails"
CARD_PREFIX = f"{PAY_PREFIX}.cardInputs.cardInput"

RPC_ACC_HOME = "/shop/accounthomex"
RPC_MODEL_FETCH_ID = "x-aos-ui-fetch-call-1"
