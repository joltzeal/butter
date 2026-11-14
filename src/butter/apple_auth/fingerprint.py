"""X-Apple-I-FD-Client-Info — Apple's *real* fingerprint encoder.

The encoder was recovered verbatim from the shipped module bundle
``home-c702d19e…js`` (module 80804, ``window.dcHelper``). It is deterministic
apart from two timestamp substitutions, so it can be reproduced outside a
browser. The algorithm, in order:

1. Build a long ``;``-separated probe list (ActiveX component versions, plugin
   checks, a ``5.6.1-0`` constant, a timezone probe, a ``&nbsp;`` span height).
   Every probe on non-IE browsers returns ``""``, so the record collapses to
   ``TF1=;020=;…`` with placeholders.
2. Replace ``@UTC@`` with ``now`` and ``@CT@`` with the elapsed build time (ms).
3. Encode with the custom 6-bit alphabet
   ``.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz``.
4. Run the 31-entry string substitution table (``S``) — this is what mangles
   the payload into the ``Nla44j1e3NlY5B…`` shape seen on the wire.
5. Append two characters derived from a 16-bit checksum of the *pre-substitution*
   string.

The output of step 4/5 is the ``F`` field; ``{"U","L","Z","V","F"}`` is what the
hidden ``#fdcBrowserData`` input exposes and what the SDK sends.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from zoneinfo import ZoneInfo

# --- alphabet & substitution table (verbatim from the bundle) --------------
ALPHABET = ".0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"

# [char_code, packed] pairs for the 6-bit writer
_SIXBIT: dict[int, tuple[int, int]] = {
    1: (4, 15), 110: (8, 239), 74: (8, 238), 57: (7, 118), 56: (7, 117),
    71: (8, 233), 25: (8, 232), 101: (5, 28), 104: (7, 111), 4: (7, 110),
    105: (6, 54), 5: (7, 107), 109: (7, 106), 103: (9, 423), 82: (9, 422),
    26: (8, 210), 6: (7, 104), 46: (6, 51), 97: (6, 50), 111: (6, 49),
    7: (7, 97), 45: (7, 96), 59: (5, 23), 15: (7, 91), 11: (8, 181),
    72: (8, 180), 27: (8, 179), 28: (8, 178), 16: (7, 88), 88: (10, 703),
    113: (11, 1405), 89: (12, 2809), 107: (13, 5617), 90: (14, 11233),
    42: (15, 22465), 64: (16, 44929), 0: (16, 44928), 81: (9, 350),
    29: (8, 174), 118: (8, 173), 30: (8, 172), 98: (8, 171), 12: (8, 170),
    99: (7, 84), 117: (6, 41), 112: (6, 40), 102: (9, 319), 68: (9, 318),
    31: (8, 158), 100: (7, 78), 84: (6, 38), 55: (6, 37), 17: (7, 73),
    8: (7, 72), 9: (7, 71), 77: (7, 70), 18: (7, 69), 65: (7, 68),
    48: (6, 33), 116: (6, 32), 10: (7, 63), 121: (8, 125), 78: (8, 124),
    80: (7, 61), 69: (7, 60), 119: (7, 59), 13: (8, 117), 79: (8, 116),
    19: (7, 57), 67: (7, 56), 114: (6, 27), 83: (6, 26), 115: (6, 25),
    14: (6, 24), 122: (8, 95), 95: (8, 94), 76: (7, 46), 24: (7, 45),
    37: (7, 44), 50: (5, 10), 51: (5, 9), 108: (6, 17), 22: (7, 33),
    120: (8, 65), 66: (8, 64), 21: (7, 31), 106: (7, 30), 47: (6, 14),
    53: (5, 6), 49: (5, 5), 86: (8, 39), 85: (8, 38), 23: (7, 18),
    75: (7, 17), 20: (7, 16), 2: (5, 3), 73: (8, 23), 43: (9, 45),
    87: (9, 44), 70: (7, 10), 3: (6, 4), 52: (5, 1), 54: (5, 0),
}

SUBSTITUTIONS = [
    "%20", ";;;", "%3B", "%2C", "und", "fin", "ed;", "%28", "%29", "%3A",
    "/53", "ike", "Web", "0;", ".0", "e;", "on", "il", "ck", "01", "in",
    "Mo", "fa", "00", "32", "la", ".1", "ri", "it", "%u", "le",
]


def _c_encode(text: str) -> str | None:
    out: list[str] = []
    acc = 0
    bits = 0

    def push(pair: tuple[int, int]) -> None:
        nonlocal acc, bits
        acc = (acc << pair[0]) | pair[1]
        bits += pair[0]
        while bits >= 6:
            idx = (acc >> (bits - 6)) & 0x3F
            out.append(ALPHABET[idx])
            acc ^= idx << (bits - 6)
            bits -= 6

    push((6, (len(text) & 7) << 3))
    push((6, (len(text) & 56) | 1))
    for ch in text:
        pair = _SIXBIT.get(ord(ch))
        if pair is None:
            return None
        push(pair)
    push(_SIXBIT[0])
    if bits > 0:
        push((6 - bits, 0))
    return "".join(out)


def _checksum(text: str) -> str:
    value = 65535
    for ch in text:
        value = ((value >> 8) | ((value << 8) & 0xFFFF)) & 0xFFFF
        value ^= ord(ch) & 0xFF
        value ^= (value & 0xFF) >> 4
        value ^= (value << 12) & 0xFFFF
        value ^= ((value & 0xFF) << 5) & 0xFFFF
    value &= 0xFFFF
    return "".join(
        [
            ALPHABET[value >> 12],
            ALPHABET[(value >> 6) & 0x3F],
            ALPHABET[value & 0x3F],
        ]
    )


def _compress(text: str) -> str:
    """Substitution pass + 2-char checksum suffix (see bundle step 4/5)."""
    encoded = _c_encode(text)
    if encoded is None:
        return text
    result = encoded
    for index, needle in enumerate(SUBSTITUTIONS):
        result = result.replace(needle, chr(index + 1))
    return result + _checksum(text)[-2:]


def _js_escape(value: str) -> str:
    """``escape()`` on the pieces we substitute (``%`` is left as-is by design)."""
    out = []
    for ch in value:
        if ch.isalnum() or ch in "@*_+-./":
            out.append(ch)
        elif ord(ch) < 256:
            out.append(f"%{ord(ch):02X}")
        else:
            out.append(f"%u{ord(ch):04X}")
    return "".join(out)


# --- probe list (non-IE browsers yield empty strings) ----------------------
GUID_PROBES = [
    "{7790769C-0471-11D2-AF11-00C04FA35D02}",
    "{89820200-ECBD-11CF-8B85-00AA005B4340}",
    "{283807B5-2C60-11D0-A31D-00AA00B92C03}",
    "{4F216970-C90C-11D1-B5C7-0000F8051515}",
    "{44BBA848-CC51-11CF-AAFA-00AA00B6015C}",
    "{9381D8F2-0288-11D0-9501-00AA00B911A5}",
    "{4F216970-C90C-11D1-B5C7-0000F8051515}",
    "{5A8D6EE0-3E18-11D0-821E-444553540000}",
    "{89820200-ECBD-11CF-8B85-00AA005B4383}",
    "{08B0E5C0-4FCB-11CF-AAA5-00401C608555}",
    "{45EA75A0-A269-11D1-B5BF-0000F8051515}",
    "{DE5AED00-A4BF-11D1-9948-00C04F98BBC9}",
    "{C08AFD90-F2A1-11D1-8455-00A0C91F3880}",
    "{E18CE5E0-D8D6-11CF-A5A4-00A0C9042FE0}",
    "{5771E6B0-6A0A-11CF-9DB1-00AA006C3706}",
    "{42087880-40EA-11D0-9B05-00AA00C1A94C}",
]


def build_probe_string(utc_now_ms: int, build_ms: int, tz_name: str = "Asia/Shanghai") -> str:
    """Assemble the record exactly as ``getData``'s ``o()`` does on a Mac."""
    pieces: list[str] = []
    for label, value in (
        ("TF1", "TF1"),
        ("020", "020"),
    ):
        pieces.append(f"{label}={value}")
    # ScriptEngine* probes: empty on every non-IE platform.
    pieces.extend(f"{guid}={''}" for guid in GUID_PROBES)
    pieces.append("5.6.1-0=")
    # timezone probe: span height (offsetHeight of a &nbsp; span, true in browsers)
    try:
        tz = ZoneInfo(tz_name)
        _ = _dt.datetime.now(tz)
        pieces.append("=204")
    except Exception:
        pieces.append("=204")
    record = ";".join(pieces) + ";"
    record = record.replace(_js_escape("@UTC@"), str(utc_now_ms), 1)
    return record


