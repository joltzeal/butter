import { Command, Layers, ListOrdered, ScrollText, Settings2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ViewId } from "../lib/types";
import { Dialog } from "./Dialog";

interface Item {
  id: ViewId;
  label: string;
  hint: string;
  icon: typeof ListOrdered;
  needsUnlock?: boolean;
}

const ITEMS: Item[] = [
  { id: "accounts", label: "账号", hint: "账号列表与批量操作", icon: ListOrdered },
  { id: "network", label: "网络", hint: "代理链与落地线路", icon: Layers },
  { id: "logs", label: "事件", hint: "实时操作流", icon: ScrollText, needsUnlock: true },
  { id: "settings", label: "设置", hint: "外观与行为", icon: Settings2 },
];

export function CommandPalette({
  open,
  onClose,
  onNavigate,
  unlocked,
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (view: ViewId) => void;
  unlocked: boolean;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return ITEMS.filter((item) => {
      if (item.needsUnlock && !unlocked) return false;
      if (!q) return true;
      return item.label.toLowerCase().includes(q) || item.hint.toLowerCase().includes(q);
    });
  }, [query, unlocked]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setIndex(0);
  }, [open]);

  const go = (item: Item) => {
    onNavigate(item.id);
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} title="跳转" size="sm" bare panelClass="palette">
      <header className="modal__head" style={{ padding: "12px 14px" }}>
        <Command style={{ width: 15, color: "var(--text-dim)" }} />
        <input
          autoFocus
          placeholder="跳转到…"
          aria-label="跳转到"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setIndex(0);
          }}
          style={{ border: "none", background: "transparent", padding: 0, height: 22 }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setIndex((i) => Math.min(items.length - 1, i + 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setIndex((i) => Math.max(0, i - 1));
            } else if (event.key === "Enter" && items[index]) {
              event.preventDefault();
              go(items[index]);
            }
          }}
        />
        <span className="kbd">ESC</span>
      </header>
      <div className="modal__body" style={{ padding: 6, gap: 2 }}>
        {items.map((item, i) => (
          <button
            key={item.id}
            className="rail__item"
            data-active={i === index}
            onMouseEnter={() => setIndex(i)}
            onClick={() => go(item)}
            style={{ width: "100%" }}
          >
            <item.icon />
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
              <span>{item.label}</span>
              <span className="tiny dim">{item.hint}</span>
            </div>
          </button>
        ))}
        {items.length === 0 ? (
          <div className="dim tiny" style={{ padding: 12 }}>
            没有匹配项
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
