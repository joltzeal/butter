"""Issue an offline licence for one machine.

Stand-in for the activation server: same payload shape and signature, so the
app's verification path is exercised end to end without any network.

Usage:
    uv run python scripts/license_issue.py --machine 0123abcd4567ef89 --days 7
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import time

from cryptography.hazmat.primitives import serialization

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY = ROOT / "scripts" / "license_key.pem"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", required=True, help="16-hex machine fingerprint")
    ap.add_argument("--days", type=int, default=7, help="validity, counted from now")
    ap.add_argument("--plan", default="week")
    ap.add_argument("--code", default="LOCAL-TEST")
    ap.add_argument("--out", default="license.json")
    args = ap.parse_args()

    key = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    now = int(time.time())
    payload = {
        "code": args.code,
        "machine": args.machine,
        "plan": args.plan,
        "iat": now,
        "exp": now + args.days * 86_400,
        "jti": b64(bytes(range(9))),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = key.sign(raw)

    licence = {"payload": b64(raw), "sig": b64(sig), "checked": now}
    pathlib.Path(args.out).write_text(json.dumps(licence, indent=2), encoding="utf-8")
    print(f"{args.out}: machine={args.machine} exp=+{args.days}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
