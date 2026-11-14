import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CommandPalette } from "./components/CommandPalette";
import { Rail, Titlebar } from "./components/Chrome";
import { LoginProgress } from "./components/LoginProgress";
import { Button, Toasts } from "./components/ui";
import { RealtimeProvider, useRealtime } from "./hooks/useRealtime";
import { ToastProvider, useToasts } from "./hooks/useToasts";
import { useAccounts } from "./hooks/useAccounts";
import type { ViewId } from "./lib/types";
import { AccountsView } from "./views/AccountsView";
import { BillingView } from "./views/BillingView";
import { LogsView } from "./views/LogsView";
import { NetworkView } from "./views/NetworkView";
import { SettingsView } from "./views/SettingsView";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000, refetchOnWindowFocus: false },
    mutations: { retry: 0 },
  },
});

function Overlay() {
  const { toasts, dismiss } = useToasts();
  return (
    <>
      <LoginProgress />
      <Toasts toasts={toasts} dismiss={dismiss} />
    </>
  );
}

function BootScreen() {
  const { state, error, reconnect } = useRealtime();

  if (state === "online") return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        display: "grid",
        placeItems: "center",
        background: "var(--bg)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, maxWidth: 420 }}>
        <div
          style={{
            display: "grid",
            placeItems: "center",
            width: 46,
            height: 46,
            borderRadius: 15,
            background: state === "offline" ? "color-mix(in srgb, var(--danger) 18%, transparent)" : "var(--amber-soft)",
            border: `1px solid ${state === "offline" ? "var(--danger)" : "var(--amber-line)"}`,
            color: state === "offline" ? "var(--danger)" : "var(--amber)",
          }}
        >
          {state === "offline" ? (
            <AlertTriangle style={{ width: 20 }} />
          ) : (
            <Loader2 className="spin" style={{ width: 20 }} />
          )}
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {state === "offline" ? "连接失败" : "启动中…"}
          </div>
          {state === "offline" && error ? (
            <div className="dim tiny" style={{ marginTop: 4, lineHeight: 1.6 }}>
              {error}
            </div>
          ) : null}
        </div>
        {state === "offline" ? (
          <Button icon={RefreshCw} variant="primary" onClick={reconnect}>
            重试连接
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function Workspace() {
  const [view, setView] = useState<ViewId>("accounts");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [billingTarget, setBillingTarget] = useState<string | null>(null);
  const { data } = useAccounts();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if (event.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const counts = useMemo(
    () => ({
      accounts: data?.length ?? 0,
      cards: data?.filter((a) => a.has_card).length ?? 0,
    }),
    [data],
  );

  return (
    <div className="shell">
      <BootScreen />
      <Titlebar view={view} onOpenPalette={() => setPaletteOpen(true)} />
      <div className="workspace">
        <Rail view={view} onChange={setView} counts={counts} />
        <main style={{ minWidth: 0, minHeight: 0, display: "flex" }}>
          <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
            {view === "accounts" ? <AccountsView /> : null}
            {view === "billing" ? <BillingView initialEmail={billingTarget} /> : null}
            {view === "network" ? <NetworkView /> : null}
            {view === "logs" ? <LogsView /> : null}
            {view === "settings" ? <SettingsView /> : null}
          </div>
        </main>
      </div>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={(next) => {
          setView(next);
          if (next === "billing") setBillingTarget(null);
        }}
      />
      <Overlay />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RealtimeProvider>
        <ToastProvider>
          <Workspace />
        </ToastProvider>
      </RealtimeProvider>
    </QueryClientProvider>
  );
}
