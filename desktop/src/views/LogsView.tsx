import { ArrowDownToLine, ScrollText } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRealtime } from "../hooks/useRealtime";
import { Button, Panel } from "../components/ui";

const INTERESTING = new Set([
  "login.progress",
  "login.done",
  "login.hsa2",
  "billing.progress",
  "billing.fetched",
  "billing.updated",
  "billing.failed",
  "session.progress",
  "session.done",
  "batch.progress",
  "batch.done",
]);

const FILTERS = [
  ["all", "全部"],
  ["login", "登录"],
  ["billing", "账单"],
  ["session", "会话"],
  ["batch", "批量"],
] as const;

export function LogsView() {
  const { events, state } = useRealtime();
  const [filter, setFilter] = useState<string>("all");
  const listRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);

  const filtered = events.filter((event) => filter === "all" || event.event.startsWith(filter));

  useEffect(() => {
    if (pinned && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [filtered.length, pinned]);

  return (
    <div className="page page--wide">
      <div className="page__head">
        <div>
          <h1>事件</h1>
          <p>登录、账单与会话检测的实时进度流（WebSocket）</p>
        </div>
        <div className="page__actions">
          <div className="seg">
            {FILTERS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={filter === value}
                data-on={filter === value}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <Panel
        title={`${filtered.length} 条`}
        subtitle={state === "online" ? "通道在线" : "通道离线，等待重连"}
        actions={
          <Button icon={ArrowDownToLine} variant="ghost" onClick={() => setPinned(true)} disabled={pinned}>
            回到底部
          </Button>
        }
      >
        <div className="logs">
          <div
            className="logs__list"
            ref={listRef}
            role="log"
            aria-live="polite"
            onScroll={(event) => {
              const el = event.currentTarget;
              setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
            }}
          >
            {filtered.length === 0 ? (
              <div className="logs__empty">
                <ScrollText style={{ width: 14, verticalAlign: -2, marginRight: 6 }} />
                还没有事件。执行一次登录或账单操作就会出现在这里。
              </div>
            ) : (
              filtered.map((event) => (
                <div
                  className="log-line"
                  key={event.id ?? `${event.event}-${event.ts}`}
                  style={INTERESTING.has(event.event) ? undefined : { opacity: 0.6 }}
                >
                  <time>{(event.ts ?? "").replace("T", " ").replace("+00:00", "Z")}</time>
                  <span className="evt">{event.event}</span>
                  <span className="body">
                    {Object.entries(event.payload)
                      .filter(([, value]) => value !== null && value !== undefined && value !== "")
                      .map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`)
                      .join("  ")}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}
