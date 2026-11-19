import { Command, ListOrdered, Settings2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ViewId } from "../lib/types";

const ITEMS: Array<{ id: ViewId; label: string; hint: string; icon: typeof ListOrdered }> = [
  { id: "accounts", label: "账号", hint: "账号列表与批量操作", icon: ListOrdered },
  { id: "settings", label: "设置", hint: "外观与行为", icon: Settings2 },
];

export function CommandPalette({
  open,
  onClose,
  onNavigate,
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (view: ViewId) => void;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const items = useMemo(
    () =>
      ITEMS.filter(
        (item) =>
          !query.trim() ||
          item.label.includes(query.trim()) ||
          item.hint.toLowerCase().includes(query.trim().toLowerCase()),
      ),
    [query],
  );

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal modal--sm"
        style={{ width: 460, alignSelf: "flex-start", marginTop: 120 }}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal__head" style={{ padding: "12px 14px" }}>
          <Command style={{ width: 15, color: "var(--text-dim)" }} />
          <input
            autoFocus
            placeholder="跳转到…"
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
                onNavigate(items[index].id);
                onClose();
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
              onClick={() => {
                onNavigate(item.id);
                onClose();
              }}
              style={{ width: "100%" }}
            >
              <item.icon />
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                <span>{item.label}</span>
                <span className="tiny dim">{item.hint}</span>
              </div>
            </button>
          ))}
          {items.length === 0 ? <div className="dim tiny" style={{ padding: 12 }}>没有匹配项</div> : null}
        </div>
      </div>
    </div>
  );
}
