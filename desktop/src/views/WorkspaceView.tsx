import {
  CheckSquare,
  ChevronRight,
  ClipboardPaste,
  Eye,
  Loader2,
  LogIn,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldOff,
  Sparkles,
  Trash2,
  Upload,
  UserPlus,
  Users,
  WifiOff,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useAccountActions, useAccounts } from "../hooks/useAccounts";
import { useOptionalApi, useRealtime } from "../hooks/useRealtime";
import { useToasts } from "../hooks/useToasts";
import type { Account, BillingForm, BillingInfo } from "../api/client";
import { COUNTRIES } from "../lib/countries";
import { relativeTime } from "../lib/format";
import { Badge, Button, Checkbox, Empty, Field, Panel, Skeleton } from "../components/ui";
import { AddAccountDialog } from "./AddAccountDialog";
import { BulkImportDialog } from "./BulkImportDialog";
import { ConfirmDialog } from "./ConfirmDialog";
import { Hsa2Dialog } from "./Hsa2Dialog";
import { PasteDialog } from "./PasteDialog";
import { CreditCard } from "../components/shared-assets/credit-card/credit-card";

const EMPTY: BillingForm = {
  card_number: "",
  card_expiry: "",
  first_name: "",
  last_name: "",
  phone: "",
  street: "",
  street2: "",
  city: "",
  state: "",
  postal_code: "",
  country_code: "US",
  remove_only: false,
};

function toForm(info: BillingInfo): BillingForm {
  return {
    card_number: "",
    card_expiry: info.expiry || "",
    first_name: info.first_name || "",
    last_name: info.last_name || "",
    phone: info.phone || "",
    street: info.street || "",
    street2: info.street2 || "",
    city: info.city || "",
    state: info.state || "",
    postal_code: info.postal_code || "",
    country_code: (info.country_code || "US").toUpperCase(),
    remove_only: false,
  };
}

