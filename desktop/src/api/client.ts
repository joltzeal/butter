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
  has_des: boolean;
  billing_checked: boolean;
  has_card: boolean;
  card_suffix: string;
  billing_updated_at: string;
  /** Endpoint that yields the 2FA code; empty means ask the operator. */
  code_url?: string;
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
  card_number: string;
  display_card_type: string;
}

/** Mutation result; ``info`` is what the server held on re-read. */
export interface BillingResult {
  ok: boolean;
  message?: string;
  info?: BillingInfo | null;
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
  running: boolean;
  port: number;
  pid: number | null;
  config: string;
  log: string;
  error: string;
  alive?: boolean;
}

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
  proxy: ProxyStatus;
}

export interface EventEnvelope {
  event: string;
  payload: Record<string, unknown>;
  ts?: string;
}

const FALLBACK = "http://127.0.0.1:7911";

export class BackendError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export const isTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Resolve the backend base URL once per session. */
export async function resolveBaseUrl(): Promise<string> {
  // Browser dev can pin a backend via ?api=http://127.0.0.1:PORT (handy for
  // screenshots and for talking to a non-default port outside the Tauri shell).
  if (typeof window !== "undefined") {
    const fromQuery = new URLSearchParams(window.location.search).get("api");
    if (fromQuery) {
      window.localStorage.setItem("butter.api", fromQuery);
      return fromQuery.replace(/\/$/, "");
    }
    const fromStore = window.localStorage.getItem("butter.api");
    if (fromStore && !isTauri()) return fromStore.replace(/\/$/, "");
  }
  const envBase = import.meta.env.VITE_BUTTER_API as string | undefined;
  if (envBase) return envBase.replace(/\/$/, "");
  if (!isTauri()) return FALLBACK;

  for (let attempt = 0; attempt < 90; attempt += 1) {
    try {
      const info = await invoke<BackendInfo>("backend_info");
      if (info.status === "ready" && info.baseUrl) return info.baseUrl;
      if (info.status === "failed") {
        throw new BackendError(
          `后端启动失败：${info.logTail.slice(-4).join(" ")}`,
          0,
        );
      }
    } catch (err) {
      if (err instanceof BackendError) throw err;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new BackendError("后端未在 45 秒内就绪", 0);
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

export class Api {
  constructor(private readonly base: string) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
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

  health = () => this.request<Health>("/api/health");

  listAccounts = () => this.request<Account[]>("/api/accounts");

  createAccount = (payload: { email: string; password?: string; note?: string }) =>
    this.request<Account>("/api/accounts", { method: "POST", body: JSON.stringify(payload) });

  updateAccount = (email: string, payload: { password?: string; note?: string }) =>
    this.request<Account>(`/api/accounts/${encodeURIComponent(email)}`, {
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
    code_url?: string;
  }) =>
    this.request<{ ok: boolean; message: string; account: Account }>("/api/accounts/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });

  submitHsa2 = (email: string, code: string) =>
    this.request<{ accepted: boolean }>(`/api/accounts/${encodeURIComponent(email)}/hsa2`, {
      method: "POST",
      body: JSON.stringify({ code }),
    });

  bulkImport = (text: string) =>
    this.request<BulkResult>("/api/accounts/bulk", {
      method: "POST",
      body: JSON.stringify({ text }),
    });

  batchRelogin = (emails?: string[]) =>
    this.request<{ ok: boolean; count: number }>("/api/accounts/batch-relogin", {
      method: "POST",
      body: JSON.stringify({ emails: emails ?? null }),
    });

  getBilling = (email: string) =>
    this.request<{ ok: boolean; info?: BillingInfo; account?: Account; message?: string; session_expired?: boolean }>(
      `/api/accounts/${encodeURIComponent(email)}/billing`,
    );

  putBilling = (email: string, form: BillingForm) =>
    this.request<BillingResult>(
      `/api/accounts/${encodeURIComponent(email)}/billing`,
      { method: "PUT", body: JSON.stringify(form) },
    );

  deleteBilling = (email: string) =>
    this.request<BillingResult>(`/api/accounts/${encodeURIComponent(email)}/billing`, {
      method: "DELETE",
    });

  checkSessions = (emails?: string[]) =>
    this.request<{ ok: boolean; results: Array<{ email: string; ok: boolean; status: string }> }>(
      "/api/sessions/check",
      { method: "POST", body: JSON.stringify({ emails: emails ?? null }) },
    );

  checkSession = (email: string) =>
    this.request<{ ok: boolean; status: string; message?: string }>(
      `/api/accounts/${encodeURIComponent(email)}/session`,
      { method: "POST" },
    );

  parsePaste = (text: string) =>
    this.request<{ fields: Record<string, string>; count: number }>("/api/paste", {
      method: "POST",
      body: JSON.stringify({ text }),
    });

  clashStatus = () => this.request<ClashStatus>("/api/clash/status");

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
    });

  version = () => this.request<{ version: string }>("/api/version");

  getSettings = () => this.request<Settings>("/api/settings");

  saveSettings = (patch: Partial<Settings>) =>
    this.request<{ ok: boolean }>("/api/settings", { method: "PUT", body: JSON.stringify(patch) });

  previewProfile = () => this.request<Record<string, unknown>>("/api/proxy/preview");

  startProxy = () => this.request<ProxyStatus>("/api/proxy/start", { method: "POST" });

  stopProxy = () => this.request<ProxyStatus>("/api/proxy/stop", { method: "POST" });

  proxyStatus = () => this.request<ProxyStatus>("/api/proxy/status");

  wsUrl = () => `${this.base.replace(/^http/, "ws")}/ws`;
}
