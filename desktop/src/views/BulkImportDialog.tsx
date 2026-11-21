import { ClipboardPaste, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import type { BulkResult } from "../api/client";
import { Button, Field } from "../components/ui";
import { Dialog } from "../components/Dialog";

/** Mirrors the server rule in `core/bulk_import.py`. */
const SEP = "----";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/;

const PLACEHOLDER = `apple_id@example.com${SEP}密码${SEP}备注（可空）
第二个@example.com${SEP}密码${SEP}US 主号`;

interface LineCheck {
  line: number;
  text: string;
  reason: string | null;
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
  const [error, setError] = useState("");

  const lines = useMemo(() => check(text), [text]);
  const bad = lines.filter((l) => l.reason);
  const good = lines.length - bad.length;

  const canSubmit = good > 0 && bad.length === 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      const value = await onSubmit(text);
      setResult(value);
      if (value.ok) {
        setText("");
        // Keep the summary visible; the caller closes on demand.
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="批量导入"
      subtitle={`每行 邮箱${SEP}密码${SEP}备注`}
      icon={Upload}
      size="md"
      busy={busy}
      onSubmit={submit}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {result?.ok ? "完成" : "取消"}
          </Button>
          <Button variant="primary" type="submit" disabled={!canSubmit} loading={busy}>
            {busy ? `导入中… (${good})` : `导入 ${good} 个账号`}
          </Button>
        </>
      }
    >
      <Field label="账号列表" hint={`${good} 行有效${bad.length ? ` · ${bad.length} 行有问题` : ""}`}>
        <textarea
          name="bulk"
          autoFocus
          rows={9}
          spellCheck={false}
          className="paste-area paste-area--code"
          value={text}
          placeholder={PLACEHOLDER}
          onChange={(event) => {
            setText(event.target.value);
            setResult(null);
          }}
        />
      </Field>

      <div className="row">
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
        <div className="note note--danger tiny" style={{ maxHeight: 140, overflow: "auto" }}>
          {bad.slice(0, 12).map((item) => (
            <div key={item.line} style={{ lineHeight: 1.7 }}>
              <b>第 {item.line} 行</b>：{item.reason}
            </div>
          ))}
          {bad.length > 12 ? <div className="dim">…还有 {bad.length - 12} 行</div> : null}
        </div>
      ) : null}

      {result ? (
        <div className={result.ok ? "note note--ok tiny" : "note note--danger tiny"}>{result.message}</div>
      ) : null}
      {error ? <div className="note note--danger tiny">{error}</div> : null}
    </Dialog>
  );
}
