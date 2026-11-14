#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple Store shld 挑战获取 + PoW 提交 + shld_bt_ck 落地

对应 烽火账单辅助工具.exe:
    src/account_manager/login_worker.py  →  LoginWorker._do_shld(self, sess, ssi, store_base, retry_fn)
    src/apple_auth/shld_solver.py        →  solve_pow_timed / solve_sha_pow_timed

════════ 真实流程 ════════
# 1) 取挑战
GET  {store_base}/shop/shld/work/s3/q
     Accept: */*
     Sec-Fetch-Site: same-origin
     Sec-Fetch-Mode: cors
     Sec-Fetch-Dest: empty
     Referer: {store_base}/shop/signIn/account?ssi={ssi}

# 2) 解挑战（shld_solver.solve_challenge）
   {"parts","low","high"}                → 位序回溯
   {"challenge","salt","algorithm",...}  → SHA-384 碰撞

# 3) 提交
POST 同端点
     Content-Type: application/json
     Origin: {store_base}
     body: {"challenge": ..., "number": ..., "took": ...}
  → Set-Cookie: shld_bt_ck=...

# 4) 判定
"[LoginWorker] shld -> ok | shld_bt_ck=… | url=s3 jr=… number=… took=…ms"
失败则 authx 必然 541（源码里 authx 前检查 has_ck / has_des，MISS 就放弃）。
"""

from __future__ import annotations

import json
import time

from .apple_shld_solver import solve_challenge

SHLD_PATH = "/shop/shld/work/s3/q"


class ShldError(RuntimeError):
    pass


def run_shld(session, store_base: str, ssi: str, verbose: bool = False,
             referer: str | None = None) -> str | None:
    """
    执行完整 shld 流程，返回 shld_bt_ck 值（失败返回 None）。

    :param session:    curl_cffi Session（已带 store cookie）
    :param store_base: 例如 https://secure7.store.apple.com
    :param ssi:        第 3 步 loc 里的 ssi
    :param referer:    默认 {store_base}/shop/signIn/account?ssi={ssi}
    """
    url = store_base.rstrip("/") + SHLD_PATH
    ref = referer or f"{store_base.rstrip('/')}/shop/signIn/account?ssi={ssi}"

    # ---------- 1) 取挑战 ----------
    h = {
        "Accept": "*/*",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": ref,
    }
    if verbose:
        print(f"    [shld] GET {url}")
    try:
        r = session.get(url, headers=h, timeout=20, allow_redirects=False)
    except Exception as e:
        print(f"    [shld] GET 失败 | EXC {type(e).__name__}: {e}")
        return None

    if r.status_code != 200:
        print(f"    [shld] GET 失败 | status={r.status_code} url={url} body={r.text[:200]!r}")
        return None

    body_txt = (r.text or "").strip()
    if verbose:
        print(f"    [shld] 挑战原文: {body_txt[:300]}")
    try:
        jsa = json.loads(body_txt)
    except Exception:
        print(f"    [shld] 挑战非 JSON: {body_txt[:200]!r}")
        return None

    # ---------- 2) 求解 ----------
    try:
        solved = solve_challenge(jsa)
    except ValueError as e:
        print(f"    [shld] {e}")
        return None

    number = solved["number"]
    took = solved["took"]
    print(f"    [shld] mode={solved['mode']} number={number} took={took}ms")

    # ---------- 3) 提交 ----------
    post_body = {
        "challenge": solved.get("challenge") or jsa.get("challenge"),
        "number": number,
        "took": took,
    }
    ph = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": store_base.rstrip("/"),
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": ref,
    }
    if verbose:
        print(f"    [shld] POST {url} body={json.dumps(post_body)[:200]}")
    try:
        r2 = session.post(url, headers=ph, data=json.dumps(post_body), timeout=20,
                          allow_redirects=False)
    except Exception as e:
        print(f"    [shld] POST 失败 | EXC {type(e).__name__}: {e}")
        return None

    # ---------- 4) 取 shld_bt_ck ----------
    ck = None
    try:
        for ck_name, ck_val in _iter_cookies(session):
            if ck_name == "shld_bt_ck":
                ck = ck_val
    except Exception:
        pass
    if not ck:
        for sc in _split_set_cookie(r2.headers.get("set-cookie", "")):
            if sc.startswith("shld_bt_ck="):
                ck = sc.split("=", 1)[1].split(";")[0]

    print(f"    [shld] -> {'ok' if ck else 'FAIL'} | shld_bt_ck={ck or 'MISS'} "
          f"| number={number} took={took}ms status={r2.status_code}")
    if verbose and r2.text:
        print(f"    [shld] POST 响应: {r2.text[:300]}")
    return ck


def _iter_cookies(session):
    try:
        jar = session.cookies.jar
        for c in jar:
            yield c.name, c.value
    except Exception:
        try:
            d = session.cookies.get_dict()
            for k, v in d.items():
                yield k, v
        except Exception:
            return


def _split_set_cookie(raw: str):
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if "=" in part and " " not in part.split("=")[0]:
            out.append(part.split(";")[0])
    return out


if __name__ == "__main__":
    print("用法: from .apple_shld import run_shld")
    print("      run_shld(session, 'https://secure7.store.apple.com', ssi)")
