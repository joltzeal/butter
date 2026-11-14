export type ViewId = "accounts" | "billing" | "network" | "logs" | "settings";

export interface Toast {
  id: number;
  kind: "ok" | "error" | "info";
  title: string;
  detail?: string;
}

export type TradeLine = "HK" | "US";
