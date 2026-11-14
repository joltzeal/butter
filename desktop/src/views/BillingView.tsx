import { ClipboardPaste, CreditCard, Eye, Loader2, RefreshCw, Save, ShieldOff, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Account, BillingForm, BillingInfo } from "../api/client";
import { useAccountActions, useAccounts } from "../hooks/useAccounts";
import { useRealtime } from "../hooks/useRealtime";
import { Badge, Button, Empty, Field, Panel } from "../components/ui";
import { PasteDialog } from "./PasteDialog";
import { ConfirmDialog } from "./ConfirmDialog";

const EMPTY: BillingForm = {
  card_number: "",
  card_expiry: "",
  first_name: "",
  last_name: "",
  street: "",
  street2: "",
  city: "",
  state: "",
  postal_code: "",
  country_code: "US",
  phone: "",
  remove_only: false,
};

const COUNTRIES = [
  { code: "US", label: "美国" },
  { code: "GB", label: "英国" },
  { code: "CA", label: "加拿大" },
  { code: "AU", label: "澳大利亚" },
];

function toForm(info: BillingInfo | null | undefined): BillingForm {
  if (!info) return { ...EMPTY };
  return {
    card_number: info.card_number ? `•••• ${info.card_suffix}` : "",
    card_expiry: info.expiry,
    first_name: info.first_name,
    last_name: info.last_name,
    street: info.street,
    street2: info.street2,
    city: info.city,
    state: info.state,
    postal_code: info.postal_code,
    country_code: (info.country_code || "US").toUpperCase(),
    phone: info.phone,
    remove_only: false,
  };
}

