from __future__ import annotations

import json
import random

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from butter.apple_auth.billing import (
    bin_detection_str,
    detect_card_type,
    encrypt_card,
    fill_address,
    normalize_card_expiry,
    random_phone,
    split_expiry,
)
from butter.apple_auth.fingerprint import fd_client_info_matching_common_headers, format_gmt_offset
from butter.apple_auth.hashcash import solve_challenge, solve_pow
from butter.apple_auth.http import mask_proxy, new_fetch_id, rotate_sid
from butter.apple_auth.apple_store_client import find_in_dict, is_session_expired
from butter.core.address_parser import parse_clipboard
from butter.core.proxy import build_profile, render_profile
from butter.core.services import is_retryable
from butter.core.store import Account, AccountStore, Settings


# --- crypto helpers --------------------------------------------------------
def test_encrypt_card_roundtrip():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    import base64

    payload = encrypt_card("4111111111111111", base64.b64encode(pub_der).decode(), "hash123")
    assert payload["publicKeyHash"] == "hash123"
    plain = key.decrypt(
        base64.b64decode(payload["cipherText"]),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=b""),
    )
    assert plain == b"4111111111111111"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("03/27", "03/27"), ("3/27", "03/27"), ("0327", "03/27"), ("03/2027", "03/27"), ("2027-03", "03/27")],
)
def test_normalize_card_expiry(raw, expected):
    assert normalize_card_expiry(raw) == expected


def test_split_expiry():
    assert split_expiry("3/2030") == ("03", "30")


@pytest.mark.parametrize(
    ("card", "brand"),
    [("4111111111111111", "VISA"), ("378282246310005", "AMERICAN_EXPRESS"), ("5555555555554444", "MASTERCARD")],
)
def test_card_brand(card, brand):
    assert detect_card_type(card) == brand


def test_bin_detection():
    assert bin_detection_str("4111 1111 1111 1111") == "411111"


# --- fingerprint -----------------------------------------------------------
def test_fd_client_info_shape():
    blob = json.loads(fd_client_info_matching_common_headers("Asia/Shanghai"))
    assert set(blob) == {"U", "L", "Z", "V", "F"}
    assert blob["Z"] == "GMT+08:00"
    assert "Chrome" in blob["U"]


def test_gmt_offset_format():
    # The browser sends Z with the GMT prefix (recovered from #fdcBrowserData).
    assert format_gmt_offset(-360) == "GMT-06:00"
    assert format_gmt_offset(480) == "GMT+08:00"


# --- shld / hashcash -------------------------------------------------------
def test_hashcash_matches_captured_header():
    from butter.apple_auth import hashcash

    # Real header captured from the sign-in page (bits=10, empty email slot).
    real = "1:10:20261111114749:7ee87923eed576c45ee5c4cd94d76d60::1108"
    assert hashcash.verify(real, 10)
    assert not hashcash.verify(real, 40)


def test_hashcash_solves_to_spec():
    from butter.apple_auth import hashcash

    header = hashcash.solve_header("750f73542bc885c2e2e3c8baa3f0f684", 10)
    assert header.count(":") == 5 and "::" in header
    assert hashcash.verify(header, 10)



def test_hashcash_empty_challenge_is_ignored():
    from butter.apple_auth import hashcash

    assert hashcash.solve_header("", 10) == ""
    assert hashcash.solve("abc", 0) == (-1, 0)



def test_mask_proxy_hides_password():
    assert "****" in mask_proxy("socks5://user:secret@1.2.3.4:1080")
    assert mask_proxy("") == "(no proxy)"


def test_rotate_sid_is_sticky_and_replaces_old_sid():
    url = rotate_sid("socks5://u:p@h:1080", "abc123", "HK")
    assert "-sid-abc123-t-10" in url
    again = rotate_sid(url, "zzz", "HK")
    assert "-sid-abc123" not in again and "-sid-zzz" in again


def test_new_fetch_id_shape():
    # Apple derives X-Apple-Auth-Attributes length from this string; the browser
    # shape (37 chars, auth-<8>-<4>-<4>-<4>-<8>) is what yields a 292-char blob.
    fid = new_fetch_id()
    assert len(fid) == 37
    assert fid.startswith("auth-")
    assert [len(part) for part in fid.split("-")[1:]] == [8, 4, 4, 4, 8]


# --- store / session -------------------------------------------------------
def test_store_session_expiry_detection():
    from butter.apple_auth.http import Response

    assert is_session_expired(401)
    assert is_session_expired(302, location="https://x/shop/accounthome/sorry?type=SESSIONEXPIRY")
    assert is_session_expired(200, body='{"head":{"status":302,"data":{"url":"...SESSIONEXPIRY"}}}')
    assert not is_session_expired(200, body="ok")