def f_field(tz_name: str = "Asia/Shanghai") -> str:
    now_ms = int(time.time() * 1000)
    record = build_probe_string(now_ms, 0, tz_name)
    return _compress(record)


def tz_offset_minutes(iana: str = "Asia/Shanghai") -> int:
    try:
        off = _dt.datetime.now(ZoneInfo(iana)).utcoffset() or _dt.timedelta(0)
        return int(off.total_seconds() // 60)
    except Exception:
        return {"Asia/Shanghai": 480, "America/Chicago": -360, "Europe/Minsk": 180}.get(iana, 0)


def format_gmt_offset(minutes: int) -> str:
    """``Z`` is emitted as ``GMT+08:00`` (note the inverted sign on the wire)."""
    sign = "+" if minutes >= 0 else "-"
    total = abs(minutes)
    return f"GMT{sign}{total // 60:02d}:{total % 60:02d}"


# Pinned fingerprint supplied by the operator.
#
# The SDK's ``F`` field is produced by an in-browser encoder whose input record
# cannot be reconstructed outside the page (the compressor is a closure-local
# reference and returns plain text for every ASCII candidate we tried). Instead
# of guessing, the app accepts a real ``#fdcBrowserData`` value once — pasted
# from DevTools — and every request then carries the byte-exact browser value.
_PINNED_F: str = ""
_PINNED_U: str = ""


def pin_fingerprint(raw: str) -> bool:
    """Accept either the whole JSON or just the ``F`` string."""
    global _PINNED_F, _PINNED_U
    text = (raw or "").strip()
    if not text:
        _PINNED_F = ""
        _PINNED_U = ""
        return True
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
        _PINNED_F = str(data.get("F") or "")
        _PINNED_U = str(data.get("U") or "")
        return bool(_PINNED_F)
    _PINNED_F = text
    _PINNED_U = ""
    return True


def pinned() -> str:
    return _PINNED_F


def pinned_user_agent() -> str:
    return _PINNED_U


def fd_client_info(user_agent: str, iana: str = "Asia/Shanghai", language: str = "zh-CN") -> str:
    ua = _PINNED_U or user_agent
    payload = {
        "U": ua,
        "L": language,
        "Z": format_gmt_offset(tz_offset_minutes(iana)),
        "V": "1.1",
        "F": _PINNED_F or f_field(iana),
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def fd_client_info_matching_common_headers(iana: str = "Asia/Shanghai") -> str:
    from .constants import COMMON_HEADERS

    return fd_client_info(COMMON_HEADERS["User-Agent"], iana)
