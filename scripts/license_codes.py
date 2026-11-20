"""Generate activation codes locally and import them into the Worker.

Codes are random and are never derived from anything — the Worker stores them and
the signing key stays there. Duration is per code, and codes stack.

Usage:
    uv run python scripts/license_codes.py --days 7 --count 20 --plan week
    uv run python scripts/license_codes.py --push codes.json      # import

`--push` needs BUTTER_ADMIN_URL and BUTTER_ADMIN_SECRET in the environment.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import pathlib
import secrets
import time
import urllib.request

# Crockford-style alphabet: no I, L, O, U — survives being read aloud or copied.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
GROUPS = 4
GROUP_LEN = 4


def checksum(body: str) -> str:
    digest = hashlib.sha256(body.encode()).digest()
    return ALPHABET[digest[0] % len(ALPHABET)]


def make_code() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP_LEN))
    grouped = "-".join(body[i : i + GROUP_LEN] for i in range(0, len(body), GROUP_LEN))
    return f"{grouped}-{checksum(body)}"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def push(url: str, secret: str, codes: list[dict]) -> dict:
    body = json.dumps({"codes": codes}).encode()
    stamp = str(int(time.time()))
    mac = b64url(hmac.new(secret.encode(), stamp.encode() + body, hashlib.sha256).digest())
    req = urllib.request.Request(
        f"{url.rstrip('/')}/admin/codes",
        data=body,
        method="POST",
        headers={"content-type": "application/json", "x-stamp": stamp, "x-sign": mac},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="validity each code grants")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--plan", default="week")
    ap.add_argument("--out", default="codes.json")
    ap.add_argument("--push", nargs="?", const="", help="import an existing file")
    args = ap.parse_args()

    if args.push is not None:
        import os

        url = os.environ.get("BUTTER_ADMIN_URL", "")
        secret = os.environ.get("BUTTER_ADMIN_SECRET", "")
        if not url or not secret:
            raise SystemExit("需要 BUTTER_ADMIN_URL 和 BUTTER_ADMIN_SECRET")
        codes = json.loads(pathlib.Path(args.push or args.out).read_text(encoding="utf-8"))
        print(push(url, secret, codes))
        return 0

    if not args.days:
        raise SystemExit("--days required")
    batch = [{"code": make_code(), "plan": args.plan, "days": args.days} for _ in range(args.count)]
    pathlib.Path(args.out).write_text(json.dumps(batch, indent=2), encoding="utf-8")
    for row in batch:
        print(row["code"])
    print(f"\n{len(batch)} codes × {args.days}d -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
