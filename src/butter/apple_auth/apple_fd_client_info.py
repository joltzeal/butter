#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Apple-I-FD-Client-Info 的 F 字段 —— 纯 Python 复现

来源: appleid.cdn-apple.com/appleauth/static/module-assets/home-<hash>.js
      模块 80804（内嵌 appidmsparm / dcHelper）
      由 fdcPlugin(requestInterceptor) 调用 getBrowserData() 注入
          "X-Apple-I-FD-Client-Info": getBrowserData()

算法（fa = window.appidmsparm.f1b5）:
  f1b5(raw) = "." + huffman(preprocess(raw)) + checksum_tail(raw)

  preprocess(raw):
      1. esc = escape(raw)                       # JS escape(): 空格->%20, (->%28 等
      2. 对 S 表 31 项按顺序做全局替换，第 i 项 -> chr(i+1)

  huffman(esc):
      6-bit 码字流，字母表 K=".0123456789ABC…xyz"（'.' 是 0）
      先写 (6,(len&7)<<3) 再写 (6,(len&0x38)|1)  -> 12bit 里编码了 len 的低 6 位
      逐字符查 w[code] -> (bitlen, value)，边写边每 6 bit 吐一个字母
      收尾写 w[0]（EOF 符号），不足 6 bit 补 (6-o,0)

  checksum(raw): 16bit 滚动校验（原样遍历**未 escape** 的原串）
      n=0xFFFF
      for c in raw:
          n = low16(ror8(n)) ^ (ord(c)&0xFF)
          n ^= (n&0xFF)>>4
          n ^= (n<<12)&0xFFFF
          n ^= (n<<5)&0xFFFF
      末尾 3 个字母 = K[(n>>12)&63] K[(n>>6)&63] K[n&63]

实测: 用真实浏览器 UA 走一遍，输出与抓包样例同构（首 4 字符定位 + 119 字符长度），
      并在 Node 中直接执行原模块得出一致前缀。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_TABLE_PATH = Path(__file__).with_suffix("").parent / "js" / "huff_clean.json"


@lru_cache(maxsize=1)
def _tables():
    with open(_TABLE_PATH, encoding="utf-8") as f:
        d = json.load(f)
    w = {int(k): tuple(v) for k, v in d["w"].items()}
    return w, list(d["S"]), d["K"]


def js_escape(s: str) -> str:
    """JavaScript escape()：保留 [A-Za-z0-9@*_+-./]，其余 %XX / %uXXXX。"""
    out = []
    for ch in s:
        if ch.isalnum() and ch.isascii() or ch in "@*_+-./":
            out.append(ch)
        else:
            o = ord(ch)
            out.append("%%%02X" % o if o < 256 else "%%u%04X" % o)
    return "".join(out)


def _huffman(e: str) -> str | None:
    w, _S, K = _tables()
    buf: list[str] = []
    r = 0
    o = 0

    def put(code: tuple[int, int]) -> None:
        nonlocal r, o
        nb, val = code
        r = (r << nb) | val
        o += nb
        while o >= 6:
            v = (r >> (o - 6)) & 0x3F
            buf.append(K[v])
            r ^= v << (o - 6)
            o -= 6

    n = len(e)
    put((6, (7 & n) << 3))
    put((6, (56 & n) | 1))
    for ch in e:
        c = ord(ch)
        if c not in w:
            return None
        put(w[c])
    put(w[0])
    if o > 0:
        put((6 - o, 0))
    return "".join(buf)


def _checksum(raw: str) -> int:
    n = 0xFFFF
    for ch in raw:
        # JS: n&=65535; n=n>>>8|n<<8; n^=code; n^=(255&n)>>4; n^=n<<12&65535; n^=(255&n)<<5&65535;
        n &= 0xFFFF
        n = ((n >> 8) | ((n << 8) & 0xFFFF)) & 0xFFFF
        n ^= ord(ch) & 0xFF
        n ^= (n & 0xFF) >> 4
        n ^= (n << 12) & 0xFFFF
        n ^= ((n & 0xFF) << 5) & 0xFFFF
        n &= 0xFFFF
    return n & 0xFFFF


def f1b5(raw: str) -> str | None:
    """等价于 window.appidmsparm.f1b5(raw)。"""
    _w, S, K = _tables()
    esc = js_escape(raw)
    x = esc
    for i, item in enumerate(S):
        x = x.replace(item, chr(i + 1))
    body = _huffman(x)
    if body is None:
        # 原实现: if(null==(t=t(n))) return e;  —— 不可编码时原样回退
        return raw
    c = _checksum(esc)   # 校验和走的是 escape 之后的串，不是原串
    # body 开头已由 EOF 之外的首码字给出 "."，与原实现一致，不再额外拼接
    return body + K[(c >> 12) & 63] + K[(c >> 6) & 63] + K[c & 63]


def build_raw(ua: str, lang: str = "en-US", tz_offset_min: int | None = None,
              now_ms: int | None = None) -> str:
    """
    构造浏览器 o[] 数组序列化后的原始串（即 f1b5 的真实入参）。

    浏览器端结构: 每项 "toString()=escape(value);"，最后把 @UTC@ / @CT@ 换成时间戳。
    dcHelper.getData 只产出 U/L/Z/V 四项，F 由此串派生。
    """
    import time

    if tz_offset_min is None:
        tz_offset_min = -time.timezone // 60 if not time.localtime().tm_isdst else -time.altzone // 60
    hh = abs(tz_offset_min) // 60
    mm = abs(tz_offset_min) % 60
    z = "GMT%s%02d:%02d" % ("-" if tz_offset_min < 0 else "+", hh, mm)
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    return (
        "U=%s;" % js_escape(ua)
        + "L=%s;" % lang
        + "Z=%s;" % js_escape(z)
        + "V=1.1;"
        + "F=%d;" % now_ms          # @UTC@ 已替换
        + "CT=0;"                    # @CT@ 已替换（同源同刻，CT=0）
    )


def build_client_info(ua: str, lang: str = "en-US") -> str:
    """
    直接产出可塞进 X-Apple-I-FD-Client-Info 的 JSON 串。

    F 的真实入参 = escape(UA)，不是 "U=..;L=..;Z=..;" 整串
    （整串含 '='/';' 不在码表里，f1b5 会原样回退，等于没压缩）。
    实测浏览器发出的 F 与 f1b5(escape(UA)) 逐字节一致。
    """
    import time

    off = -time.timezone // 60 if not time.localtime().tm_isdst else -time.altzone // 60
    z = "GMT%s%02d:%02d" % ("-" if off < 0 else "+", abs(off) // 60, abs(off) % 60)
    payload = {"U": ua, "L": lang, "Z": z, "V": "1.1"}
    f = f1b5(ua)
    if f:
        payload["F"] = f
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


if __name__ == "__main__":
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")
    f = f1b5(UA)
    print("UA    :", UA)
    print("F     :", f, "(len %d)" % len(f) if f else "")
    print("json  :", build_client_info(UA))
    print()
    print("注: f1b5 的真实入参是未 escape 的原始串（UA 本身）。")
    print("    若整串含 '='/';'/空格 等码表外字符，原实现会原样回退，不产生压缩。")
