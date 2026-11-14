#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-APPLE-HC（hashcash）stamp 生成 —— 纯 Python 复现

来源: appleid.cdn-apple.com/appleauth/static/jsj/24891381/generateHashcash.js
      bootData.generateHashcashScriptTag 指定加载；bootData.hashcash 提供参数：
        { hashcashGenerationTimeout, hcChallenge, hcBits, isHCstrictTimeout }

算法:
    stamp_base = "1" + ":" + hcBits + ":" + UTC时间(YYYYMMDDHHMMSS) + ":" + hcChallenge
    逐次尝试 nonce = 0,1,2,…
        candidate = stamp_base + ":" + nonce          ← 注意这里只有一个 ':'
        SHA1(candidate) 的**前导零比特数** >= hcBits 即命中

    实测样本 1:12:20261112133857:cb829e8f304052191bd2346f36ab5130::4395
        SHA1 前导零 = 12 bit ✅ 与 hcBits 一致

关键点（和直觉不同的地方）:
  - 用的是 SHA-1，不是 SHA-256
  - 判据是「前导零 **bit** 数」，不是十六进制字符 '0' 前缀
      JS 里 isStrengthSatisfied 先 atob 再逐字节数前导零位
  - 计数器直接以十进制拼在末尾，:分隔符只在 base 与计数器之间出现一次
  - 时间戳取 UTC，格式 YYYYMMDDHHMMSS（不含时区偏移）

用法:
    python3 apple_hashcash.py <challenge> <bits>
"""

from __future__ import annotations

import datetime
import hashlib


def leading_zero_bits(digest: bytes) -> int:
    """数一个字节串开头有多少个连续的 0 bit。"""
    n = 0
    for b in digest:
        if b == 0:
            n += 8
            continue
        n += 8 - b.bit_length()
        break
    return n


def build_stamp(challenge: str, bits: int,
                ts: datetime.datetime | None = None,
                max_iterations: int = 50_000_000,
                timeout: float | None = 10.0) -> str | None:
    """
    生成满足 bits 位前导零的 hashcash stamp。

    :param challenge: bootData.hashcash.hcChallenge
    :param bits:      bootData.hashcash.hcBits（字符串或 int）
    :param ts:        UTC 时间；默认 now()
    :param timeout:   秒；超时返回 None（对应 isHCstrictTimeout）
    :return: 形如 "1:12:20261112133857:<challenge>:<nonce>"
    """
    bits = int(bits)
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc)
    if ts.tzinfo is not None:
        ts = ts.astimezone(datetime.timezone.utc)

    # JS: (new Date).toISOString().slice(0,19).replace(/[-:T]/g,"")
    base = "1:%d:%s:%s" % (bits, ts.strftime("%Y%m%d%H%M%S"), challenge)

    deadline = None
    if timeout:
        deadline = datetime.datetime.now().timestamp() + timeout

    nonce = 0
    while nonce < max_iterations:
        cand = "%s:%d" % (base, nonce)
        if leading_zero_bits(hashlib.sha1(cand.encode()).digest()) >= bits:
            return cand
        nonce += 1
        if deadline is not None and (nonce & 0x3FF) == 0:
            if datetime.datetime.now().timestamp() > deadline:
                return None
    return None


def verify_stamp(stamp: str, bits: int | None = None) -> bool:
    """校验 stamp 是否满足前导零要求。bits 省略时从 stamp 自身解析。"""
    parts = stamp.split(":")
    if len(parts) < 5:
        return False
    need = int(parts[1]) if bits is None else int(bits)
    return leading_zero_bits(hashlib.sha1(stamp.encode()).digest()) >= need


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        ch, bt = sys.argv[1], int(sys.argv[2])
    else:
        ch, bt = "cb829e8f304052191bd2346f36ab5130", 12

    import time
    t0 = time.time()
    st = build_stamp(ch, bt)
    cost = (time.time() - t0) * 1000
    print(f"challenge : {ch}")
    print(f"bits      : {bt}")
    print(f"stamp     : {st}")
    print(f"cost      : {cost:.0f} ms")
    print(f"verified  : {verify_stamp(st, bt) if st else False}")
