import { clsx } from "clsx";
import { Globe2, Layers, ListOrdered, ScrollText, Settings2 } from "lucide-react";
import { useRealtime } from "../hooks/useRealtime";
import { useSecretUnlock } from "../hooks/useSecretUnlock";
import type { ViewId } from "../lib/types";

const NAV: Array<{ id: ViewId; label: string; icon: typeof Globe2; hint: string }> = [
  { id: "accounts", label: "账号", icon: ListOrdered, hint: "账号与账单" },
  { id: "network", label: "网络", icon: Layers, hint: "代理链与落地线路" },
  { id: "logs", label: "事件", icon: ScrollText, hint: "实时操作流" },
  { id: "settings", label: "设置", icon: Settings2, hint: "行为与偏好" },
];

export function Titlebar({
  view,
  onOpenPalette,
}: {
  view: ViewId;
  onOpenPalette: () => void;
}) {
  const { state } = useRealtime();

  const label = state === "online" ? "已连接" : state === "boot" ? "连接中" : "离线";

  return (
    <header className="titlebar" data-tauri-drag-region="deep">
      <div className="titlebar__brand">
        <img className="titlebar__mark" src="/butter.png" alt="" />
        <span>Butter</span>
      </div>
      <div className="titlebar__sep" />
      <div className="titlebar__status">
        <i
          className={clsx("dot", state !== "online" && "dot--pulse")}
          style={{
            color: state === "online" ? "var(--ok)" : state === "boot" ? "var(--warn)" : "var(--danger)",
          }}
        />
        {label}
        <span className="dim">·</span>
        <span className="mono tiny">{NAV.find((n) => n.id === view)?.label}</span>
      </div>
      <div className="titlebar__spacer" />
      <div className="titlebar__actions">
        <button className="btn btn--ghost btn--sm" onClick={onOpenPalette}>
          命令 <span className="kbd">⌘K</span>
        </button>
      </div>
    </header>
  );
}

export function Rail({
  view,
  onChange,
  counts,
}: {
  view: ViewId;
  onChange: (next: ViewId) => void;
  counts: { accounts: number; cards: number; online: number };
}) {
  const { unlocked } = useSecretUnlock();
  return (
    <nav className="rail" aria-label="工作台">
      <div className="rail__group">
        <div className="rail__label">工作台</div>
        {NAV.filter((item) => item.id !== "logs" || unlocked).map((item) => (
          <button
            key={item.id}
            className="rail__item"
            data-active={view === item.id}
            aria-current={view === item.id ? "page" : undefined}
            onClick={() => onChange(item.id)}
            title={item.hint}
          >
            <item.icon />
            {item.label}
            {item.id === "accounts" && counts.accounts ? (
              <span className="rail__count">{counts.accounts}</span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="rail__foot">
        <div className="rail__foot-row">
          <span>会话在线</span>
          <b>{counts.online}</b>
        </div>
        <div className="rail__foot-row">
          <span>已绑卡</span>
          <b>{counts.cards}</b>
        </div>
      </div>
    </nav>
  );
}
