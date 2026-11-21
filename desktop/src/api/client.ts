/** Typed client for the Butter Python backend. */

import { invoke } from "@tauri-apps/api/core";

export type Status = "idle" | "checking" | "online" | "offline";

export interface Account {
  email: string;
  note: string;
  status: Status;
  logged_in: boolean;
  last_login: string;
  has_password: boolean;
  /** Stored password in the clear; the UI shows and edits it directly. */
  password_plain: string;
  has_des: boolean;
  billing_checked: boolean;
  has_card: boolean;
  card_suffix: string;
  awaiting_hsa2?: boolean;
  billing_updated_at: string;
}

export interface BulkLineError {
  line: number;
  text: string;
  reason: string;
}

export interface BulkResult {
  ok: boolean;
  message: string;
  created: number;
  updated: number;
  accounts: string[];
  errors: BulkLineError[];
}

export interface BillingInfo {
  has_card: boolean;
  card_suffix: string;
  expiry: string;
  first_name: string;
  last_name: string;
  street: string;
  street2: string;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  phone: string;
  /** Apple only returns the last digits here, never the full PAN. */
  card_number: string;
  display_card_type: string;
}

/** Mutation result; ``info`` is what the server held on re-read. */
export interface BillingResult {
  ok: boolean;
  message?: string;
  info?: BillingInfo | null;
  /** The read parked on a 2FA code; the dialog takes over. */
  awaiting_hsa2?: boolean;
}

export interface BillingForm {
  card_number: string;
  card_expiry: string;
  first_name: string;
  last_name: string;
  street: string;
  street2: string;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  phone: string;
  remove_only: boolean;
}

export interface ClashGroup {
  name: string;
  type: string;
  now: string;
  members: string[];
}

export interface ClashLiveNode {
  name: string;
  type: string;
  delay: number | null;
  alive: boolean;
}

export interface ClashStatus {
  ok: boolean;
  message?: string;
  version?: Record<string, unknown>;
  groups: ClashGroup[];
  nodes: ClashLiveNode[];
}

export interface Settings {
  proxy_mode: "direct" | "custom" | "clash" | "mihomo";
  clash_api: string;
  clash_secret: string;
  clash_group: string;
  clash_socks: string;
  proxy_url: string;
  proxy_host: string;
  proxy_port: number;
  proxy_user: string;
  proxy_pass: string;
  proxy_type: string;
  hk_nodes: ClashNode[];
  line: "HK" | "US";
  impersonate: string;
  timezone: string;
  session_auto_check: boolean;
  session_check_top: number;
  session_poll: boolean;
  session_poll_seconds: number;
  retry_attempts: number;
  verbose_network_log: boolean;
  fd_client_info: string;
}

export interface ClashNode {
  type?: string;
  server: string;
  port: number;
  cipher?: string;
  password: string;
  plugin?: string;
}

export interface ProxyStatus {
  mode: string;
  /** The backend answers 0/1; read it through ``isRunning()``. */
  running: boolean | 0 | 1;
  port: number;
  pid: number | null;
  config: string;
  log: string;
  error: string;
  alive?: boolean;
}

export const isRunning = (status: ProxyStatus | null): boolean => Boolean(status?.running);

export interface BackendInfo {
  status: string;
  baseUrl: string | null;
  port: number | null;
  pid: number | null;
  command: string | null;
  logTail: string[];
}

export interface Health {
  ok: boolean;
  version: string;
  curl_cffi: boolean;
  data_dir: string;
  clients: number;
  fingerprint_pinned?: boolean;
  proxy: ProxyStatus;
}

export interface EventEnvelope {
  event: string;
  payload: Record<string, unknown>;
  ts?: string;
  /** Client-side sequence; the backend does not send one. */
  id?: number;
}

export interface License {
  licensed: boolean;
  plan: string;
  exp: number;
  free_limit: number;
  machine?: string;
}

const FALLBACK = "http://127.0.0.1:7911";
const REQUEST_TIMEOUT = 20_000;
const READ_TIMEOUT = 120_000;
// A read may have to log in first, 2FA prompt included.
const LOGIN_READ_TIMEOUT = 360_000;

export class BackendError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Raised by the boot path; carries no HTTP semantics. */
export class BootError extends Error {}

export const isTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export function normalizeBase(url: string): string {
  return url.replace(/\/+$/, "");
}

