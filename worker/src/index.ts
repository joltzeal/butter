/**
 * Butter activation service.
 *
 * Codes are generated offline and imported here; the signing key lives only in
 * this Worker as a secret. Each redemption *adds* its duration to the machine's
 * licence, so codes stack and two one-week codes are two weeks.
 *
 * Routes:
 *   POST /activate      {code, machine}     redeem a code, return a licence
 *   POST /renew         {machine}           refresh a still-valid licence
 *   POST /admin/codes   (HMAC)              bulk import
 *   GET  /health
 */

const enc = new TextEncoder();

/** Master public key; the client verifies both licences and param bundles. */
const PUBLIC_KEY_SPKI = "MCowBQYDK2VwAyEAf7gPauvZ5_MuVt2jFKwRaI4qFEB6kphICxOD5reijIY";

// 1024-bit group Apple's SRP variant uses, and its k = H(N) XOR H(pad(g)).
import { SRP_N_HEX } from "./params";
const SRP_K_HEX = "05b9e8ef059c6b32ea59fc1d322d37f04aa30bae5aa9003b8321e21ddb04e300";

interface Env {
  DB: D1Database;
  /** base64url raw Ed25519 private key (32 bytes). */
  SIGNING_KEY: string;
  /** Shared secret for the import endpoint. */
  ADMIN_SECRET: string;
}

