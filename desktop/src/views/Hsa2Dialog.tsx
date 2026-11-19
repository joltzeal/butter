import { KeyRound, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui";

const CODE_LENGTH = 6;

/**
 * Two-factor code entry.
 *
 * Shown when the login stops at HSA2 and no usable ``code_url`` was available:
 * the operator reads the code off their device and types it. A plain field, not
 * an on-screen keypad — the code is six digits and the keyboard is right there.
 */
export function Hsa2Dialog({
  open,
  email,
  reason,
  onSubmit,
  onCancel,
}: {
  open: boolean;
  email: string;
  /** Why the automatic fetch did not happen, shown as context. */
  reason?: string;
  onSubmit: (code: string) => Promise<void> | void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setCode("");
    setBusy(false);
    setTouched(false);
    // The dialog is the only thing on screen; focus belongs in the field.
    window.setTimeout(() => input.current?.focus(), 30);
  }, [open]);

  if (!open) return null;

  const valid = new RegExp(`^\\d{${CODE_LENGTH}}$`).test(code);

  const submit = async () => {
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true);
    try {
      await onSubmit(code);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onCancel}>
      <div className="modal modal--sm" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal__head">
          <KeyRound style={{ width: 16, color: "var(--amber)" }} />
          <div>
            <h2>需要两步验证</h2>
            <p style={{ wordBreak: "break-all" }}>{email || "输入设备上收到的 6 位验证码"}</p>
          </div>
          <button className="modal__close" onClick={onCancel}>
            <X />
          </button>
        </header>

        <div className="modal__body">
          {reason ? (
            <div
              className="tiny"
              style={{
                marginBottom: 12,
                padding: "7px 10px",
                borderRadius: 8,
                lineHeight: 1.6,
                background: "color-mix(in srgb, var(--warn) 10%, transparent)",
                border: "1px solid color-mix(in srgb, var(--warn) 32%, transparent)",
              }}
            >
              {reason}
            </div>
          ) : null}

          <input
            ref={input}
            value={code}
            onChange={(event) => {
              // Digits only, length-capped: paste of "123 456" still works.
              setCode(event.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH));
              setTouched(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submit();
            }}
            onBlur={() => setTouched(true)}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="000000"
            aria-label="六位验证码"
            data-invalid={touched && code.length > 0 && !valid ? "true" : undefined}
            style={{
              width: "100%",
              height: 42,
              textAlign: "center",
              letterSpacing: "0.42em",
              fontSize: 19,
              fontVariantNumeric: "tabular-nums",
              fontFamily: "var(--font-mono)",
            }}
          />
          <div className="dim tiny" style={{ marginTop: 8, lineHeight: 1.6 }}>
            {touched && code.length > 0 && !valid
              ? `还差 ${CODE_LENGTH - code.length} 位，需 ${CODE_LENGTH} 位数字`
              : "6 位数字 · 5 分钟内有效，连续错误 3 次需重新登录"}
          </div>
        </div>

        <footer className="modal__foot">
          <Button variant="ghost" onClick={onCancel}>
            取消
          </Button>
          <Button variant="primary" onClick={submit} disabled={busy || !valid}>
            {busy ? "验证中…" : "提交"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