/** "VISA **** 4141 12/34" — the collapsed stand-in for the card art. */
function cardSummary(info: BillingInfo): string {
  const brand = (info.display_card_type || "CARD").toUpperCase();
  const suffix = info.card_suffix || "••••";
  // Apple answers "4/27"; the summary reads better zero-padded ("04/27").
  const expiry = (info.expiry || "").replace(/^(\d)\//, "0$1/");
  return [brand, `**** ${suffix}`, expiry].filter(Boolean).join(" ");
}

function statusTone(account: Account): { tone: "online" | "offline" | "idle"; label: string } {
  if (account.status === "online") return { tone: "online", label: "在线" };
  if (account.status === "offline") return { tone: "offline", label: "掉线" };
  if (account.status === "checking") return { tone: "idle", label: "检测中" };
  return { tone: "idle", label: "待登录" };
}

/**
 * One screen: the account list on the left, the selected account's billing in a
 * peek panel on the right, every action in a bar pinned to the bottom.
 *
 * Accounts and billing used to be two tabs, which meant clicking through to a
 * second screen just to read one card. Here the row a person already picked
 * stays visible while its billing is shown beside it.
 */
export function WorkspaceView() {
  const { data, isLoading, isError, error, refetch } = useAccounts();
  const actions = useAccountActions();
  const { lastEvent } = useRealtime();
  const api = useOptionalApi();
  const { push } = useToasts();

  const accounts = useMemo(() => data ?? [], [data]);
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [hsa2Email, setHsa2Email] = useState<string | null>(null);
  const [hsa2Reason, setHsa2Reason] = useState("");
  const [form, setForm] = useState<BillingForm>({ ...EMPTY });
  const [info, setInfo] = useState<BillingInfo | null>(null);
  const [reveal, setReveal] = useState(false);
  const [notice, setNotice] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter(
      (a) => a.email.toLowerCase().includes(q) || (a.note || "").toLowerCase().includes(q),
    );
  }, [accounts, query]);

  const current = useMemo(
    () => accounts.find((a) => a.email === selected) ?? null,
    [accounts, selected],
  );

  // Selection paints the cache if there is one; otherwise the peek panel shows
  // a button and no request is made until it is pressed.
  // No cache painting: selecting an account always shows the veil until a real
  // read lands, so what is on screen is exactly what the server answered.
  // Selecting an account only prepares the pane. The read is explicit: the
  // button starts it, and an offline session is logged in as part of that same
  // press rather than on every row click.
  useEffect(() => {
    setInfo(null);
    setForm({ ...EMPTY });
    setNotice("");
  }, [selected]);

  useEffect(() => {
    if (lastEvent?.event !== "account.status") return;
    void refetch();
  }, [lastEvent, refetch]);

  // Open the code dialog as soon as a login parks on 2FA. The event is
  // fire-and-forget, so the account list also carries the flag and the dialog
  // opens from state — a reload or a late listener would otherwise miss it.
  useEffect(() => {
    if (lastEvent?.event === "login.hsa2") {
      const email = String(lastEvent.payload.email ?? "");
      if (email) {
        setHsa2Email(email);
        setHsa2Reason(String(lastEvent.payload.reason ?? ""));
      }
    }
  }, [lastEvent]);

  useEffect(() => {
    if (hsa2Email) return;
    const waiting = accounts.find((a) => a.awaiting_hsa2);
    if (waiting) setHsa2Email(waiting.email);
  }, [accounts, hsa2Email]);

  useEffect(() => {
    if (!lastEvent || !selected) return;
    if (lastEvent.event === "billing.fetched" && lastEvent.payload.email === selected) {
      const next = lastEvent.payload.info as BillingInfo;
      setInfo(next);
      setForm(toForm(next));
    }
  }, [lastEvent, selected]);

  const allChecked = filtered.length > 0 && filtered.every((a) => checked.has(a.email));

  const toggle = (email: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });

  async function load(target?: string) {
    const email = target ?? selected;
    if (!email) return;
    try {
      const result = await actions.fetchBilling.mutateAsync(email);
      if (result.awaiting_hsa2) {
        setNotice(result.message ?? "正在登录，等待验证码");
        return;
      }
      if (result.ok && result.info) {
        setNotice("");
        setInfo(result.info);
        setForm(toForm(result.info));
      }
    } catch {
      /* toast already raised */
    }
  }

  const set = <K extends keyof BillingForm>(key: K, value: BillingForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const mergeFields = (fields: Record<string, string>) =>
    setForm((prev) => ({
      ...prev,
      first_name: fields.first_name ?? prev.first_name,
      last_name: fields.last_name ?? prev.last_name,
      phone: fields.phone ?? prev.phone,
      street: fields.street ?? prev.street,
      street2: fields.street2 ?? prev.street2,
      city: fields.city ?? prev.city,
      state: fields.state ?? prev.state,
      postal_code: fields.postal_code ?? prev.postal_code,
      country_code: fields.country_code ?? prev.country_code,
      card_number: fields.card_number ?? prev.card_number,
      card_expiry: fields.card_expiry ?? prev.card_expiry,
    }));

  /** Paste anywhere while a card is on screen → parse it into the form. */
  useEffect(() => {
    if (!api) return;

    const onPaste = async (event: ClipboardEvent) => {
      if (!selected) return;
      const target = event.target as HTMLElement | null;
      // Inside a field the browser's own paste is what the person wants.
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (addOpen || bulkOpen || pasteOpen || confirmRemove) return;

      const text = event.clipboardData?.getData("text/plain")?.trim();
      if (!text || !text.includes("\n") && text.length < 12) return;

      event.preventDefault();
      try {
        const result = await api.parsePaste(text);
        // Silent on success: the form itself is the feedback.
        if (!Object.keys(result.fields).length) return;
        mergeFields(result.fields);
      } catch (err) {
        push({ kind: "error", title: "粘贴解析失败", detail: String(err) });
      }
    };

    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, selected, addOpen, bulkOpen, pasteOpen, confirmRemove]);

  const pending = actions.fetchBilling.isPending;
  // Ticked rows win; with nothing ticked the row open in the peek panel is the
  // target, so a single account never needs a checkbox first.
  const targets = checked.size ? [...checked] : selected ? [selected] : [];

  return (
    <div className="ws">
      <div className="ws__head">
        <div>
          <h1>账号</h1>
          <p>
            {accounts.length} 个账号 · {accounts.filter((a) => a.has_card).length} 张已绑卡
          </p>
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

      <div className="ws__body">
        <div className="ws__list">
          {isLoading && !data ? (
            <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
              {Array.from({ length: 7 }).map((_, i) => (
                <Skeleton key={i} height={40} />
              ))}
            </div>
          ) : isError ? (
            <Empty icon={Users} title="无法读取账号" action={<Button onClick={() => void refetch()}>重试</Button>}>
              {error instanceof Error ? error.message : "后端未连接"}
            </Empty>
          ) : filtered.length === 0 ? (
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
            <ul className="ws-rows">
              {filtered.map((account) => {
                const tone = statusTone(account);
                return (
                  <li
                    key={account.email}
                    className="ws-row"
                    data-active={selected === account.email}
                    data-checked={checked.has(account.email)}
                    onClick={() => setSelected(account.email === selected ? null : account.email)}
                  >
                    <span className="ws-row__check" onClick={(e) => e.stopPropagation()}>
                      <Checkbox on={checked.has(account.email)} onChange={() => toggle(account.email)} />
                    </span>
                    <span className="avatar">{account.email.slice(0, 2).toUpperCase()}</span>
                    <span className="ws-row__text">
                      <span className="ws-row__email">{account.email}</span>
                      <span className="ws-row__meta">
                        {account.note || (account.has_password ? "已保存密码" : "无密码")}
                      </span>
                    </span>
                    <span className="ws-row__badges">
                      {account.billing_checked && account.has_card ? (
                        <Badge tone="card">•••• {account.card_suffix || "已绑"}</Badge>
                      ) : null}
                      <Badge tone={tone.tone} dot pulse={tone.tone === "online"}>
                        {tone.label}
                      </Badge>
                    </span>
                    <span className="ws-row__time">{relativeTime(account.last_login)}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <aside className="ws__peek" data-open={Boolean(current)}>
          {current ? (
            <>
              <div className="peek__head">
                <div>
                  <strong>{current.email}</strong>
                  <span className="dim tiny">
                    {current.status === "online" ? "会话在线" : "会话已失效"}
                  </span>
                </div>
                <Button
                  icon={WifiOff}
                  variant="ghost"
                  title="检测这个账号的会话"
                  disabled={actions.checkSessions.isPending}
                  onClick={() => actions.checkSessions.mutate([current.email])}
                >
                  检测
                </Button>
                <Button
                  icon={LogIn}
                  variant="ghost"
                  title="重新登录这个账号"
                  disabled={actions.reloginBatch.isPending}
                  onClick={() => actions.reloginBatch.mutate([current.email])}
                >
                  重登
                </Button>
                <button className="btn btn--ghost btn--icon" onClick={() => setSelected(null)} title="关闭">
                  <X />
                </button>
              </div>

              {!info && !pending ? (
                <div className="peek__veil">
                  <ShieldOff style={{ width: 20, color: "var(--amber)" }} />
                  <strong>{notice || "还没有读取账单"}</strong>
                  <span>
                    {notice ? "验证码输入后会自动继续" : "点击下方按钮从 Apple 获取这个账号的账单"}
                  </span>
                  <Button icon={RefreshCw} variant="primary" onClick={() => void load()}>
                    获取账单信息
                  </Button>
                </div>
              ) : (
                <div className="peek__scroll">
                  {pending ? (
                    <div className="peek__veil">
                      <Loader2 className="spin" style={{ width: 18, color: "var(--amber)" }} />
                      <strong>正在读取…</strong>
                    </div>
                  ) : null}

                  {info ? (
                    <>
                      <div className="peek__actions">
                        <Button icon={RefreshCw} variant="ghost" onClick={() => void load()} disabled={pending}>
                          重新读取
                        </Button>
                        <Button
                          icon={ShieldOff}
                          variant="danger"
                          disabled={!info.has_card || actions.removeBilling.isPending}
                          onClick={() => setConfirmRemove(true)}
                        >
                          移除
                        </Button>
                      </div>

                      {/* Collapsed by default so the form keeps the space. */}
                      <details className="peek__card">
                        <summary>
                          <ChevronRight />
                          {info.has_card
                            ? cardSummary(info)
                            : "无付款方式"}
                        </summary>
                        <div className="peek__card-body">
                          <CreditCard
                            empty={!info.has_card}
                            company="Apple Account"
                            cardNumber={`•••• •••• •••• ${info.card_suffix || "••••"}`}
                            cardHolder={[info.first_name, info.last_name].filter(Boolean).join(" ")}
                            cardExpiration={info.expiry || "MM/YY"}
                            type="gray-dark"
                          />
                        </div>
                      </details>

                      <Panel
                        title="账单信息"
                        actions={
                          <Button
                            icon={Sparkles}
                            variant="ghost"
                            title="清空表单"
                            onClick={() => setForm({ ...EMPTY })}
                          >
                            重置
                          </Button>
                        }
                      >
                        <div className="billing__form">
                          <div className="billing__section-title">付款方式</div>
                          <div className="grid-2">
                            <Field label="卡号">
                              <div className="row">
                                <input
                                  inputMode="numeric"
                                  placeholder="4111 1111 1111 1111"
                                  value={form.card_number}
                                  onChange={(event) => set("card_number", event.target.value)}
                                />
                                <Button
                                  icon={Eye}
                                  variant="ghost"
                                  title={reveal ? "隐藏" : "显示"}
                                  onClick={() => setReveal((v) => !v)}
                                />
                              </div>
                            </Field>
                            <Field label="有效期" hint="MM/YY">
                              <input
                                placeholder="03/27"
                                value={form.card_expiry}
                                onChange={(event) => set("card_expiry", event.target.value)}
                              />
                            </Field>
                          </div>

                          <div className="billing__section-title">联系信息</div>
                          <div className="grid-3">
                            <Field label="名字">
                              <input value={form.first_name} onChange={(e) => set("first_name", e.target.value)} />
                            </Field>
                            <Field label="姓氏">
                              <input value={form.last_name} onChange={(e) => set("last_name", e.target.value)} />
                            </Field>
                            <Field label="电话">
                              <input value={form.phone} onChange={(e) => set("phone", e.target.value)} />
                            </Field>
                          </div>

                          <div className="billing__section-title">账单地址</div>
                          <div className="grid-2">
                            <Field label="国家">
                              <select
                                value={form.country_code}
                                onChange={(e) => set("country_code", e.target.value)}
                              >
                                {COUNTRIES.map((c) => (
                                  <option key={c.code} value={c.code}>
                                    {c.label} ({c.code})
                                  </option>
                                ))}
                              </select>
                            </Field>
                            <Field label="州 / 省">
                              <input value={form.state} onChange={(e) => set("state", e.target.value)} />
                            </Field>
                            <Field label="街道" span={2}>
                              <input value={form.street} onChange={(e) => set("street", e.target.value)} />
                            </Field>
                            <Field label="城市">
                              <input value={form.city} onChange={(e) => set("city", e.target.value)} />
                            </Field>
                          </div>
                          <div className="grid-2">
                            <Field label="公寓（可选）">
                              <input value={form.street2} onChange={(e) => set("street2", e.target.value)} />
                            </Field>
                            <Field label="邮编">
                              <input value={form.postal_code} onChange={(e) => set("postal_code", e.target.value)} />
                            </Field>
                          </div>
                        </div>
                      </Panel>
                    </>
                  ) : null}
                </div>
              )}
            </>
          ) : (
            <div className="peek__veil">
              <Users style={{ width: 20, color: "var(--text-dim)" }} />
              <strong>选择一个账号</strong>
              <span>账单会显示在这里</span>
            </div>
          )}
        </aside>
      </div>

      {/* Bottom bar: every action lives here, never in the header. */}
      <div className="ws__bar">
        <button
          className="ws__all"
          onClick={() =>
            setChecked(allChecked ? new Set() : new Set(filtered.map((a) => a.email)))
          }
        >
          <CheckSquare />
          {allChecked ? "取消全选" : "全选"}
        </button>
        {targets.length > 0 ? (
          <span className="dim tiny">
            {checked.size ? "已选" : "当前"} <b>{targets.length}</b> 个
          </span>
        ) : null}

        <div className="ws__bar-spacer" />

        {targets.length > 1 ? (
          <>
            <Button
              icon={WifiOff}
              variant="ghost"
              onClick={() => actions.checkSessions.mutate(targets)}
              disabled={actions.checkSessions.isPending}
            >
              批量检测 ({targets.length})
            </Button>
            <Button
              icon={LogIn}
              variant="ghost"
              onClick={() => actions.reloginBatch.mutate(targets)}
              disabled={actions.reloginBatch.isPending}
            >
              批量重登 ({targets.length})
            </Button>
          </>
        ) : null}
        <Button icon={Upload} variant="ghost" onClick={() => setBulkOpen(true)}>
          批量导入
        </Button>
        <Button
          icon={ClipboardPaste}
          variant="ghost"
          disabled={!current}
          onClick={() => setPasteOpen(true)}
        >
          粘贴识别
        </Button>
        <Button
          icon={Save}
          variant="primary"
          disabled={!current || actions.saveBilling.isPending || !form.card_number || !form.card_expiry}
          onClick={() => {
            if (!selected) return;
            const payload = { ...form, card_number: form.card_number.replace(/[^0-9]/g, "") };
            if (payload.card_number.length < 12) {
              push({ kind: "error", title: "卡号长度不对", detail: "至少 12 位" });
              return;
            }
            const target = selected;
            actions.saveBilling.mutate(
              { email: target, form: payload },
              {
                // Show whatever the server re-read says, even on failure, so a
                // rejected write cannot sit there looking applied.
                onSuccess: (result) => {
                  if (!result.info) return;
                  setInfo(result.info);
                  setForm((prev) => ({ ...toForm(result.info as BillingInfo), card_number: prev.card_number }));
                },
              },
            );
          }}
        >
          保存账单
        </Button>
        <Button
          icon={Trash2}
          variant="ghost"
          disabled={!current}
          onClick={() => current && setConfirmDelete(current.email)}
        >
          删除
        </Button>
        <Button icon={Plus} variant="primary" onClick={() => setAddOpen(true)}>
          添加账号
        </Button>
      </div>

      <AddAccountDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSubmit={async (payload) => {
          setAddOpen(false);
          try {
            // Row first, login second — so the account exists even if 2FA is
            // abandoned, and a duplicate is caught before any request to Apple.
            await actions.create.mutateAsync(payload);
          } catch {
            return; // create() already raised the toast
          }
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
        email={hsa2Email ?? ""}
        reason={hsa2Reason}
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
      <PasteDialog
        open={pasteOpen}
        onClose={() => setPasteOpen(false)}
        onApply={mergeFields}
      />
      <ConfirmDialog
        open={Boolean(confirmDelete)}
        title="删除账号"
        description={`将移除 ${confirmDelete ?? ""} 及其本地会话。Apple ID 本身不受影响。`}
        confirmLabel="删除"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={async () => {
          if (confirmDelete) await actions.remove.mutateAsync(confirmDelete);
          if (confirmDelete === selected) setSelected(null);
          setConfirmDelete(null);
        }}
      />
      <ConfirmDialog
        open={confirmRemove}
        title="移除账单"
        description="将从该 Apple ID 上删除当前的付款方式（两步确认）。此操作不可撤销。"
        confirmLabel="移除"
        onCancel={() => setConfirmRemove(false)}
        onConfirm={async () => {
          if (selected) {
            const result = await actions.removeBilling.mutateAsync(selected);
            if (result.info) {
              setInfo(result.info);
              setForm(toForm(result.info));
            } else if (result.ok) {
              setInfo(null);
              setForm({ ...EMPTY });
            }
          }
          setConfirmRemove(false);
        }}
      />
    </div>
  );
}