def test_find_in_dict_is_recursive():
    assert find_in_dict({"a": {"b": [{"publicKey": "k"}]}}, "publicKey") == "k"


# --- clipboard parser ------------------------------------------------------
@pytest.mark.parametrize(
    ("payload", "key", "value"),
    [
        ("姓名: Jane Doe\n电话: 2125551234\n城市: Austin", "first_name", "Jane"),
        ("First Name: Ann\nCity: Boston", "city", "Boston"),
        ("手机号13000000000 国家GB 城市London", "country_code", "GB"),
        ("first_name:\nMike\ncity:\nSeattle", "city", "Seattle"),
        ('{"personalInformation":{"firstName":"Zoe"},"city":"Dallas"}', "first_name", "Zoe"),
    ],
)
def test_parse_clipboard_formats(payload, key, value):
    assert parse_clipboard(payload).get(key) == value


def test_parse_clipboard_empty():
    assert parse_clipboard("   ") == {}


# --- proxy profile ---------------------------------------------------------
def test_build_profile_requires_upstream():
    with pytest.raises(ValueError):
        build_profile(Settings(proxy_mode="mihomo"))


def test_build_profile_single_hop_without_nodes():
    profile = build_profile(Settings(proxy_mode="mihomo", proxy_host="1.2.3.4", proxy_port=1080))
    assert [p["name"] for p in profile["proxies"]] == ["ISP"]
    assert "dialer-proxy" not in profile["proxies"][0]
    assert profile["proxy-groups"][0]["proxies"] == ["ISP"]


def test_build_profile_chains_dialer():
    settings = Settings(
        proxy_mode="mihomo",
        proxy_host="1.2.3.4",
        proxy_port=1080,
        hk_nodes=[{"server": "5.6.7.8", "port": 443, "password": "pw"}],
    )
    profile = build_profile(settings, 18000)
    assert profile["mixed-port"] == 18000
    assert profile["proxy-groups"][0]["type"] == "load-balance"
    assert profile["proxies"][-1]["dialer-proxy"] == "HK-LB"
    assert "MATCH,FINAL" in "".join(profile["rules"])
    assert "HK-LB" in render_profile(settings, 18000)


# --- misc ------------------------------------------------------------------
def test_fill_address_keeps_supplied_values():
    rng = random.Random(7)
    address = fill_address({"first_name": "Ann", "country_code": "gb"}, rng)
    assert address.first_name == "Ann"
    assert address.country_code == "GB"
    assert address.phone


def test_random_phone_per_country():
    assert random_phone("GB").startswith("07")
    assert random_phone("AU").startswith("04")


def test_is_retryable_markers():
    assert is_retryable("curl: (7) Failed to connect")
    assert not is_retryable("bad password")


def test_account_store_roundtrip(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    store.upsert(Account(email="a@b.c", password="pw", note="n1"))
    reloaded = AccountStore(tmp_path / "accounts.json")
    assert reloaded.get("A@B.C").note == "n1"
    assert reloaded.get("a@b.c").public()["password"] == "***"
    assert reloaded.remove("a@b.c") is True
    assert reloaded.accounts == []


def test_settings_proxy_url_construction(tmp_path):
    settings = Settings(proxy_mode="custom", proxy_host="h", proxy_port=1080, proxy_user="u", proxy_pass="p")
    url = settings.proxy_url_for(sid="s1", region="HK")
    assert url.startswith("socks5://u-region-HK-sid-s1-t-10:p@h:1080")
    settings.save(tmp_path / "s.json")
    assert Settings.load(tmp_path / "s.json").proxy_host == "h"


def test_pinned_fingerprint_overrides_both_fields():
    from butter.apple_auth import fingerprint as fp

    try:
        assert fp.pin_fingerprint('{"U":"UA-X","L":"zh-CN","Z":"GMT+08:00","V":"1.1","F":"Nla44j1e3NlY5B"}')
        blob = json.loads(fp.fd_client_info_matching_common_headers())
        assert blob["U"] == "UA-X"
        assert blob["F"] == "Nla44j1e3NlY5B"
        assert fp.pin_fingerprint("plainF") and fp.pinned() == "plainF"
    finally:
        fp.pin_fingerprint("")


def test_pick_port_env(monkeypatch):
    from butter.api.app import pick_port

    monkeypatch.delenv("BUTTER_PORT", raising=False)
    assert isinstance(pick_port(), int)
    monkeypatch.setenv("BUTTER_PORT", "8899")
    assert pick_port() == 8899
