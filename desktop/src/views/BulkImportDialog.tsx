import { ClipboardPaste, Upload, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { BulkResult } from "../api/client";
import { Button, Field } from "../components/ui";

/** Mirrors the server rule in `core/bulk_import.py`. */
const SEP = "----";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/;

const PLACEHOLDER = `apple_id@example.com${SEP}密码${SEP}https://…/getcode?id=123
第二个@example.com${SEP}密码${SEP}https://…/getcode?id=456`;

interface LineCheck {
  line: number;
  text: string;
  reason: string | null;
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/** Client-side pre-check so the operator sees problems before submitting. */
function check(text: string): LineCheck[] {
  const seen = new Set<string>();
  const out: LineCheck[] = [];
  text.split("\n").forEach((raw, index) => {
    const line = raw.trim();
    if (!line || line.startsWith("#")) return;
    const fields = line.split(SEP).map((part) => part.trim());
    let reason: string | null = null;
    if (fields.length !== 3) {
      reason = `需要 3 段，实际 ${fields.length} 段`;
    } else if (!EMAIL_RE.test(fields[0])) {
      reason = "邮箱格式不正确";
    } else if (!fields[1]) {
      reason = "密码为空";
    } else if (!isValidUrl(fields[2])) {
      reason = "2FA 链接必须是 http(s) URL";
    } else if (seen.has(fields[0].toLowerCase())) {
      reason = "同一批中重复";
    } else {
      seen.add(fields[0].toLowerCase());
    }
    out.push({ line: index + 1, text: line, reason });
  });
  return out;
}

export function BulkImportDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (text: string) => Promise<BulkResult>;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BulkResult | null>(null);

  const lines = useMemo(() => check(text), [text]);
  const bad = lines.filter((l) => l.reason);
  const good = lines.length - bad.length;

  if (!open) return null;

  const canSubmit = good > 0 && bad.length === 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      const value = await onSubmit(text);
      setResult(value);
      if (value.ok) {
        setText("");
        // Keep the summary visible; the caller closes on demand.
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal__head">
          <Upload style={{ width: 16, color: "var(--amber)" }} />
          <div>
            <h2>批量导入</h2>
            <p>每行一个账号，格式固定为 邮箱{SEP}密码{SEP}2FA 链接</p>
          </div>
          <button className="modal__close" onClick={onClose}>
            <X />
          </button>
        </header>

        <div className="modal__body">
          <Field
            label="账号列表"
            hint={`${good} 行有效${bad.length ? ` · ${bad.length} 行有问题` : ""}`}
          >
            <textarea
              rows={9}
              spellCheck={false}
              value={text}
              placeholder={PLACEHOLDER}
              style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.6 }}
              onChange={(event) => {
                setText(event.target.value);
                setResult(null);
              }}
            />
          </Field>

          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <Button
              icon={ClipboardPaste}
              variant="ghost"
              onClick={async () => {
                try {
                  const value = await navigator.clipboard.readText();
                  if (value) {
                    setText(value);
                    setResult(null);
                  }
                } catch {
                  /* clipboard denied — the operator can paste manually */
                }
              }}
            >
              从剪贴板粘贴
            </Button>
          </div>

          {bad.length ? (
            <div
              style={{
                marginTop: 10,
                padding: "8px 10px",
                borderRadius: 8,
                background: "color-mix(in srgb, var(--danger) 10%, transparent)",
                border: "1px solid color-mix(in srgb, var(--danger) 35%, transparent)",
                maxHeight: 140,
                overflow: "auto",
              }}
            >
              {bad.slice(0, 12).map((item) => (
                <div key={item.line} className="tiny" style={{ lineHeight: 1.7 }}>
                  <b style={{ color: "var(--danger)" }}>第 {item.line} 行</b>：{item.reason}
                </div>
              ))}
              {bad.length > 12 ? (
                <div className="tiny dim">…还有 {bad.length - 12} 行</div>
              ) : null}
            </div>
          ) : null}

          {result ? (
            <div
              style={{
                marginTop: 10,
                padding: "8px 10px",
                borderRadius: 8,
                background: result.ok
                  ? "color-mix(in srgb, var(--ok) 10%, transparent)"
                  : "color-mix(in srgb, var(--danger) 10%, transparent)",
                border: `1px solid ${
                  result.ok
                    ? "color-mix(in srgb, var(--ok) 35%, transparent)"
                    : "color-mix(in srgb, var(--danger) 35%, transparent)"
                }`,
              }}
            >
              <div className="tiny">{result.message}</div>
            </div>
          ) : null}
        </div>

        <footer className="modal__foot">
          <Button variant="ghost" onClick={onClose}>
            {result?.ok ? "完成" : "取消"}
          </Button>
          <Button variant="primary" disabled={!canSubmit} onClick={() => void submit()}>
            {busy ? `导入中… (${good})` : `导入 ${good} 个账号`}
          </Button>
        </footer>
      </div>
    </div>
  );
}