/** Payload byte-for-byte as JSON, so the signature covers exactly what is read. */
function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(text: string): Uint8Array {
  const pad = text.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(pad + "=".repeat((4 - (pad.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Ed25519 keys need an explicit DER container; raw bytes are ambiguous. */
async function importKey(secret: string) {
  return crypto.subtle.importKey("pkcs8", b64urlDecode(secret), { name: "Ed25519" }, false, ["sign"]);
}

async function verifyKey() {
  return crypto.subtle.importKey(
    "spki",
    b64urlDecode(PUBLIC_KEY_SPKI),
    { name: "Ed25519" },
    false,
    ["verify"],
  );
}

interface Payload {
  code: string;
  machine: string;
  plan: string;
  iat: number;
  exp: number;
  jti: string;
}

async function sign(env: Env, payload: Payload) {
  const body = enc.encode(JSON.stringify(payload));
  const key = await importKey(env.SIGNING_KEY);
  const sig = await crypto.subtle.sign({ name: "Ed25519" }, key, body);
  return { payload: b64url(body), sig: b64url(new Uint8Array(sig)) };
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

function sanitize(value: unknown, max = 64): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

async function machineLicence(env: Env, machine: string) {
  return env.DB.prepare("SELECT plan, exp FROM licences WHERE machine = ?")
    .bind(machine)
    .first<{ plan: string; exp: number }>();
}

async function issue(env: Env, machine: string, plan: string, seconds: number, code: string) {
  const now = Math.floor(Date.now() / 1000);
  const current = await machineLicence(env, machine);
  // Stack on the remaining time; a lapsed licence restarts from now.
  const base = current && current.exp > now ? current.exp : now;
  const exp = base + seconds;

  await env.DB.prepare(
    `INSERT INTO licences (machine, plan, exp, updated_at) VALUES (?, ?, ?, ?)
     ON CONFLICT(machine) DO UPDATE SET plan = excluded.plan, exp = excluded.exp,
       updated_at = excluded.updated_at`,
  )
    .bind(machine, plan, exp, now)
    .run();

  const token = await sign(env, { code, machine, plan, iat: now, exp, jti: crypto.randomUUID() });
  return { ...token, checked: now, exp, days_left: Math.ceil((exp - now) / 86400) };
}

async function activate(request: Request, env: Env) {
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const code = sanitize(body.code, 32).toUpperCase();
  const machine = sanitize(body.machine, 32);
  if (!code || !machine) return json({ detail: "缺少激活码或机器标识" }, 400);

  const row = await env.DB.prepare(
    "SELECT code, plan, seconds, bound, revoked, redeemed_at FROM codes WHERE code = ?",
  )
    .bind(code)
    .first<{ code: string; plan: string; seconds: number; bound: string | null; revoked: number; redeemed_at: number | null }>();
  if (!row) return json({ detail: "激活码不存在" }, 404);
  if (row.revoked) return json({ detail: "激活码已被作废" }, 409);

  // A code may be reused by the machine that already holds it (reinstall), but
  // never grants its duration twice.
  if (row.bound && row.bound !== machine) {
    return json({ detail: "激活码已绑定其他设备" }, 409);
  }

  const now = Math.floor(Date.now() / 1000);
  if (!row.bound) {
    await env.DB.prepare("UPDATE codes SET bound = ?, redeemed_at = ? WHERE code = ?")
      .bind(machine, now, code)
      .run();
    const licence = await issue(env, machine, row.plan, row.seconds, code);
    return json(licence);
  }

  // Already bound to this machine: just hand back the standing licence.
  const current = await machineLicence(env, machine);
  if (!current || current.exp <= now) {
    const licence = await issue(env, machine, row.plan, 0, code);
    return json(licence);
  }
  const token = await sign(env, {
    code,
    machine,
    plan: current.plan,
    iat: now,
    exp: current.exp,
    jti: crypto.randomUUID(),
  });
  return json({ ...token, checked: now, exp: current.exp, days_left: Math.ceil((current.exp - now) / 86400) });
}

/**
 * Protocol constants. The client can be decompiled; these cannot.
 * Request must carry a currently-valid licence in `x-payload` / `x-sig`.
 */
async function params(request: Request, env: Env) {
  const payload = request.headers.get("x-payload") ?? "";
  const sig = request.headers.get("x-sig") ?? "";
  if (!payload || !sig) return json({ detail: "缺少许可证" }, 401);

  const body = b64urlDecode(payload);
  const key = await verifyKey();
  const ok = await crypto.subtle.verify(
    { name: "Ed25519" },
    key,
    b64urlDecode(sig),
    body,
  );
  if (!ok) return json({ detail: "许可证无效" }, 401);

  const claims = JSON.parse(new TextDecoder().decode(body)) as { machine: string; exp: number };
  if (claims.exp <= Math.floor(Date.now() / 1000)) return json({ detail: "许可证已过期" }, 401);
  if (claims.machine !== request.headers.get("x-machine")) return json({ detail: "机器不匹配" }, 401);

  const bundle = {
    n_hex: SRP_N_HEX,
    k_hex: SRP_K_HEX,
    jr: "30",
    domain_id: "39",
    ver: 3,
  };
  const raw = enc.encode(JSON.stringify(bundle));
  const signingKey = await importKey(env.SIGNING_KEY);
  const out = await crypto.subtle.sign({ name: "Ed25519" }, signingKey, raw);
  return json({ payload: b64url(raw), sig: b64url(new Uint8Array(out)) });
}

async function renew(request: Request, env: Env) {
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const machine = sanitize(body.machine, 32);
  if (!machine) return json({ detail: "缺少机器标识" }, 400);

  const current = await machineLicence(env, machine);
  if (!current) return json({ detail: "未激活" }, 404);
  const now = Math.floor(Date.now() / 1000);
  if (current.exp <= now) return json({ detail: "已过期" }, 410);

  const token = await sign(env, {
    code: "renew",
    machine,
    plan: current.plan,
    iat: now,
    exp: current.exp,
    jti: crypto.randomUUID(),
  });
  return json({ ...token, checked: now, exp: current.exp, days_left: Math.ceil((current.exp - now) / 86400) });
}

async function adminCodes(request: Request, env: Env) {
  const raw = await request.text();
  const stamp = request.headers.get("x-stamp") ?? "";
  const mac = request.headers.get("x-sign") ?? "";
  if (!stamp || !mac) return json({ detail: "缺少签名" }, 401);
  if (Math.abs(Date.now() / 1000 - Number(stamp)) > 300) return json({ detail: "时间戳过期" }, 401);

  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(env.ADMIN_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const expected = b64url(new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(stamp + raw))));
  if (expected !== mac) return json({ detail: "签名不匹配" }, 401);

  const body = JSON.parse(raw || "{}") as { codes?: Array<{ code: string; plan: string; days: number }> };
  const rows = (body.codes ?? []).filter((c) => c.code && c.days > 0);
  if (!rows.length) return json({ detail: "没有可导入的码" }, 400);

  const now = Math.floor(Date.now() / 1000);
  const stmt = env.DB.prepare(
    "INSERT OR IGNORE INTO codes (code, plan, seconds, created_at) VALUES (?, ?, ?, ?)",
  );
  await env.DB.batch(rows.map((c) => stmt.bind(c.code.toUpperCase(), c.plan || "custom", c.days * 86400, now)));
  return json({ imported: rows.length });
}

export default {
  async fetch(request: Request, env: Env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return json({ ok: true });
    try {
      if (request.method === "POST" && url.pathname === "/activate") return await activate(request, env);
      if (request.method === "POST" && url.pathname === "/renew") return await renew(request, env);
      if (request.method === "GET" && url.pathname === "/params") return await params(request, env);
      if (request.method === "POST" && url.pathname === "/admin/codes") return await adminCodes(request, env);
      return json({ detail: "not found" }, 404);
    } catch (err) {
      return json({ detail: String(err) }, 500);
    }
  },
};
