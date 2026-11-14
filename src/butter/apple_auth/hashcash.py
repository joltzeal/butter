"""Apple's SHLD / hashcash proof-of-work.

Recovered from ``generateHashcash.js`` (the bundle the sign-in page loads):

    generateStamp(challenge, bits, opts)
      stamp = "1:" + bits + ":" + YYYYMMDDHHMMSS(UTC) + ":" + challenge
      loop n = 0, 1, 2, …
        candidate = stamp + ":" + n
        accept when SHA1(candidate).hex().startsWith("0" * bits)

Two details differ from the usual hashcash write-ups and both matter:

* it is **SHA-1**, not SHA-256/SHA-384;
* ``hcBits`` counts **binary** leading zero bits, measured through Apple's own
  ``countLeadingZerosToStrength`` (it reads the digest bytes and sums the zero
  bits of each leading byte). A captured ``1:10:…::1108`` header hashes to
  ``002bbae1…``, i.e. 2 + 6 = 8… which the helper rounds up via its byte table,
  so we count real binary zeros and compare against ``bits`` directly.

The header Apple sends is ``X-Apple-HC: 1:<bits>:<stamp>:<email>:<n>`` — the
email slot is empty in the captured traffic (``…:7ee8…::1108``), so we emit an
empty slot too.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

MAX_NONCE = 5_000_000


def _stamp(challenge: str, bits: int, when: datetime | None = None) -> str:
    """``1:<bits>:<stamp>:<challenge>`` — everything before the nonce."""
    moment = when or datetime.now(UTC)
    # JS: (new Date).toISOString().slice(0,19).replace(/[-:T]/g,"")
    stamp = moment.strftime("%Y%m%d%H%M%S")
    return f"1:{bits}:{stamp}:{challenge}"


def _candidate(base: str, nonce: int) -> str:
    """The exact string Apple hashes: two separators before the nonce.

    The stamp already ends with the challenge, so ``base + "::" + n`` yields
    ``1:10:<ts>:<challenge>::<n>`` — matching ``…:7ee8…::1108`` on the wire.
    """
    return f"{base}::{nonce}"


def leading_zero_bits(digest: bytes) -> int:
    """Binary leading zeros, failing fast on the first set bit."""
    total = 0
    for byte in digest:
        if byte == 0:
            total += 8
            continue
        total += 8 - byte.bit_length()
        break
    return total


def solve(challenge: str, bits: int, max_n: int = MAX_NONCE, when: datetime | None = None) -> tuple[int, int]:
    """Return ``(nonce, took_ms)``; ``nonce`` is -1 when the budget runs out."""
    if not challenge or bits <= 0:
        return -1, 0
    base = _stamp(challenge, bits, when)
    started = time.perf_counter()
    for nonce in range(max_n + 1):
        if leading_zero_bits(hashlib.sha1(_candidate(base, nonce).encode()).digest()) >= bits:
            return nonce, int((time.perf_counter() - started) * 1000)
    return -1, int((time.perf_counter() - started) * 1000)


def header_value(challenge: str, bits: int, nonce: int, when: datetime | None = None) -> str:
    """The ``X-Apple-HC`` value with the empty email slot Apple expects."""
    return _candidate(_stamp(challenge, bits, when), nonce)


def solve_header(challenge: str, bits: int, max_n: int = MAX_NONCE) -> str:
    nonce, _ = solve(challenge, bits, max_n)
    if nonce < 0:
        return ""
    return header_value(challenge, bits, nonce)


def verify(candidate: str, bits: int) -> bool:
    return leading_zero_bits(hashlib.sha1(candidate.encode()).digest()) >= bits


# --- back-compat shims -----------------------------------------------------
def solve_sha_pow(salt: str, challenge_version: int, max_n: int, challenge: str, prefix: int = 0):
    """Old call shape kept for existing callers: ``salt`` is now unused."""
    return solve(challenge, prefix or 1, max_n)


def solve_pow(prefix: int, challenge: str, max_n: int = MAX_NONCE):
    return solve(challenge, prefix, max_n)


def solve_challenge(challenge: str, bits: int, max_n: int = MAX_NONCE):
    return solve(challenge, bits, max_n)
