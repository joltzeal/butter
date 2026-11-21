import {
  CheckSquare,
  ChevronRight,
  ClipboardPaste,
  LogIn,
  LogOut,
  Plus,
  RefreshCw,
  Save,
  Pencil,
  Search,
  ShieldOff,
  RotateCcw,
  Trash2,
  Upload,
  UserPlus,
  Users,
  WifiOff,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import { AccountEditDialog } from "./AccountEditDialog";
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
    // Apple never returns the PAN, so the card has to be retyped on any save.
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

const sameForm = (a: BillingForm, b: BillingForm) =>
  (Object.keys(EMPTY) as Array<keyof BillingForm>).every((key) => a[key] === b[key]);

/** "VISA **** 4141 12/34" — the collapsed stand-in for the card art. */
function cardSummary(info: BillingInfo): string {
  const brand = (info.display_card_type || "CARD").toUpperCase();
  const suffix = info.card_suffix || "••••";
  // Apple answers "4/27"; the summary reads better zero-padded ("04/27").
  const expiry = (info.expiry || "").replace(/^(\d)\//, "0$1/");
  return [brand, `**** ${suffix}`, expiry].filter(Boolean).join(" ");
}

/** "3/29" → "03/29"; a partial entry is left alone. */
function padExpiry(value: string): string {
  return value.replace(/^(\d)\//, "0$1/");
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
  const [confirmDelete, setConfirmDelete] = useState<string[] | null>(null);
  const [hsa2Email, setHsa2Email] = useState<string | null>(null);
  const [hsa2Reason, setHsa2Reason] = useState("");
  const [form, setForm] = useState<BillingForm>({ ...EMPTY });
  const [baseline, setBaseline] = useState<BillingForm>({ ...EMPTY });
  const [info, setInfo] = useState<BillingInfo | null>(null);
  const [notice, setNotice] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [cardMissing, setCardMissing] = useState(false);

  const cardRef = useRef<HTMLInputElement>(null);
  // Cancelled prompts must stay cancelled: the list keeps reporting
  // awaiting_hsa2 for a while and used to reopen the dialog on the next poll.
  const dismissed = useRef(new Set<string>());
  const readRef = useRef<AbortController | null>(null);
  const dirty = !sameForm(form, baseline);

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

  const resetPane = useCallback(() => {
    setInfo(null);
    setForm({ ...EMPTY });
    setBaseline({ ...EMPTY });
    setNotice("");
    setCardMissing(false);
  }, []);

  // A read in flight belongs to the account it started on; switching used to
  // land its answer in the next account's form.
  const loadInto = (next: BillingInfo) => {
    const fields = toForm(next);
    setInfo(next);
    setForm(fields);
    setBaseline(fields);
    setNotice("");
  };

  useEffect(() => {
    setChecked((prev) => {
      const alive = new Set(accounts.map((a) => a.email));
      const next = new Set([...prev].filter((email) => alive.has(email)));
      return next.size === prev.size ? prev : next;
    });
    if (selected && !accounts.some((a) => a.email === selected)) setSelected(null);
  }, [accounts, selected]);

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
        dismissed.current.delete(email);
        setHsa2Email(email);
        setHsa2Reason(String(lastEvent.payload.reason ?? ""));
      }
    }
  }, [lastEvent]);

  useEffect(() => {
    for (const email of [...dismissed.current]) {
      if (!accounts.some((a) => a.email === email && a.awaiting_hsa2)) dismissed.current.delete(email);
    }
    if (hsa2Email) return;
    const waiting = accounts.find((a) => a.awaiting_hsa2 && !dismissed.current.has(a.email));
    if (waiting) setHsa2Email(waiting.email);
  }, [accounts, hsa2Email]);

  useEffect(() => {
    if (!lastEvent || !selected) return;
    if (lastEvent.event === "billing.fetched" && lastEvent.payload.email === selected) {
      const next = lastEvent.payload.info as BillingInfo;
      if (next) loadInto(next);
    }
  }, [lastEvent, selected]);

  useEffect(() => () => readRef.current?.abort(), []);

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const pick = (email: string) => {
    if (email === selected) {
      if (dirty && !window.confirm("当前账单有未保存的改动，收起会丢弃。继续？")) return;
      setSelected(null);
      resetPane();
      return;
    }
    if (dirty && !window.confirm("当前账单有未保存的改动，切换会丢弃。继续？")) return;
    readRef.current?.abort();
    setSelected(email);
    resetPane();
  };

  const allChecked = filtered.length > 0 && filtered.every((a) => checked.has(a.email));

  const toggle = (email: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });

  const load = async () => {
    const email = selected;
    if (!email) return;
    readRef.current?.abort();
    const controller = new AbortController();
    readRef.current = controller;
    try {
      const result = await actions.fetchBilling.mutateAsync({ email, signal: controller.signal });
      if (selectedRef.current !== email) return;
      if (result.awaiting_hsa2) {
        setNotice(result.message ?? "正在登录，等待验证码");
        return;
      }
      if (result.ok && result.info) loadInto(result.info);
      else if (result.message) setNotice(result.message);
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      /* toast already raised */
    }
  };

  const set = <K extends keyof BillingForm>(key: K, value: BillingForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const mergeFields = useCallback((fields: Record<string, string>) => {
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
  }, []);

  /** Paste anywhere on the screen (outside a field) parses a card block. */
  useEffect(() => {
    if (!api) return;

    const onPaste = async (event: ClipboardEvent) => {
      if (!selected) return;
      const target = event.target as HTMLElement | null;
      // Inside a field the browser's own paste is what the person wants.
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (addOpen || bulkOpen || pasteOpen || editOpen || confirmRemove || confirmDelete || hsa2Email) return;

      const text = event.clipboardData?.getData("text/plain")?.trim();
      if (!text || (!text.includes("\n") && text.length < 12)) return;

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
  }, [
    api,
    selected,
    addOpen,
    bulkOpen,
    pasteOpen,
    editOpen,
    confirmRemove,
    confirmDelete,
    hsa2Email,
    mergeFields,
    push,
  ]);

  const pending = actions.fetchBilling.isPending;
  // Ticked rows win for the destructive/batch actions; the save button always
  // talks about the row on screen, so it says so when a selection exists.
  const targets = checked.size ? [...checked] : selected ? [selected] : [];
  const saveLabel = checked.size ? `保存当前 · 已选 ${checked.size}` : "保存账单";

  const save = () => {
    if (!selected) return;
    const digits = form.card_number.replace(/[^0-9]/g, "");
    if (!form.card_expiry.trim()) {
      push({ kind: "error", title: "缺少有效期", detail: "请填写 MM/YY" });
      return;
    }
    if (digits.length < 12) {
      // The card has to be retyped every time: Apple does not return the PAN.
      setCardMissing(true);
      cardRef.current?.focus();
      push({
        kind: "error",
        title: digits ? "卡号不完整" : "需要重填卡号",
        detail: digits ? "至少 12 位" : "Apple 不回传完整卡号，保存前请重填一次",
      });
      return;
    }
    const target = selected;
    actions.saveBilling.mutate(
      { email: target, form: { ...form, card_number: digits } },
      {
        // Show whatever the server re-read says, even on failure, so a rejected
        // write cannot sit there looking applied.
        onSuccess: (result) => {
          setCardMissing(false);
          if (!result.info) return;
          // Keep the typed card when the write was rejected: retrying is then
          // one click, and the cleared field used to force a full retype.
          const fields = { ...toForm(result.info), card_number: result.ok ? "" : form.card_number };
          setInfo(result.info);
          setForm(fields);
          setBaseline(fields);
        },
      },
    );
  };

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
            type="search"
            name="account-search"
            aria-label="搜索邮箱或备注"
            placeholder="搜索邮箱或备注…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <div className="ws__body">
        <div className="ws__list">
          {isLoading && !data ? (
            <div className="ws__list-skeleton">
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
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected === account.email}
                    data-active={selected === account.email}
                    data-checked={checked.has(account.email)}
                    onClick={() => pick(account.email)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        pick(account.email);
                      }
                    }}
                  >
                    <span className="ws-row__check">
                      <Checkbox
                        on={checked.has(account.email)}
                        onChange={() => toggle(account.email)}
                        label={`选择 ${account.email}`}
                      />
                    </span>
                    <span className="avatar">{(account.email.split("@")[0] || "?").slice(0, 2).toUpperCase()}</span>
                    <span className="ws-row__text">
                      <span className="ws-row__email">{account.email}</span>
                      <span className="ws-row__meta">
                        {account.note ? <span className="ws-row__note">{account.note}</span> : null}
                        <span className={account.password_plain ? "ws-row__pass" : "ws-row__pass dim"}>
                          {account.password_plain || "无密码"}
                        </span>
                      </span>
                    </span>
                    <span className="ws-row__badges">
                      {account.billing_checked && account.has_card ? (
                        <Badge tone="card">{account.card_suffix || "已绑卡"}</Badge>
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
                <div className="peek__id">
                  <strong>{current.email}</strong>
                  <span className="dim tiny mono">
                    {current.password_plain || "无密码"} · {current.status === "online" ? "会话在线" : "会话已失效"}
                  </span>
                </div>
                <div className="peek__tools">
                  <Button
                    icon={WifiOff}
                    variant={["ghost", "sm"]}
                    disabled={actions.checkSessions.isPending}
                    onClick={() => actions.checkSessions.mutate([current.email])}
                  >
                    检测
                  </Button>
                  <Button
                    icon={LogIn}
                    variant={["ghost", "sm"]}
                    disabled={actions.reloginBatch.isPending}
                    onClick={() => actions.reloginBatch.mutate([current.email])}
                  >
                    登录
                  </Button>
                  <Button
                    icon={LogOut}
                    variant={["ghost", "sm"]}
                    disabled={!current.logged_in && !current.has_des}
                    loading={actions.logout.isPending}
                    title={current.logged_in || current.has_des ? "清除本地会话" : "当前没有会话"}
                    onClick={() => {
                      actions.logout.mutate(current.email, {
                        onSuccess: (result) => {
                          if (result.ok) resetPane();
                        },
                      });
                    }}
                  >
                    登出
                  </Button>
                  <Button
                    icon={Pencil}
                    variant={["ghost", "sm"]}
                    onClick={() => setEditOpen(true)}
                  >
                    编辑
                  </Button>
                  <Button
                    icon={X}
                    variant={["ghost", "sm"]}
                    title="收起账单面板（Esc）"
                    onClick={() => {
                      if (dirty && !window.confirm("当前账单有未保存的改动，收起会丢弃。继续？")) return;
                      readRef.current?.abort();
                      setSelected(null);
                      resetPane();
                    }}
                  >
                    收起
                  </Button>
                </div>
              </div>

              {!info && !pending ? (
                <div className="peek__veil">
                  <ShieldOff style={{ width: 20, color: "var(--amber)" }} />
                  <strong>{notice || "还没有读取账单"}</strong>
                  <span>
                    {notice ? "验证码输入后会自动继续" : "从 Apple 读取账单"}
                  </span>
                  <Button icon={RefreshCw} variant="primary" onClick={() => void load()}>
                    获取账单信息
                  </Button>
                </div>
              ) : (
                <div className="peek__scroll">
                  {pending ? (
                    <div className="peek__veil">
                      <RefreshCw className="spin" style={{ width: 18, color: "var(--amber)" }} />
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
                          {info.has_card ? cardSummary(info) : "无付款方式"}
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
                            icon={RotateCcw}
                            variant="ghost"
                            title="撤销未保存的改动"
                            disabled={!dirty}
                            onClick={() => {
                              setForm({ ...baseline });
                              setCardMissing(false);
                            }}
                          >
                            还原
                          </Button>
                        }
                      >
                        <div className="billing__form">
                          <div className="billing__section-title">付款方式</div>
                          <div className="grid-2">
                            <Field
                              label="卡号"
                              hint={
                                cardMissing
                                  ? "必填：Apple 不回传完整卡号"
                                  : info.has_card
                                    ? `已存尾号 ${info.card_suffix || "----"}，保存前重填`
                                    : undefined
                              }
                            >
                              <input
                                ref={cardRef}
                                name="card_number"
                                type="text"
                                autoComplete="cc-number"
                                inputMode="numeric"
                                spellCheck={false}
                                placeholder={info.has_card ? `重填卡号（尾号 ${info.card_suffix}）` : "4111 1111 1111 1111"}
                                aria-invalid={cardMissing || undefined}
                                value={form.card_number}
                                onChange={(event) => {
                                  setCardMissing(false);
                                  set("card_number", event.target.value);
                                }}
                              />
                            </Field>
                            <Field label="有效期" hint="MM/YY">
                              <input
                                name="card_expiry"
                                autoComplete="cc-exp"
                                placeholder="03/27"
                                value={form.card_expiry}
                                onChange={(event) => set("card_expiry", event.target.value)}
                                onBlur={(event) => set("card_expiry", padExpiry(event.target.value.trim()))}
                              />
                            </Field>
                          </div>

                          <div className="billing__section-title">联系信息</div>
                          <div className="grid-3">
                            <Field label="名字">
                              <input
                                name="first_name"
                                autoComplete="given-name"
                                value={form.first_name}
                                onChange={(e) => set("first_name", e.target.value)}
                              />
                            </Field>
                            <Field label="姓氏">
                              <input
                                name="last_name"
                                autoComplete="family-name"
                                value={form.last_name}
                                onChange={(e) => set("last_name", e.target.value)}
                              />
                            </Field>
                            <Field label="电话">
                              <input
                                name="phone"
                                autoComplete="tel"
                                value={form.phone}
                                onChange={(e) => set("phone", e.target.value)}
                              />
                            </Field>
                          </div>

                          <div className="billing__section-title">账单地址</div>
                          <div className="grid-2">
                            <Field label="国家">
                              <select
                                name="country_code"
                                autoComplete="country"
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
                              <input
                                name="state"
                                autoComplete="address-level1"
                                value={form.state}
                                onChange={(e) => set("state", e.target.value)}
                              />
                            </Field>
                            <Field label="街道" span={2}>
                              <input
                                name="street"
                                autoComplete="address-line1"
                                value={form.street}
                                onChange={(e) => set("street", e.target.value)}
                              />
                            </Field>
                            <Field label="城市">
                              <input
                                name="city"
                                autoComplete="address-level2"
                                value={form.city}
                                onChange={(e) => set("city", e.target.value)}
                              />
                            </Field>
                          </div>
                          <div className="grid-2">
                            <Field label="公寓（可选）">
                              <input
                                name="street2"
                                autoComplete="address-line2"
                                value={form.street2}
                                onChange={(e) => set("street2", e.target.value)}
                              />
                            </Field>
                            <Field label="邮编">
                              <input
                                name="postal_code"
                                autoComplete="postal-code"
                                value={form.postal_code}
                                onChange={(e) => set("postal_code", e.target.value)}
                              />
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
          onClick={() => setChecked(allChecked ? new Set() : new Set(filtered.map((a) => a.email)))}
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
              批量登录 ({targets.length})
            </Button>
          </>
        ) : null}
        <Button icon={Upload} variant="ghost" onClick={() => setBulkOpen(true)}>
          批量导入
        </Button>
        <Button icon={ClipboardPaste} variant="ghost" disabled={!current} onClick={() => setPasteOpen(true)}>
          粘贴识别
        </Button>
        <Button
          icon={Save}
          variant="primary"
          disabled={!current || actions.saveBilling.isPending}
          loading={actions.saveBilling.isPending}
          title={dirty ? "保存当前账号的账单" : "没有改动也要求重填卡号"}
          onClick={save}
        >
          {saveLabel}
        </Button>
        {/* One delete for both cases: ticked rows win, else the open account. */}
        <Button
          icon={Trash2}
          variant="ghost"
          disabled={targets.length === 0}
          title={targets.length ? "" : "选择账号后可用"}
          onClick={() => setConfirmDelete(targets)}
        >
          删除{targets.length > 1 ? ` (${targets.length})` : ""}
        </Button>
        <Button icon={Plus} variant="primary" onClick={() => setAddOpen(true)}>
          添加账号
        </Button>
      </div>

      <AccountEditDialog
        account={editOpen ? current : null}
        onClose={() => setEditOpen(false)}
        onRenamed={(email) => {
          setSelected(email);
          resetPane();
        }}
      />
      <AddAccountDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSubmit={async (payload) => {
          setAddOpen(false);
          // Save only. Logging in is a separate, deliberate step so a batch of
          // imports does not each fire a 2FA push.
          await actions.create.mutateAsync(payload).catch(() => {});
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
          if (hsa2Email) {
            dismissed.current.add(hsa2Email);
            void actions.hsa2.mutate({ email: hsa2Email, code: "" });
          }
          setHsa2Email(null);
          setHsa2Reason("");
        }}
        onSubmit={async (code) => {
          if (!hsa2Email) return false;
          try {
            const result = await actions.hsa2.mutateAsync({ email: hsa2Email, code });
            if (!result.accepted) return false;
            setHsa2Email(null);
            setHsa2Reason("");
            // The pending billing read continues on its own and paints the
            // result; only re-read when nothing is in flight (manual login).
            if (selected && !actions.fetchBilling.isPending) void load();
            return true;
          } catch {
            return false;
          }
        }}
      />
      <PasteDialog open={pasteOpen} onClose={() => setPasteOpen(false)} onApply={mergeFields} />
      <ConfirmDialog
        open={Boolean(confirmDelete?.length)}
        title={confirmDelete && confirmDelete.length > 1 ? `删除 ${confirmDelete.length} 个账号` : "删除账号"}
        description={
          confirmDelete && confirmDelete.length > 1
            ? "本地记录和会话会被删除，Apple ID 不受影响。"
            : `移除 ${confirmDelete?.[0] ?? ""} 及其本地会话。`
        }
        confirmLabel="删除"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={async () => {
          const batch = confirmDelete ?? [];
          let failed = 0;
          for (const email of batch) {
            try {
              await actions.remove.mutateAsync(email);
            } catch {
              failed += 1;
            }
          }
          setChecked((prev) => {
            const next = new Set(prev);
            batch.forEach((email) => next.delete(email));
            return next;
          });
          if (selected && batch.includes(selected)) {
            setSelected(null);
            resetPane();
          }
          return failed === 0;
        }}
      />
      <ConfirmDialog
        open={confirmRemove}
        title="移除账单"
        description="删除当前的付款方式，不可撤销。"
        confirmLabel="移除"
        onCancel={() => setConfirmRemove(false)}
        onConfirm={async () => {
          if (!selected) return false;
          try {
            const result = await actions.removeBilling.mutateAsync(selected);
            if (result.info) loadInto(result.info);
            else if (result.ok) resetPane();
            return result.ok;
          } catch {
            return false;
          }
        }}
      />
    </div>
  );
}
