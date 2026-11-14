"""SRP proof against a captured Apple worker oracle.

The fixture records one real ``webSRPClientWorker`` computation: fixed private
``a``, the server's salt/B, and the M1/M2 the browser produced. If our variant
(``k = H(N) XOR H(pad(g))``, unpadded ``u = H(A|B)``) drifts, these break.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from butter.apple_auth.apple_exe_replica import SRP_N, _i2b, srp_proofs

FIXTURE = Path(__file__).parent / "fixtures" / "srp_oracle.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_public_value_matches_worker():
    fx = _load()
    a_int = int.from_bytes(bytes.fromhex(fx["fixed_private_hex"]), "big")
    assert _i2b(pow(2, a_int, SRP_N)) == base64.b64decode(fx["A_b64"])


def test_proofs_match_worker_output():
    fx = _load()
    a_int = int.from_bytes(bytes.fromhex(fx["fixed_private_hex"]), "big")
    m1, m2 = srp_proofs(
        fx["account"],
        fx["password"],
        fx["salt_b64"],
        fx["iterations"],
        fx["b_b64"],
        a_int,
        fx.get("protocol", "s2k"),
    )
    assert m1 == fx["m1_b64"]
    assert m2 == fx["m2_b64"]