export function BillingView({ initialEmail }: { initialEmail?: string | null }) {
  const { data } = useAccounts();
  const actions = useAccountActions();
  const { lastEvent } = useRealtime();

  const accounts = data ?? [];
  const [email, setEmail] = useState<string | null>(initialEmail ?? accounts[0]?.email ?? null);
  const [form, setForm] = useState<BillingForm>({ ...EMPTY });
  const [info, setInfo] = useState<BillingInfo | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [reveal, setReveal] = useState(false);
  const current = useMemo(() => accounts.find((a) => a.email === email) ?? null, [accounts, email]);

  useEffect(() => {
    if (!email && accounts.length) setEmail(accounts[0].email);
  }, [accounts, email]);

  // Never fetch on selection. A cached copy paints immediately; otherwise the
  // operator presses "获取账单信息", which keeps surprise requests off Apple.
  useEffect(() => {
    if (!current) return;
    const cached = current.billing_cache;
    if (cached && Object.keys(cached).length) {
      setInfo(cached);
      setForm(toForm(cached));
    } else {
      setInfo(null);
      setForm({ ...EMPTY });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.email, current?.billing_cache]);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.event === "billing.fetched" && lastEvent.payload.email === email) {
      const next = lastEvent.payload.info as BillingInfo;
      setInfo(next);
      setForm(toForm(next));
    }
  }, [lastEvent, email]);

  async function load() {
    if (!email) return;
    try {
      const result = await actions.fetchBilling.mutateAsync(email);
      if (result.ok && result.info) {
        setInfo(result.info);
        setForm(toForm(result.info));
      }
    } catch {
      /* toast already raised */
    }
  }

  const set = <K extends keyof BillingForm>(key: K, value: BillingForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  if (!email) {
    return (
      <div className="placeholder-view">
        <Empty icon={CreditCard} title="选择账号以查看账单">
          先在「账号」里添加 Apple ID，再回到这里读取付款方式。
        </Empty>
      </div>
    );
  }

  return (
    <div className="billing">
      <aside className="billing__picker">
        <div className="billing__picker-head">账号 · {accounts.length}</div>
        <div className="billing__picker-list">
          {accounts.map((account: Account) => (
            <button
              key={account.email}
              className="pick"
              data-active={account.email === email}
              onClick={() => setEmail(account.email)}
            >
              <span className="pick__email">{account.email}</span>
              <span className="pick__badge">
                {account.has_card ? <Badge tone="card">卡</Badge> : <Badge tone="noc">—</Badge>}
              </span>
            </button>
          ))}
        </div>
      </aside>

      <div className="billing__main" style={{ position: "relative" }}>
        {!info && !actions.fetchBilling.isPending ? (
          <div className="billing__veil">
            <div className="billing__veil-card">
              <CreditCard style={{ width: 22, color: "var(--amber)" }} />
              <strong>还没有读取这个账号的账单</strong>
              <span>点击下方按钮从 Apple 获取最新的账单与付款方式</span>
              <Button icon={RefreshCw} variant="primary" onClick={() => void load()}>
                获取账单信息
              </Button>
            </div>
          </div>
        ) : null}
        {actions.fetchBilling.isPending ? (
          <div className="billing__veil">
            <div className="billing__veil-card">
              <Loader2 className="spin" style={{ width: 20, color: "var(--amber)" }} />
              <strong>正在读取账单…</strong>
              <span>通常需要 1–3 秒</span>
            </div>
          </div>
        ) : null}
        <div className="billing__header">
          <div>
            <h1>{email}</h1>
            <div className="dim tiny">
              {current?.logged_in ? "会话在线" : "会话可能已过期"} ·{" "}
              {info?.display_card_type || (info?.has_card ? "已绑卡" : "无账单")}
            </div>
          </div>
          <div className="page__actions">
            <Button
              icon={RefreshCw}
              onClick={() => void load()}
              disabled={actions.fetchBilling.isPending}
            >
              {actions.fetchBilling.isPending ? "读取中…" : "读取账单"}
            </Button>
            <Button icon={ClipboardPaste} variant="ghost" onClick={() => setPasteOpen(true)}>
              粘贴识别
            </Button>
            <Button
              icon={ShieldOff}
              variant="danger"
              disabled={!info?.has_card || actions.removeBilling.isPending}
              onClick={() => setConfirmRemove(true)}
            >
              移除账单
            </Button>
          </div>
        </div>

        <div className="billing__grid">
          <div className="stack">
            <div className="card-visual" data-empty={!info?.has_card}>
              <div className="card-visual__top">
                <span className="card-visual__brand">Apple Account</span>
                <span className="card-visual__type">{info?.display_card_type || "NO CARD"}</span>
              </div>
              <div className="card-visual__number">
                {info?.has_card ? `•••• •••• •••• ${info.card_suffix || "••••"}` : "•••• •••• •••• ••••"}
              </div>
              <div className="card-visual__bottom">
                <span className="card-visual__holder">
                  {[info?.first_name, info?.last_name].filter(Boolean).join(" ") || "—"}
                </span>
                <span>{info?.expiry || "MM/YY"}</span>
              </div>
            </div>

            <div className="billing__status">
              <strong>{info?.has_card ? "已绑定付款方式" : "尚未绑定付款方式"}</strong>
              <span>
                {[info?.street, info?.city, info?.state, info?.postal_code, info?.country_code]
                  .filter(Boolean)
                  .join(" · ") || "读取后展示当前账单地址"}
              </span>
              {actions.saveBilling.isPending ? (
                <span className="row" style={{ color: "var(--amber)" }}>
                  <Loader2 className="spin" style={{ width: 12, height: 12 }} /> 正在提交…
                </span>
              ) : null}
            </div>
          </div>

          <Panel
            title="账单信息"
            subtitle="留空的字段会按所选国家自动补全"
            actions={
              <Button
                icon={Sparkles}
                variant="ghost"
                title="清空表单"
                onClick={() => {
                  setInfo(null);
                  setForm({ ...EMPTY });
                }}
              >
                重置
              </Button>
            }
            footer={
              <>
                <span className="dim tiny">卡号在本地加密后才提交</span>
                <div style={{ marginLeft: "auto" }} className="row">
                  <Button
                    icon={Save}
                    variant="primary"
                    disabled={actions.saveBilling.isPending || !form.card_number || !form.card_expiry}
                    onClick={() => {
                      const payload: BillingForm = {
                        ...form,
                        card_number: form.card_number.replace(/[^0-9]/g, ""),
                      };
                      if (payload.card_number.length < 12) {
                        setForm((prev) => ({ ...prev, card_number: "" }));
                        return;
                      }
                      actions.saveBilling.mutate({ email, form: payload });
                    }}
                  >
                    保存账单
                  </Button>
                </div>
              </>
            }
          >
            <div className="billing__form">
              <div className="billing__section-title">付款方式</div>
              <div className="grid-2">
                <Field label="卡号" hint="15 或 16 位">
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
                  <input value={form.first_name} onChange={(event) => set("first_name", event.target.value)} />
                </Field>
                <Field label="姓氏">
                  <input value={form.last_name} onChange={(event) => set("last_name", event.target.value)} />
                </Field>
                <Field label="电话" hint="10 位数字">
                  <input value={form.phone} onChange={(event) => set("phone", event.target.value)} />
                </Field>
              </div>

              <div className="billing__section-title">账单地址</div>
              <div className="grid-2">
                <Field label="国家">
                  <select value={form.country_code} onChange={(event) => set("country_code", event.target.value)}>
                    {COUNTRIES.map((country) => (
                      <option key={country.code} value={country.code}>
                        {country.label} ({country.code})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="州 / 省">
                  <input value={form.state} onChange={(event) => set("state", event.target.value)} />
                </Field>
                <Field label="街道" span={2}>
                  <input value={form.street} onChange={(event) => set("street", event.target.value)} />
                </Field>
                <Field label="公寓（可选）">
                  <input value={form.street2} onChange={(event) => set("street2", event.target.value)} />
                </Field>
                <Field label="城市">
                  <input value={form.city} onChange={(event) => set("city", event.target.value)} />
                </Field>
                <Field label="邮编">
                  <input value={form.postal_code} onChange={(event) => set("postal_code", event.target.value)} />
                </Field>
              </div>
            </div>
          </Panel>
        </div>
      </div>

      <PasteDialog
        open={pasteOpen}
        onClose={() => setPasteOpen(false)}
        onApply={(fields) =>
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
          }))
        }
      />

      <ConfirmDialog
        open={confirmRemove}
        title="移除账单"
        description="将从该 Apple ID 上删除当前的付款方式（两步确认）。此操作不可撤销。"
        confirmLabel="移除"
        onCancel={() => setConfirmRemove(false)}
        onConfirm={async () => {
          await actions.removeBilling.mutateAsync(email);
          setConfirmRemove(false);
          setInfo(null);
        }}
      />
    </div>
  );
}
