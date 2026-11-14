"""Clipboard billing/address parser (7 shapes incl. JSON).

Ported from ``src/account_manager/address_parser.py``. Accepts what operators
realistically paste — Chinese labels, English labels, key/value streams,
aligned tables, nested ``key:`` blocks, the ``【卡片信息】/【个人信息】`` blocks and
raw JSON — and returns a normalised dict.
"""

from __future__ import annotations

import json
import re
from typing import Any

_CN_LABELS = {
    "姓名": "full_name",
    "姓": "last_name",
    "名": "first_name",
    "电话": "phone",
    "手机号": "phone",
    "手机": "phone",
    "地址": "street",
    "地址1": "street",
    "地址2": "street2",
    "街道": "street",
    "公寓": "street2",
    "城市": "city",
    "州": "state",
    "州/省": "state",
    "州/省/地区": "state",
    "省": "state",
    "邮编": "postal_code",
    "邮政编码": "postal_code",
    "国家": "country_code",
    "卡号": "card_number",
    "有效期": "card_expiry",
    "过期日": "card_expiry",
    "日期": "card_expiry",
    "到期日期": "card_expiry",
    "卡名": "card_holder",
    "持卡人": "card_holder",
    "性别": "gender",
    "生日": "birthday",
    "邮箱": "email",
    "邮箱密码": "email_password",
}

_EN_LABEL_MAP = {
    "first name": "first_name",
    "firstname": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "name": "full_name",
    "phone": "phone",
    "phone number": "phone",
    "telephone": "phone",
    "address": "street",
    "address line 1": "street",
    "address line 2": "street2",
    "street": "street",
    "city": "city",
    "town": "city",
    "state": "state",
    "province": "state",
    "zip": "postal_code",
    "zip code": "postal_code",
    "postal code": "postal_code",
    "postcode": "postal_code",
    "country": "country_code",
    "card number": "card_number",
    "card": "card_number",
    "expiry": "card_expiry",
    "expiration": "card_expiry",
    "exp": "card_expiry",
}

_F2_KEY_MAP = {
    "手机号": "phone",
    "手机": "phone",
    "电话": "phone",
    "国家": "country_code",
    "地址": "street",
    "城市": "city",
    "邮编": "postal_code",
}

_F4_KEY_MAP = {**_CN_LABELS, **_F2_KEY_MAP}

_F5_KEY_MAP = {
    "first_name": "first_name",
    "last_name": "last_name",
    "name": "full_name",
    "phone": "phone",
    "street": "street",
    "street2": "street2",
    "line1": "street",
    "line2": "street2",
    "city": "city",
    "state": "state",
    "postal_code": "postal_code",
    "country_code": "country_code",
    "card_number": "card_number",
    "expiry": "card_expiry",
    "email": "email",
}

_F5_LINE_RE = re.compile(r"^([a-z][a-z_0-9]*)\s*:$")
_KEY_ONLY_RE = re.compile(r"^(.+?)\s*:\s*$")
_KEY_RE = re.compile(r"^([a-z][a-z_0-9]*)\s*:\s*(.+)$", re.IGNORECASE)

_F6_DETECT = re.compile(r"【(?:卡片信息|个人信息)】|\[(?:card|personal)", re.IGNORECASE)
_F6_LABELS = ("【卡片信息】", "【个人信息】", "[card]", "[personal]", "card info", "personal info")

_FULL_ADDR_RE = re.compile(r"^(.+?),\s*.+,\s*\w[\w ]*\s+\d{5}(?:-\d{4})?$")
_APT_RE = re.compile(r",?\s*((?:Apt|Suite|Ste|Unit|#)\s*[\w-]+)\s*$", re.IGNORECASE)

_JSON_ALIASES = {
    "firstname": "first_name",
    "first_name": "first_name",
    "lastname": "last_name",
    "last_name": "last_name",
    "phone": "phone",
    "address": "street",
    "addressline1": "street",
    "line1": "street",
    "street": "street",
    "addressline2": "street2",
    "line2": "street2",
    "street2": "street2",
    "city": "city",
    "state": "state",
    "zipcode": "postal_code",
    "zip": "postal_code",
    "postalcode": "postal_code",
    "countrycode": "country_code",
    "country": "country_code",
    "cardnumber": "card_number",
    "card_number": "card_number",
    "expirydate": "card_expiry",
    "expiry": "card_expiry",
    "expiration": "card_expiry",
    "email": "email",
}

_RESULT_KEYS = (
    "first_name",
    "last_name",
    "full_name",
    "phone",
    "street",
    "street2",
    "city",
    "state",
    "postal_code",
    "country_code",
    "card_number",
    "card_expiry",
    "card_holder",
    "email",
)


def _clean(value: str) -> str:
    return value.strip().strip("：:").strip()


def _split_name(result: dict[str, str], full_name: str) -> None:
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if not parts:
        return
    if len(parts) == 1:
        result.setdefault("first_name", parts[0])
    else:
        result.setdefault("first_name", parts[0])
        result.setdefault("last_name", " ".join(parts[1:]))


