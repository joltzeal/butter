import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { Component, useEffect, useMemo, useState, type ReactNode } from "react";
import { CommandPalette } from "./components/CommandPalette";
import { Rail, Titlebar } from "./components/Chrome";
import { LoginProgress } from "./components/LoginProgress";
import { Button, Toasts } from "./components/ui";
import { RealtimeProvider, useRealtime } from "./hooks/useRealtime";
import { ToastProvider, useToasts } from "./hooks/useToasts";
import { useSecretUnlock } from "./hooks/useSecretUnlock";
import { useUpdater } from "./hooks/useUpdater";
import { useAccounts } from "./hooks/useAccounts";
import { isTauri } from "./api/client";
import type { ViewId } from "./lib/types";
import { WorkspaceView } from "./views/WorkspaceView";
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
    <div className="overlay-stack">
      <LoginProgress />
      <Toasts toasts={toasts} dismiss={dismiss} />
    </div>
  );
}

/** Last-resort screen: a render throw used to blank the whole webview. */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="boot" data-tauri-drag-region="deep">
        <div className="boot__card">
          <div className="boot__icon boot__icon--offline">
            <AlertTriangle />
          </div>
          <strong>界面出错了</strong>
          <pre className="boot__detail" data-tauri-drag-region="false">
            {String(this.state.error.stack ?? this.state.error)}
          </pre>
          <div className="row">
            <Button onClick={() => this.setState({ error: null })}>回到界面</Button>
            <Button variant="primary" icon={RefreshCw} onClick={() => location.reload()}>
              重新加载
            </Button>
          </div>
        </div>
      </div>
    );
  }
}

function BootScreen() {
  const { state, error, reconnect, ready } = useRealtime();

  if (state === "online" || ready) return null;

  return (
    <div className="boot" role="status" aria-live="polite" data-tauri-drag-region="deep">
      <div className="boot__card">
        <div className={state === "offline" ? "boot__icon boot__icon--offline" : "boot__icon"}>
          {state === "offline" ? <AlertTriangle /> : <Loader2 className="spin" />}
        </div>
        <strong>{state === "offline" ? "连接失败" : "启动中…"}</strong>
        {state === "offline" && error ? (
          <div className="boot__detail tiny dim" data-tauri-drag-region="false">
            {error}
          </div>
        ) : null}
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
  const { data } = useAccounts();
  // Panes mount together, so they must not render before the client exists —
  // every view calls useApi() synchronously.
  const { api } = useRealtime();
  const { push } = useToasts();
  const updater = useUpdater();
  const { unlocked } = useSecretUnlock();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // One quiet check per launch. Only the window can install, so the toast
  // offers to open the panel instead of pretending it can update in place.
  useEffect(() => {
    if (!isTauri()) return;
    const timer = window.setTimeout(async () => {
      const update = await updater.find();
      if (!update) return;
      push({
        kind: "info",
        title: `有新版本 ${update.version}`,
        detail: "在「设置 → 更新」里下载",
        action: { label: "去设置", run: () => setView("settings") },
      });
    }, 4000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Locking hides the nav item but not the view: without this the app sat on a
  // page whose entry had just disappeared.
  useEffect(() => {
    if (!unlocked && view === "logs") setView("accounts");
  }, [unlocked, view]);

  const counts = useMemo(() => {
    const rows = data ?? [];
    return {
      accounts: rows.length,
      cards: rows.filter((a) => a.has_card).length,
      online: rows.filter((a) => a.status === "online").length,
    };
  }, [data]);

  // Views stay mounted: unmounting them threw away scroll, filters, filters and
  // re-fetched every panel on each nav click.
  const panes: Array<[ViewId, ReactNode]> = [
    ["accounts", <WorkspaceView />],
    ["network", <NetworkView />],
    ["logs", <LogsView />],
    ["settings", <SettingsView />],
  ];

  return (
    <div className="shell">
      <BootScreen />
      <Titlebar view={view} onOpenPalette={() => setPaletteOpen(true)} />
      <div className="workspace">
        <Rail view={view} onChange={setView} counts={counts} />
        <main className="pane-host">
          {api
            ? panes.map(([id, pane]) => (
                <div key={id} className="pane" hidden={view !== id}>
                  {pane}
                </div>
              ))
            : null}
        </main>
      </div>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={setView}
        unlocked={unlocked}
      />
      <Overlay />
    </div>
  );
}

export default function App() {
  return (
    <Boundary>
      <QueryClientProvider client={queryClient}>
        <RealtimeProvider>
          <ToastProvider>
            <Workspace />
          </ToastProvider>
        </RealtimeProvider>
      </QueryClientProvider>
    </Boundary>
  );
}
