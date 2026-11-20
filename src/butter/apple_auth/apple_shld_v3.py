#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple Store shld v3 工作量证明 —— 完整复刻 store 的 /shop/shld/v3/verify.js

════════ 实测协议（两步，先 GET 再 POST）════════
① GET  {store}/shop/shld/work/v3/q?jr={jr}
      Accept: /
      Referer: {store}/shop/signIn/account?ssi={ssi}
      Sec-Fetch-Site: same-origin / Mode: cors / Dest: empty
   → 200 JSON 挑战 {salt, timeout, signature, t, challenge_version, X, algorithm, challenge, number, ...}
   → 429 表示限流，body 里有 retry_count / retry_interval

② POST {store}/shop/shld/work/v3/q?jr={jr}
      Content-Type: text/plain;charset=UTF-8
      Origin / Referer 同上
   body = {
       ...原挑战字段,
       "flagskv": {"patSkip": true},
       "number": <解出的 n 或乘积因子组>,
       "took":   <耗时 ms>,
       "jsa":    {"s":30,"f":["P"],"d":{"u":"c","p":1,"r":"oxxxxxo"}}
   }
   → Set-Cookie: shld_bt_ck=...

════════ jr 的来源 ════════
第 3 步 GET /shop/signIn/account?ssi=... 的 set-cookie 里下发：
    shld_bt_m=2X03SdNLHwE_Zs4o1sD82A|1794497912|ZY0U_GXgysFppv-E2-0Y8w|r5ycr5H5...
              ^^^^^^^^^^^^^^^^^^^^^^ 第一段就是 jr
    Max-Age=7200; SameSite=Lax; Domain=apple.com
实测 jr 常见值为 30。

════════ 求解器（从 verify.js 反混淆）════════
A. SHA 型（挑战含 salt + challenge + algorithm）
   for n in 0 .. 0xF4240:
       d = SHA(choice, encode(salt + n))
       if challenge_version == 3: d = _swap(d)   # 见 _swap_challenge
       if d == challenge: 命中 → number = n

B. PoW 型（挑战含 X + number + low/high）
   回溯分解：选 k=number 个因子，乘积 == X
       backtrack(arr, prod, start):
           if len(arr) == k and prod == X: return arr
           for i in start..high:
               if i < low: continue
               if prod*i > X: continue
               if X % (prod*i) != 0 and len(arr)+1 < k: continue
               push(i); r = backtrack(...); if r: return r; pop()
