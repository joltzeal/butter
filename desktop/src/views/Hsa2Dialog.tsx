import { Delete, KeyRound, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/ui";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "del"];

/**
 * Six-digit 2FA entry with an on-screen keypad.
 *
 * Shown when the login stops at HSA2 and no usable ``code_url`` was available —
 * the operator reads the code off their device and taps it in. Physical
 * keyboard input keeps working alongside the pad.
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

  useEffect(() => {
    if (open) {
      setCode("");
      setBusy(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (/^\d$/.test(event.key)) {
        setCode((prev) => (prev + event.key).slice(0, 6));
      } else if (event.key === "Backspace") {
        setCode((prev) => prev.slice(0, -1));
      } else if (event.key === "Enter") {
        void submit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!open) return null;

  const submit = async () => {
    if (code.length < 6 || busy) return;
    setBusy(true);
    try {
      await onSubmit(code);
    } finally {
      setBusy(false);
    }
  };

  const press = (key: string) => {
    if (busy) return;
    if (key === "del") {
      setCode((prev) => prev.slice(0, -1));
      return;
    }
    if (!key) return;
    setCode((prev) => (prev.length >= 6 ? prev : prev + key));
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

          <div className="code-display">
            {Array.from({ length: 6 }).map((_, index) => (
              <span key={index} className="code-display__slot" data-filled={index < code.length}>
                {code[index] ?? ""}
              </span>
            ))}
          </div>

          <div className="keypad">
            {KEYS.map((key, index) => {
              if (!key) return <span key={index} />;
              return (
                <button
                  key={key}
                  type="button"
                  className="keypad__key"
                  data-variant={key === "del" ? "del" : undefined}
                  onClick={() => press(key)}
                  disabled={busy}
                >
                  {key === "del" ? <Delete style={{ width: 17 }} /> : key}
                </button>
              );
            })}
          </div>

          <div className="dim tiny" style={{ textAlign: "center", marginTop: 10, lineHeight: 1.6 }}>
            5 分钟内有效，连续错误 3 次需重新登录
          </div>
        </div>

        <footer className="modal__foot">
          <Button variant="ghost" onClick={onCancel}>
            取消
          </Button>
          <Button variant="primary" onClick={submit} disabled={busy || code.length < 6}>
            {busy ? "验证中…" : "提交"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
