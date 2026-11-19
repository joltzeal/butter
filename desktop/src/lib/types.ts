export type ViewId = "accounts" | "network" | "logs" | "settings";

export interface Toast {
  id: number;
  kind: "ok" | "error" | "info";
  title: string;
  detail?: string;
  /** No auto-dismiss; the flow dismisses it or the operator closes it. */
  sticky?: boolean;
  /** Closing also aborts the flow the toast is reporting on. */
  onCancel?: () => void;
}

export type TradeLine = "HK" | "US";
