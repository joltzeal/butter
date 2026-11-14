import {
  Copy,
  LogIn,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  UserPlus,
  Users,
  WifiOff,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Account } from "../api/client";
import { useAccountActions, useAccounts } from "../hooks/useAccounts";
import { useRealtime } from "../hooks/useRealtime";
import { relativeTime } from "../lib/format";
import { Badge, Button, Checkbox, Empty, Skeleton } from "../components/ui";
import { AddAccountDialog } from "./AddAccountDialog";
import { BulkImportDialog } from "./BulkImportDialog";
import { Hsa2Dialog } from "./Hsa2Dialog";
import { ConfirmDialog } from "./ConfirmDialog";

function statusTone(account: Account): { tone: "online" | "offline" | "idle"; label: string } {
  if (account.status === "online" || account.logged_in) return { tone: "online", label: "在线" };
  if (account.status === "offline") return { tone: "offline", label: "掉线" };
  if (account.status === "checking") return { tone: "idle", label: "检测中" };
  return { tone: "idle", label: "待登录" };
}

export function AccountsView() {
  const { data, isLoading, isError, error, refetch } = useAccounts();
  const actions = useAccountActions();
  const { lastEvent, state } = useRealtime();

  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [hsa2Reason, setHsa2Reason] = useState("");
  const [hsa2Email, setHsa2Email] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    if (lastEvent?.event === "login.hsa2") {
      const email = String(lastEvent.payload.email ?? "");
      if (email) {
        setHsa2Email(email);
        setHsa2Reason(String(lastEvent.payload.reason ?? ""));
      }
    }
  }, [lastEvent]);

  const accounts = useMemo(() => {
    const list = data ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return list;
    return list.filter(
      (a) => a.email.toLowerCase().includes(needle) || a.note.toLowerCase().includes(needle),
    );
  }, [data, query]);

  const current = accounts.find((a) => a.email === selected) ?? null;
  const allChecked = accounts.length > 0 && checked.size === accounts.length;

  const toggle = (email: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  const cards = (data ?? []).filter((a) => a.has_card).length;

  return (
    <div className="accounts">
      <div className="accounts__head">
        <div className="accounts__title">
          <h1>账号</h1>
          <span>
            {data?.length ?? 0} 个账号 · {cards} 张已绑卡
          </span>
        </div>
        <div className="row" style={{ marginLeft: 14, gap: 6 }}>
          <Button icon={RefreshCw} variant="ghost" onClick={() => void refetch()} title="刷新列表" />
          <Button
            icon={WifiOff}
            variant="ghost"
            onClick={() => actions.checkSessions.mutate([...checked])}
            disabled={actions.checkSessions.isPending || state !== "online" || checked.size === 0}
            title={checked.size ? "" : "请先勾选账号"}
          >
            检测会话{checked.size ? ` (${checked.size})` : ""}
          </Button>
          <Button
            icon={LogIn}
            onClick={() => actions.reloginBatch.mutate([...checked])}
            disabled={actions.reloginBatch.isPending || checked.size === 0}
            title={checked.size ? "" : "请先勾选账号"}
          >
            批量重登{checked.size ? ` (${checked.size})` : ""}
          </Button>
          <Button icon={Upload} variant="ghost" onClick={() => setBulkOpen(true)}>
            批量导入
          </Button>
          <Button icon={Plus} variant="primary" onClick={() => setAddOpen(true)}>
            添加账号
          </Button>
        </div>
        <div className="search">
          <Search />
          <input
            placeholder="搜索邮箱或备注…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <div className="accounts__body" data-detail={Boolean(current)}>
        <div className="accounts__table">
          {isLoading ? (
            <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 10 }}>
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} height={34} />
              ))}
            </div>
          ) : isError ? (
            <Empty
              icon={Users}
              title="无法读取账号"
              action={<Button onClick={() => void refetch()}>重试</Button>}
            >
              {error instanceof Error ? error.message : "后端未连接"}
            </Empty>
          ) : accounts.length === 0 ? (
            <Empty
              icon={UserPlus}
              title={query ? "没有匹配的账号" : "还没有账号"}
              action={
                <Button icon={Plus} variant="primary" onClick={() => setAddOpen(true)}>
                  添加第一个账号
                </Button>
              }
            >
              {query ? "换个关键词试试。" : "导入 Apple ID 之后即可读取与修改账单。"}
            </Empty>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 34 }}>
                      <Checkbox
                        on={allChecked}
                        onChange={(next) => setChecked(next ? new Set(accounts.map((a) => a.email)) : new Set())}
                      />
                    </th>
                    <th>账号</th>
                    <th style={{ width: 92 }}>会话</th>
                    <th style={{ width: 108 }}>账单</th>
                    <th style={{ width: 132 }}>最近登录</th>
                    <th style={{ width: 44 }} />
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((account) => {
                    const tone = statusTone(account);
                    return (
                      <tr
                        key={account.email}
                        data-selected={selected === account.email}
                        data-checked={checked.has(account.email)}
                        onClick={() => setSelected(account.email === selected ? null : account.email)}
                      >
                        <td>
                          <div className="cell-check" data-on={checked.has(account.email)}>
                            <Checkbox on={checked.has(account.email)} onChange={() => toggle(account.email)} />
                          </div>
                        </td>
                        <td>
                          <div className="cell-id">
                            <span className="avatar">{account.email.slice(0, 2).toUpperCase()}</span>
                            <div className="cell-id__text">
                              <span className="cell-email">{account.email}</span>
                              <span className="cell-id__note">
                                {account.note || (account.has_password ? "已保存密码" : "无密码")}
                                {account.has_des ? " · 可信设备" : ""}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="session-cell">
                            <Badge tone={tone.tone} dot pulse={tone.tone === "online"}>
                              {tone.label}
                            </Badge>
                          </div>
                        </td>
                        <td>
                          {account.billing_checked ? (
                            account.has_card ? (
                              <Badge tone="card">•••• {account.card_suffix || "已绑"}</Badge>
                            ) : (
                              <Badge tone="noc">无卡</Badge>
                            )
                          ) : (
                            <span className="dim tiny">未读取</span>
                          )}
                        </td>
                        <td className="cell-mono">{relativeTime(account.last_login)}</td>
                        <td>
                          <button
                            className="btn btn--ghost btn--icon"
                            title="删除账号"
                            onClick={(event) => {
                              event.stopPropagation();
                              setConfirmDelete(account.email);
                            }}
                          >
                            <Trash2 />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {checked.size > 0 ? (
                <div className="table__foot">
                  <div className="selection-bar">
                    已选 <b>{checked.size}</b> 个
                    <Button variant={["ghost", "sm"]} onClick={() => setChecked(new Set())} icon={X}>
                      取消
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>

        {current ? (
          <aside className="detail">
            <div className="detail__head">
              <span className="avatar" style={{ width: 34, height: 34, borderRadius: 10 }}>
                {current.email.slice(0, 2).toUpperCase()}
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="detail__email">{current.email}</div>
                <div className="detail__meta">
                  {current.has_password ? "密码已保存" : "未保存密码"} ·{" "}
                  {current.has_des ? "DES cookie 有效" : "无可信设备 cookie"}
                </div>
              </div>
              <button className="btn btn--ghost btn--icon" style={{ marginLeft: "auto" }} onClick={() => setSelected(null)}>
                <X />
              </button>
            </div>

            <div className="detail__section">
              <div className="kv">
                <span>会话</span>
                <b>{statusTone(current).label}</b>
              </div>
              <div className="kv">
                <span>最近登录</span>
                <b>{relativeTime(current.last_login)}</b>
              </div>
              <div className="kv">
                <span>账单</span>
                <b>
                  {current.billing_checked
                    ? current.has_card
                      ? `•••• ${current.card_suffix}`
                      : "无卡"
                    : "未读取"}
                </b>
              </div>
              <div className="kv">
                <span>账单更新</span>
                <b>{relativeTime(current.billing_updated_at)}</b>
              </div>
            </div>

            <div className="detail__section">
              <div className="detail__label">操作</div>
              <div className="detail__actions">
                <Button
                  icon={LogIn}
                  variant="primary"
                  onClick={() => actions.login.mutate({ email: current.email })}
                  disabled={actions.login.isPending || !current.has_password}
                >
                  重新登录
                </Button>
                <Button
                  icon={WifiOff}
                  onClick={() => actions.checkSessions.mutate([current.email])}
                  disabled={actions.checkSessions.isPending}
                >
                  检测会话
                </Button>
                <Button
                  icon={RefreshCw}
                  onClick={() => actions.fetchBilling.mutate(current.email)}
                  disabled={actions.fetchBilling.isPending}
                >
                  读取账单
                </Button>
                <Button
                  icon={Copy}
                  onClick={() => void navigator.clipboard.writeText(current.email)}
                  variant="ghost"
                >
                  复制邮箱
                </Button>
              </div>
            </div>

            <div className="detail__section">
              <div className="detail__label">备注</div>
              <textarea
                key={current.email}
                defaultValue={current.note}
                rows={2}
                placeholder="给这个账号加个记忆点…"
                onBlur={(event) => {
                  if (event.target.value !== current.note) {
                    actions.update.mutate({ email: current.email, note: event.target.value });
                  }
                }}
              />
            </div>

            <div className="detail__section danger-zone">
              <Button icon={Trash2} variant="danger" onClick={() => setConfirmDelete(current.email)}>
                删除账号
              </Button>
            </div>
          </aside>
        ) : null}
      </div>

      <AddAccountDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSubmit={async (payload) => {
          // Fire and close: the login runs in the background and reports through
          // a toast, so the dialog never blocks on the network round trip. The
          // returned promise resolves immediately on purpose.
          setAddOpen(false);
          actions.login.mutate(payload);
        }}
      />

      <BulkImportDialog
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onSubmit={(text) => actions.bulkImport.mutateAsync(text)}
      />

      <Hsa2Dialog
        open={Boolean(hsa2Email)}
        reason={hsa2Reason}
        email={hsa2Email ?? ""}
        onCancel={() => {
          if (hsa2Email) void actions.hsa2.mutate({ email: hsa2Email, code: "" });
          setHsa2Email(null);
          setHsa2Reason("");
        }}
        onSubmit={async (code) => {
          if (hsa2Email) await actions.hsa2.mutateAsync({ email: hsa2Email, code });
          setHsa2Email(null);
        }}
      />

      <ConfirmDialog
        open={Boolean(confirmDelete)}
        title="删除账号"
        description={`将从本地移除 ${confirmDelete ?? ""} 及其 cookies，该操作不影响 Apple 账号本身。`}
        confirmLabel="删除"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={async () => {
          if (confirmDelete) await actions.remove.mutateAsync(confirmDelete);
          setSelected(null);
          setConfirmDelete(null);
        }}
      />
    </div>
  );
}