/** Resolve the backend base URL once per session. */
export async function resolveBaseUrl(signal?: AbortSignal): Promise<string> {
  // Browser dev can pin a backend via ?api=http://127.0.0.1:PORT (handy for
  // screenshots and for talking to a non-default port outside the Tauri shell).
  if (typeof window !== "undefined") {
    const fromQuery = new URLSearchParams(window.location.search).get("api");
    if (fromQuery) {
      // The shell picks a fresh port every boot, so a pinned URL is only
      // remembered for the browser workflow that set it.
      if (!isTauri()) window.localStorage.setItem("butter.api", fromQuery);
      return normalizeBase(fromQuery);
    }
    const fromStore = !isTauri() ? window.localStorage.getItem("butter.api") : null;
    if (fromStore) return normalizeBase(fromStore);
  }
  const envBase = import.meta.env.VITE_BUTTER_API as string | undefined;
  if (envBase) return normalizeBase(envBase);
  if (!isTauri()) return FALLBACK;

  for (let attempt = 0; attempt < 90; attempt += 1) {
    if (signal?.aborted) throw new BootError("已取消");
    try {
      const info = await invoke<BackendInfo>("backend_info");
      if (info.status === "ready" && info.baseUrl) return normalizeBase(info.baseUrl);
      if (info.status === "failed") {
        throw new BootError(`后端启动失败：${info.logTail.slice(-4).join(" ")}`);
      }
    } catch (err) {
      if (err instanceof BootError) throw err;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new BootError("后端未在 45 秒内就绪");
}

export async function backendInfo(): Promise<BackendInfo | null> {
  if (!isTauri()) return null;
  try {
    return await invoke<BackendInfo>("backend_info");
  } catch {
    return null;
  }
}

export async function restartBackend(): Promise<BackendInfo | null> {
  if (!isTauri()) return null;
  return invoke<BackendInfo>("backend_restart");
}

/** Remote activation endpoint; empty when the build has none. */
export const ACTIVATION_URL = normalizeBase(
  (import.meta.env.VITE_ACTIVATION_URL as string | undefined) ?? "",
);

export interface ActivationTicket {
  payload: string;
  sig: string;
  checked: number;
}

export async function activate(
  code: string,
  machine: string,
  signal?: AbortSignal,
): Promise<ActivationTicket> {
  if (!ACTIVATION_URL) throw new BackendError("尚未配置激活服务器", 0);
  const res = await fetch(`${ACTIVATION_URL}/activate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code, machine }),
    signal: signal ?? AbortSignal.timeout(REQUEST_TIMEOUT),
  });
  const body = (await res.json().catch(() => ({}))) as Partial<ActivationTicket> & {
    detail?: string;
  };
  if (!res.ok || !body.payload || !body.sig) {
    throw new BackendError(body.detail ?? "激活码无效", res.status);
  }
  return {
    payload: body.payload,
    sig: body.sig,
    checked: body.checked ?? Math.floor(Date.now() / 1000),
  };
}

/**
 * Hand the ticket to the shell for verification + persistence.
 *
 * Returns null outside Tauri: the browser preview can reach the server but has
 * no licence store, and ``invoke`` throws a TypeError there.
 */
export async function applyLicense(ticket: ActivationTicket): Promise<License | null> {
  if (!isTauri()) return null;
  return invoke<License>("license_apply", {
    payload: ticket.payload,
    sig: ticket.sig,
    checked: ticket.checked,
  });
}

export class Api {
  constructor(private readonly base: string) {}

  private async request<T>(path: string, init?: RequestInit & { timeout?: number }): Promise<T> {
    const { timeout = REQUEST_TIMEOUT, ...rest } = init ?? {};
    // Every call is bounded: without this a stalled backend let the 2.5s poll
    // stack requests on top of each other until the socket pool was gone.
    const timer = AbortSignal.timeout(timeout);
    const signal = rest.signal ? AbortSignal.any([rest.signal, timer]) : timer;
    const res = await fetch(`${this.base}${path}`, {
      ...rest,
      signal,
      headers: { "content-type": "application/json", ...(rest.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail ?? detail;
      } catch {
        /* body was not JSON */
      }
      throw new BackendError(typeof detail === "string" ? detail : res.statusText, res.status);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  health = (signal?: AbortSignal) => this.request<Health>("/api/health", { signal });

  listAccounts = (signal?: AbortSignal) =>
    this.request<Account[]>("/api/accounts", { signal, timeout: 10_000 });

  createAccount = (payload: { email: string; password?: string; note?: string }) =>
    this.request<Account>("/api/accounts", { method: "POST", body: JSON.stringify(payload) });

  updateAccount = (
    key: string,
    payload: { email?: string; password?: string; note?: string },
  ) =>
    this.request<Account>(`/api/accounts/${encodeURIComponent(key)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });

  deleteAccount = (email: string) =>
    this.request<{ removed: boolean }>(`/api/accounts/${encodeURIComponent(email)}`, {
      method: "DELETE",
    });

  reorder = (emails: string[]) =>
    this.request<{ ok: boolean }>("/api/accounts/reorder", {
      method: "POST",
      body: JSON.stringify({ emails }),
    });

  login = (payload: {
    email: string;
    password?: string;
    note?: string;
    persist?: boolean;
  }) =>
    this.request<{ ok: boolean; message: string; account: Account }>(
      "/api/accounts/login",
      // Covers the 2FA wait: the request stays open while the operator types.
      { method: "POST", body: JSON.stringify(payload), timeout: LOGIN_READ_TIMEOUT },
    );

  cancelCheck = () =>
    this.request<{ ok: boolean; message?: string }>("/api/sessions/check/cancel", {
      method: "POST",
    });

  cancelLogin = (email: string) =>
    this.request<{ ok: boolean; message?: string }>(
      `/api/accounts/${encodeURIComponent(email)}/login/cancel`,
      { method: "POST" },
    );

  logout = (email: string) =>
    this.request<{ ok: boolean; status?: string; message?: string }>(
      `/api/accounts/${encodeURIComponent(email)}/logout`,
      { method: "POST" },
    );

  submitHsa2 = (email: string, code: string) =>
    this.request<{ accepted: boolean }>(`/api/accounts/${encodeURIComponent(email)}/hsa2`, {
      method: "POST",
      body: JSON.stringify({ code }),
      timeout: 30_000,
    });

  bulkImport = (text: string) =>
    this.request<BulkResult>("/api/accounts/bulk", {
      method: "POST",
      body: JSON.stringify({ text }),
      timeout: READ_TIMEOUT,
    });

  batchRelogin = (emails?: string[]) =>
    this.request<{ ok: boolean; count: number }>("/api/accounts/batch-relogin", {
      method: "POST",
      body: JSON.stringify({ emails: emails ?? null }),
    });

  getBilling = (email: string, signal?: AbortSignal) =>
    this.request<BillingResult & { account?: Account; session_expired?: boolean }>(
      `/api/accounts/${encodeURIComponent(email)}/billing`,
      { signal, timeout: LOGIN_READ_TIMEOUT },
    );

  putBilling = (email: string, form: BillingForm) =>
    this.request<BillingResult>(
      `/api/accounts/${encodeURIComponent(email)}/billing`,
      { method: "PUT", body: JSON.stringify(form), timeout: LOGIN_READ_TIMEOUT },
    );

  deleteBilling = (email: string) =>
    this.request<BillingResult>(`/api/accounts/${encodeURIComponent(email)}/billing`, {
      method: "DELETE",
      timeout: READ_TIMEOUT,
    });

  checkSessions = (emails?: string[]) =>
    this.request<{ ok: boolean; results: Array<{ email: string; ok: boolean; status: string }> }>(
      "/api/sessions/check",
      { method: "POST", body: JSON.stringify({ emails: emails ?? null }), timeout: READ_TIMEOUT },
    );

  checkSession = (email: string) =>
    this.request<{ ok: boolean; status: string; message?: string }>(
      `/api/accounts/${encodeURIComponent(email)}/session`,
      { method: "POST", timeout: READ_TIMEOUT },
    );

  parsePaste = (text: string, signal?: AbortSignal) =>
    this.request<{ fields: Record<string, string>; count: number }>("/api/paste", {
      method: "POST",
      body: JSON.stringify({ text }),
      signal,
    });

  clashStatus = () => this.request<ClashStatus>("/api/clash/status", { timeout: 10_000 });

  clashNodes = (keyword = "", limit = 400) =>
    this.request<{ ok: boolean; nodes: ClashLiveNode[] }>(
      `/api/clash/nodes?keyword=${encodeURIComponent(keyword)}&limit=${limit}`,
    );

  clashSelect = (node: string, group?: string) =>
    this.request<{ ok: boolean; group: string; now: string }>("/api/clash/select", {
      method: "POST",
      body: JSON.stringify({ node, group: group ?? "" }),
    });

  clashRotate = (keyword = "", stride = 1, group?: string) =>
    this.request<{ ok: boolean; group: string; now: string; total: number }>("/api/clash/rotate", {
      method: "POST",
      body: JSON.stringify({ keyword, stride, group: group ?? "" }),
      timeout: 30_000,
    });

  license = () => this.request<License>("/api/license");

  version = () => this.request<{ version: string }>("/api/version");

  getSettings = (signal?: AbortSignal) => this.request<Settings>("/api/settings", { signal });

  saveSettings = (patch: Partial<Settings>) =>
    this.request<{ ok: boolean }>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    });

  previewProfile = () => this.request<Record<string, unknown>>("/api/proxy/preview");

  startProxy = () => this.request<ProxyStatus>("/api/proxy/start", { method: "POST", timeout: 60_000 });

  stopProxy = () => this.request<ProxyStatus>("/api/proxy/stop", { method: "POST" });

  proxyStatus = () => this.request<ProxyStatus>("/api/proxy/status");

  wsUrl = () => `${this.base.replace(/^http/, "ws")}/ws`;
}
