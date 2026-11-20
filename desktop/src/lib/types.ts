export type ViewId = "accounts" | "network" | "logs" | "settings";

export interface Toast {
  id: number;
  kind: "ok" | "error" | "info";
  title: string;
  detail?: string;
  /** No auto-dismiss; the flow dismisses it or the operator closes it. */
  sticky?: boolean;
  /** Explicit action (e.g. 取消检测). Closing the toast does not run it. */
  action?: { label: string; run: () => void };
}
