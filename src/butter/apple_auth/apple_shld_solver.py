#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple Store shld 工作量证明求解器 —— 复现 src/apple_auth/shld_solver.py

来源: 烽火账单辅助工具.exe 内嵌 Nuitka 载荷（payload.bin 偏差 0x14da32f-0x14da94b）
      模块名 src.apple_auth.shld_solver，导出于 src/account_manager/login_worker.py
      的 LoginWorker._do_shld()

════════ 流程（对应你给的参考）════════
GET {store}/shop/shld/work/s3/q
    Accept: */*   Sec-Fetch-Site: same-origin
    Sec-Fetch-Mode: cors   Sec-Fetch-Dest: empty
    Referer: {store}/shop/signIn/account?ssi={ssi}
  └─ 失败 → "[LoginWorker] shld GET " + " 失败 | status url body"

解析返回 JSON，二选一：
  {"challenge","number","parts"}           → solve_pow_timed(low, high, parts)
  {"challenge","salt","algorithm","number"} → solve_sha_pow_timed(...)

求解：
  solve_pow(low, high, parts) → 回溯搜索 parts 的位序组合
  solve_sha_pow(salt, challenge, algorithm, challenge_version, max_n) → SHA-384 哈希碰撞

POST {store}/shop/shld/work/s3/q
    Content-Type: application/json
    Origin: {store}
    body: {challenge, number, took}
  → Set-Cookie: shld_bt_ck=...

日志: "[LoginWorker] shld -> ok | shld_bt_ck=… | url=s3 jr=… number=… took=…ms"

════════ 二进制证据 ════════
0x14da539  uSHA-384                        ← 默认算法
0x14da57b  a_swap_tail4                    ← digest 尾部 4 字节交换
0x14da5a0  ahash_challenge                 ← hash_challenge(algorithm, salt, number, version)
0x14da5f8  a_swap_tail4 → .hex()
0x14da60e  asolve_sha_pow
0x14da7ca  ppputuple[list[int] | None, int]  ← solve_pow 返回 (parts|None, n)
0x14da8cb  amax_n
0x14da8e6  putuple[int, int]               ← timed 版本附带 (number, took)
"""

from __future__ import annotations

import hashlib
import itertools
import time
import json
import re
from typing import Iterable

DEFAULT_ALGORITHM = "SHA-384"

# 各算法名 -> hashlib 名
_ALG = {
    "SHA-384": "sha384", "SHA384": "sha384", "sha384": "sha384",
    "SHA-256": "sha256", "SHA256": "sha256", "sha256": "sha256",
    "SHA-512": "sha512", "SHA512": "sha512", "sha512": "sha512",
    "SHA-1": "sha1", "SHA1": "sha1", "sha1": "sha1",
}


def _alg_name(name: str | None) -> str:
    if not name:
        return "sha384"
    return _ALG.get(name, _ALG.get(name.upper(), "sha384"))


# ══════════════════════════════════════════════════════════
# 基础原语（对应 0x14da510 起）
# ══════════════════════════════════════════════════════════

def _hash_digest(algorithm: str | None, data: bytes) -> bytes:
    """0x14da510 a_hash_digest: hashlib.new(algorithm.replace('-','').lower(), data).digest()"""
    return hashlib.new(_alg_name(algorithm), data).digest()


def _swap_tail4(digest: bytes) -> bytes:
    """
    0x14da57b a_swap_tail4：把 digest 末尾 4 字节整体反转。

    二进制里紧接着是 `.hex()`，说明返回的仍是 bytes。
    结构: digest[:-4] + digest[-4:][::-1]
    """
    if len(digest) < 4:
        return digest
    return digest[:-4] + digest[-4:][::-1]


def hash_challenge(algorithm: str | None, salt: str, number: int,
                   challenge_version: str | None = None) -> str:
    """
    0x14da5a0 ahash_challenge(algorithm, salt, number, challenge_version)

    拼接: f"{salt}:{number}:{challenge_version}"（version 为空时省略该段）
    取摘要 → swap_tail4 → hex
    """
    parts = [salt, str(number)]
    if challenge_version:
        parts.append(str(challenge_version))
    raw = ":".join(parts).encode("utf-8")
    return _swap_tail4(_hash_digest(algorithm, raw)).hex()


# ══════════════════════════════════════════════════════════
# 求解器一：位序回溯（对应 solve_pow / solve_pow_timed）
# ══════════════════════════════════════════════════════════

def solve_pow(low: int, high: int, parts: list[int]) -> tuple[list[int] | None, int]:
    """
    0x14da7ca ppputuple[list[int] | None, int]
    对 parts 做位序组合回溯，命中区间 [low, high] 即返回 (排列, 数值)。

    二进制里的回溯骨架（0x14da3e0 起）:
        backtrack(arr, product, start):
            if low <= product <= high:  return arr
            for i in range(start, len(parts)):
                r = backtrack(arr + [parts[i]], product * parts[i], i + 1)
                if r: return r
    """
    result: list[int] = []

    def backtrack(arr: list[int], product: int, start: int):
        if low <= product <= high:
            return list(arr)
        for i in range(start, len(parts)):
            node = arr + [parts[i]]
            got = backtrack(node, product * parts[i], i + 1)
            if got is not None:
                return got
        return None

    found = backtrack(result, 1, 0)
    if not found:
        return None, 0
    product = 1
    for x in found:
        product *= x
    return found, product


def solve_pow_timed(low: int, high: int, parts: list[int]) -> tuple[list[int] | None, int, int]:
    """0x14da7eb：带 perf_counter 计时，返回 (排列, 数值, took_ms)"""
    t0 = time.perf_counter()
    arr, num = solve_pow(low, high, parts)
    return arr, num, int((time.perf_counter() - t0) * 1000)


# ══════════════════════════════════════════════════════════
# 求解器二：SHA 碰撞（对应 solve_sha_pow / solve_sha_pow_timed）
# ══════════════════════════════════════════════════════════

def solve_sha_pow(salt: str, challenge: str, algorithm: str | None,
                  challenge_version: str | None, max_n: int) -> tuple[int, int] | None:
    """
    0x14da60e asolve_sha_pow → 返回 (number, took) 由 timed 包装

    对 n = 0..max_n:
        hash_challenge(algorithm, salt, n, challenge_version)
    与 challenge 比对（challenge 为十六进制串）。
    命中即返回 (n, 0)。

    digest = swap_tail4(hash_challenge(...))，即对摘要做尾部 4 字节交换后再比。
    """
    target = (challenge or "").strip().lower()
    target = target[2:] if target.startswith("0x") else target
    for n in range(max_n):
        h = hash_challenge(algorithm, salt, n, challenge_version).lower()
        if h == target:
            return n, 0
        # 前缀匹配（部分实现是 startsWith）
        if len(h) >= len(target) and h.startswith(target):
            return n, 0
    return None


def solve_sha_pow_timed(salt: str, challenge: str, algorithm: str | None = None,
                        challenge_version: str | None = None, max_n: int = 1_000_000,
                        timeout: float | None = None) -> dict | None:
    """0x14da936：带计时与超时，返回 {number, took}"""
    t0 = time.perf_counter()
    for n in range(max_n):
        if timeout and (time.perf_counter() - t0) > timeout:
            return None
        h = hash_challenge(algorithm, salt, n, challenge_version).lower()
        tgt = (challenge or "").strip().lower()
        if h == tgt or (len(h) >= len(tgt) and h.startswith(tgt)):
            return {"number": n, "took": int((time.perf_counter() - t0) * 1000)}
    return None


# ══════════════════════════════════════════════════════════
# 挑战解析（对应 login_worker 的分派）
# ══════════════════════════════════════════════════════════

def solve_challenge(jsa: dict) -> dict:
    """
    按 login_worker._do_shld 的分派规则解挑战。

    格式 A（位序）:  {"challenge","number","parts"}
    格式 B（SHA）:   {"challenge","salt","algorithm","number"}  (+ flags/kv)
    未知格式 → 抛 ValueError("安全验证失败（未知挑战）")
    无解     → 抛 ValueError("安全验证失败（PoW 无解）")
    """
    if not isinstance(jsa, dict):
        raise ValueError("安全验证失败（未知挑战）")

    challenge = jsa.get("challenge")

    # ---- 格式 A: parts 位序 ----
    if "parts" in jsa:
        low = jsa.get("low")
        high = jsa.get("high")
        if low is None or high is None:
            num = jsa.get("number")
            if isinstance(num, int):
                low = high = num
            else:
                raise ValueError("安全验证失败（未知挑战）")
        arr, number, took = solve_pow_timed(int(low), int(high), list(jsa["parts"]))
        if arr is None:
            raise ValueError("安全验证失败（PoW 无解）")
        return {"number": number, "took": took, "challenge": challenge, "mode": "pow"}

    # ---- 格式 B: SHA ----
    if "salt" in jsa:
        max_n = int(jsa.get("number") or jsa.get("max_n") or 1_000_000)
        alg = jsa.get("algorithm") or DEFAULT_ALGORITHM
        ver = jsa.get("challenge_version") or jsa.get("challengeVersion")
        flags = jsa.get("flags") or jsa.get("kv") or {}
        tmo = flags.get("timeout") or flags.get("chCTo")
        got = solve_sha_pow_timed(
            salt=str(jsa["salt"]), challenge=str(challenge or ""),
            algorithm=alg, challenge_version=ver, max_n=max_n,
            timeout=float(tmo) if tmo else None,
        )
        if not got:
            raise ValueError("安全验证失败（PoW 无解）")
        return {"number": got["number"], "took": got["took"],
                "challenge": challenge, "mode": "sha"}

    raise ValueError("安全验证失败（未知挑战）")


# ══════════════════════════════════════════════════════════
# 自检
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("== swap_tail4 自检 ==")
    d = bytes.fromhex("0011223344556677")
    print(" in :", d.hex())
    print(" out:", _swap_tail4(d).hex(), "  （末 4 字节 44556677 -> 77665544）")

    print("\n== hash_challenge 自检 ==")
    for n in (0, 1, 42):
        print(f"  n={n:3d} -> {hash_challenge('SHA-384','abc123',n)}")

    print("\n== solve_pow 自检 ==")
    parts = [2, 3, 5, 7, 11]
    arr, num, took = solve_pow_timed(30, 60, parts)
    print(f"  parts={parts} 查找 [30,60] -> {arr} num={num} took={took}ms")

    print("\n== solve_sha_pow 自检（自造目标）==")
    salt, ver = "saltvalue", "v1"
    target_n = 137
    tgt = hash_challenge("SHA-384", salt, target_n, ver)
    print(f"  目标 hash（n={target_n}）= {tgt[:32]}…")
    got = solve_sha_pow_timed(salt, tgt, "SHA-384", ver, max_n=10000)
    print("  求解结果:", got, "→", "OK" if got and got["number"] == target_n else "FAIL")
