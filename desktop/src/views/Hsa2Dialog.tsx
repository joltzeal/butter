import { KeyRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui";
import { Dialog } from "../components/Dialog";

const CODE_LENGTH = 6;

/**
 * Two-factor code entry.
 *
 * Shown when the login stops at HSA2 and no usable ``code_url`` was available:
 * the operator reads the code off their device and types it.
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
  /** Resolve `true` when the backend accepted the code. */
  onSubmit: (code: string) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setCode("");
    setBusy(false);
    setTouched(false);
    setError("");
  }, [open]);

  const valid = new RegExp(`^\\d{${CODE_LENGTH}}$`).test(code);

  const submit = async () => {
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    try {
      if ((await onSubmit(code)) === false) setError("验证码未被接受，请确认后重试");
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title="需要两步验证"
      subtitle={email || "输入设备上收到的 6 位验证码"}
      icon={KeyRound}
      busy={busy}
      onSubmit={submit}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" type="submit" disabled={!valid} loading={busy}>
            {busy ? "验证中…" : "提交"}
          </Button>
        </>
      }
    >
      {reason ? (
        <div className="note note--warn tiny">{reason}</div>
      ) : null}

      <input
        ref={input}
        name="one-time-code"
        autoFocus
        value={code}
        onChange={(event) => {
          // Digits only, length-capped: paste of "123 456" still works.
          setCode(event.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH));
          setTouched(true);
          setError("");
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
      <div className={error ? "field__hint field__hint--error" : "dim tiny"} style={{ lineHeight: 1.6 }}>
        {error
          ? error
          : touched && code.length > 0 && !valid
            ? `还差 ${CODE_LENGTH - code.length} 位，需 ${CODE_LENGTH} 位数字`
            : "6 位数字 · 5 分钟内有效，连续错误 3 次需重新登录"}
      </div>
    </Dialog>
  );
}