"""

from __future__ import annotations

import hashlib
import json
import re
import time

# 算法名映射
_ALG = {"SHA-384": "sha384", "SHA-256": "sha256", "SHA-512": "sha512", "SHA-1": "sha1"}
MAX_N = 0xF4240  # 1000000


def _hash(algorithm: str | None, data: bytes) -> bytes:
    name = _ALG.get((algorithm or "SHA-384").upper(), "sha384")
    return hashlib.new(name, data).digest()


def _swap_tail4(digest: bytes) -> bytes:
    """challenge_version==3 时对摘要做尾部 4 字节交换"""
    if len(digest) < 4:
        return digest
    return digest[:-4] + digest[-4:][::-1]


def solve_sha(challenge: dict, deadline: float | None = None) -> dict | None:
    """
    A 型求解：对比 challenge 字段。返回 {"number": n, "took": ms}
    """
    salt = challenge.get("salt") or ""
    target = challenge.get("challenge")
    alg = challenge.get("algorithm") or "SHA-384"
    ver = challenge.get("challenge_version")
    tmo = challenge.get("timeout") or 3000
    t0 = time.time()
    deadline = t0 + (tmo / 1000.0) if deadline is None else deadline

    for n in range(MAX_N):
        if time.time() > deadline:
            return None
        d = _hash(alg, f"{salt}{n}".encode())
        if ver == 3:
            d = _swap_tail4(d)
        hx = d.hex()
        if hx == target or (target and hx.startswith(target)):
            return {"number": n, "took": int((time.time() - t0) * 1000)}
    return None


def solve_pow(challenge: dict, deadline: float | None = None) -> dict | None:
    """
    B 型求解：找 number 个因子使其乘积 == X。
    返回 {"number": [因子...], "took": ms}
    """
    low = challenge.get("low")
    high = challenge.get("high")
    x = challenge.get("X")
    k = challenge.get("number")
    tmo = challenge.get("timeout") or 3000
    t0 = time.time()
    dl = t0 + (tmo / 1000.0) if deadline is None else deadline

    if not all(v is not None for v in (low, high, x, k)):
        return None
    low, high, x, k = int(low), int(high), int(x), int(k)

    def backtrack(arr, prod, start):
        if time.time() > dl:
            return None
        if len(arr) == k:
            return list(arr) if prod == x else None
        for i in range(start, high + 1):
            if i < low:
                continue
            nxt = prod * i
            if nxt > x:
                continue
            if x % nxt != 0 and len(arr) + 1 < k:
                continue
            arr.append(i)
            r = backtrack(arr, nxt, i)
            if r:
                return r
            arr.pop()
        return None

    got = backtrack([], 1, low)
    if got is None:
        return None
    return {"number": got, "took": int((time.time() - t0) * 1000)}


def solve(challenge: dict) -> dict:
    """按挑战类型分派，返回用于 POST 的补充字段"""
    if challenge.get("challenge") and challenge.get("salt"):
        got = solve_sha(challenge)
        kind = "sha"
    elif challenge.get("X") is not None:
        got = solve_pow(challenge)
        kind = "pow"
    else:
        raise ValueError(f"未知挑战格式 | keys={list(challenge.keys())}")
    if not got:
        raise ValueError(f"{kind} 无解（超时或超出范围）")
    return {"kind": kind, **got}


# ══════════════════ HTTP 流程 ══════════════════
JSA = {"s": 30, "f": ["P"], "d": {"u": "c", "p": 1, "r": "oxxxxxo"}}


def get_jr(session=None) -> str:
    """
    实测 /shop/shld/work/v3/q 只接受 jr=30（29/31/s3/空 都 404）。
    shld_bt_m 的第一段是另一个签名值，不能当 jr 用。
    下发的值优先，便于服务端调整而不必发版。
    """
    from ..core import protocol_params

    return str(protocol_params.get("jr") or "30")


def run_shld(session, base: str, ssi: str, jr: str | None = None,
             verbose: bool = True) -> str | None:
    """
    执行 GET → 解 → POST，返回 shld_bt_ck；失败返回 None。
    session 需已带 shld_bt_m / dssid2 / as_sfa 等 store cookie。
    """
    base = base.rstrip("/")
    jr = jr or get_jr(session)
    ref = f"{base}/shop/signIn/account?ssi={ssi}"
    url = f"{base}/shop/shld/work/v3/q?jr={jr}"

    h = {
        "Accept": "/",
        "Referer": ref,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }

    # ① GET 挑战
    try:
        r = session.get(url, headers=h, timeout=20)
    except Exception as e:
        print(f"    [shld] GET 失败 {type(e).__name__}: {e}")
        return None
    if verbose:
        print(f"    [shld] GET {url} -> {r.status_code}")
    if r.status_code == 429:
        try:
            j = r.json()
            print(f"    [shld] 限流 retry={j.get('retry_count')} wait={j.get('retry_interval')}")
        except Exception:
            pass
        return None
    if r.status_code != 200:
        print(f"    [shld] GET 失败 status={r.status_code} body={r.text[:150]!r}")
        return None

    try:
        ch = r.json()
    except Exception:
        print(f"    [shld] 挑战非 JSON: {r.text[:150]!r}")
        return None
    if verbose:
        print(f"    [shld] 挑战: {json.dumps(ch, ensure_ascii=False)[:220]}")

    # ② 求解
    try:
        sol = solve(ch)
    except ValueError as e:
        print(f"    [shld] {e}")
        return None
    if verbose:
        print(f"    [shld] 解出 kind={sol['kind']} number={sol['number']} took={sol['took']}ms")

    # ③ POST 提交
    body = dict(ch)
    body["flagskv"] = {"patSkip": True, "patOkNoCk": False}
    body["number"] = sol["number"]
    body["took"] = sol["took"]
    body["jsa"] = JSA

    ph = {
        "Accept": "/",
        "Content-Type": "text/plain;charset=UTF-8",
        "Origin": base,
        "Referer": ref,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    if verbose:
        print(f"    [shld] POST body={json.dumps(body, ensure_ascii=False)[:280]}")
    try:
        r2 = session.post(url, headers=ph, data=json.dumps(body), timeout=20)
    except Exception as e:
        print(f"    [shld] POST 失败 {type(e).__name__}: {e}")
        return None

    ck = None
    sc = r2.headers.get("set-cookie") or ""
    m = re.search(r"shld_bt_ck=([^;]+)", sc)
    if m:
        ck = m.group(1)
    if not ck:
        try:
            for c in session.cookies.jar:
                if c.name == "shld_bt_ck":
                    ck = c.value
        except Exception:
            pass

    print(f"    [shld] POST -> {r2.status_code} | shld_bt_ck={'OK' if ck else 'MISS'}"
          f" | url=v3 jr={jr} number={sol['number']} took={sol['took']}ms")
    if verbose and r2.text:
        print(f"    [shld] resp: {r2.text[:200]}")
    return ck


if __name__ == "__main__":
    import hashlib as _hl
    # 自检 SHA 求解
    salt = "cdcf1294ab871034"
    n = 1099
    tgt = _hl.sha384(f"{salt}{n}".encode()).hexdigest()
    got = solve_sha({"salt": salt, "challenge": tgt, "algorithm": "SHA-384",
                     "challenge_version": 0, "timeout": 5000})
    print("SHA 自检:", got, "OK" if got and got["number"] == n else "FAIL")
    # 自检 PoW
    got2 = solve_pow({"low": 2, "high": 20, "X": 30, "number": 3, "timeout": 2000})
    print("PoW 自检:", got2, "OK" if got2 and got2["number"] == [2, 3, 5] else "?")