def _lookup_key(key: str) -> str | None:
    probe = key.strip()
    lowered = probe.lower().replace("_", " ").replace("-", " ")
    collapsed = re.sub(r"\s+", " ", lowered).strip()
    if probe in _F4_KEY_MAP:
        return _F4_KEY_MAP[probe]
    if collapsed in _EN_LABEL_MAP:
        return _EN_LABEL_MAP[collapsed]
    if lowered in _F5_KEY_MAP:
        return _F5_KEY_MAP[lowered]
    if "_" in probe and probe.lower() in _F5_KEY_MAP:
        return _F5_KEY_MAP[probe.lower()]
    return None


def _apply_field(result: dict[str, str], key: str, value: str) -> None:
    value = _clean(value)
    if not value or value in {"—", "-", "..."}:
        return
    target = _lookup_key(key)
    if not target:
        return
    if target == "full_name":
        _split_name(result, value)
        return
    if target == "country_code":
        value = value.upper()
    result.setdefault(target, value)


def _extract_street_only(addr: str) -> tuple[str, str]:
    m = _APT_RE.search(addr)
    if m:
        return addr[: m.start()].rstrip(", ").strip(), m.group(1).strip()
    return addr.strip(), ""


def _parse_aligned(lines: list[str], result: dict[str, str]) -> bool:
    keys = [_F4_KEY_MAP[k] for k in _F4_KEY_MAP]
    for line in lines:
        cells = [c for c in re.split(r"[ \t]{2,}|\t", line.strip()) if c.strip()]
        if len(cells) < 2:
            continue
        matched = 0
        for cell, value in zip(cells, cells[1:], strict=False):
            key = cell.strip().rstrip(":：")
            if key in _F4_KEY_MAP:
                _apply_field(result, key, value)
                matched += 1
        if matched:
            continue
        if len(cells) >= 2 and any(k in line for k in keys[:3]):
            continue
    return bool(result)


def _parse_kv_stream(lines: list[str], result: dict[str, str]) -> bool:
    """Format 2/2b: ``手机号…国家…地址…城市…邮编`` on one or many lines."""
    joined = " ".join(line.strip() for line in lines if line.strip())
    keys = sorted(_F2_KEY_MAP, key=len, reverse=True)
    hits = []
    for key in keys:
        for match in re.finditer(re.escape(key), joined):
            hits.append((match.start(), match.end(), key))
    hits.sort()
    if len(hits) < 2:
        return False
    for index, (_, end, key) in enumerate(hits):
        stop = hits[index + 1][0] if index + 1 < len(hits) else len(joined)
        _apply_field(result, key, joined[end:stop])
    return bool(result)


def _parse_nested(lines: list[str], result: dict[str, str]) -> bool:
    """Format 5: ``key:`` on its own line followed by its value."""
    pending: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _KEY_ONLY_RE.match(stripped):
            pending = _KEY_ONLY_RE.match(stripped).group(1)
            continue
        if _F5_LINE_RE.match(stripped):
            pending = _F5_LINE_RE.match(stripped).group(1)
            continue
        if pending:
            _apply_field(result, pending, stripped)
            pending = None
    return bool(result)


def _parse_colon_lines(lines: list[str], result: dict[str, str]) -> bool:
    for line in lines:
        stripped = line.strip()
        if stripped.count(":") + stripped.count("：") != 1:
            continue
        key, value = re.split(r"[:：]", stripped, maxsplit=1)
        _apply_field(result, key.strip(), value)
    return bool(result)


def _billing_dict_from_json(data: Any) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                target = _JSON_ALIASES.get(str(key).replace(" ", "").lower())
                if target and isinstance(value, (str, int, float)):
                    out.setdefault(target, str(value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return {k: v for k, v in out.items() if k in _RESULT_KEYS and v}


def _finish(result: dict[str, str]) -> dict[str, str]:
    street = result.get("street")
    if street and "street2" not in result:
        main, apt = _extract_street_only(street)
        if apt:
            result["street"] = main
            result["street2"] = apt
    if result.get("full_name") and "first_name" not in result:
        _split_name(result, result["full_name"])
    return {k: v for k, v in result.items() if k in _RESULT_KEYS and v}


def parse_clipboard(text: str) -> dict[str, str]:
    payload = (text or "").strip()
    if not payload:
        return {}

    for opening, closing in (("{", "}"), ("[", "]")):
        start = payload.find(opening)
        end = payload.rfind(closing)
        if start != -1 and end > start:
            try:
                return _billing_dict_from_json(json.loads(payload[start : end + 1]))
            except json.JSONDecodeError:
                pass

    lines = [line for line in payload.splitlines() if line.strip()]
    result: dict[str, str] = {}

    if _F6_DETECT.search(payload):
        _parse_colon_lines(lines, result)
        return _finish(result)

    _parse_colon_lines(lines, result)
    if result:
        return _finish(result)

    if _parse_nested(lines, result):
        return _finish(result)
    if _parse_aligned(lines, result):
        return _finish(result)
    if _parse_kv_stream(lines, result):
        return _finish(result)
    return {}
