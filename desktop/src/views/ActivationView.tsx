import { KeyRound, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Button } from "../components/ui";

/** Activation endpoint. Swap for the Worker route when it exists. */
const ACTIVATION_URL = (import.meta.env.VITE_ACTIVATION_URL as string | undefined) ?? "";

interface Status {
  licensed: boolean;
  reason: string;
  plan: string;
  exp: number;
  days_left: number;
}

/**
 * Full-window gate shown until a licence is present.
 *
 * Deliberately separate from the workspace: without a licence there is no
 * backend, so nothing else can load.
 */
export function ActivationView({ onDone }: { onDone: () => void }) {
  const [machine, setMachine] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void invoke<string>("license_machine").then(setMachine).catch(() => {});
  }, []);

  const submit = async () => {
    const trimmed = code.trim().toUpperCase();
    if (trimmed.length < 8 || busy) return;
    setBusy(true);
    setError("");
    try {
      if (!ACTIVATION_URL) {
        setError("尚未配置激活服务器");
        return;
      }
      const res = await fetch(`${ACTIVATION_URL.replace(/\/$/, "")}/activate`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: trimmed, machine }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        payload?: string;
        sig?: string;
        checked?: number;
        detail?: string;
      };
      if (!res.ok || !body.payload || !body.sig) {
        setError(body.detail ?? "激活码无效");
        return;
      }
      const status = await invoke<Status>("license_apply", {
        payload: body.payload,
        sig: body.sig,
        checked: body.checked ?? Math.floor(Date.now() / 1000),
      });
      if (status.licensed) onDone();
      else setError(status.reason);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="activation">
      <div className="activation__card">
        <div className="activation__brand">
          <img src="/butter.png" alt="" className="activation__logo" />
          <div>
            <h1>激活 Butter</h1>
            <p>输入卡密以启用这台设备</p>
          </div>
        </div>

        <input
          value={code}
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit();
          }}
          placeholder="XXXX-XXXX-XXXX-XXXX"
          autoFocus
          spellCheck={false}
          style={{ letterSpacing: "0.14em", textAlign: "center", fontFamily: "var(--font-mono)" }}
        />

        <div className="activation__machine">
          <KeyRound style={{ width: 12 }} />
          <span className="mono tiny">{machine || "读取机器标识…"}</span>
        </div>

        {error ? <div className="activation__error">{error}</div> : null}

        <Button
          variant="primary"
          onClick={() => void submit()}
          disabled={busy || code.trim().length < 8}
        >
          {busy ? (
            <span className="row" style={{ gap: 6 }}>
              <Loader2 className="spin" style={{ width: 13 }} /> 激活中…
            </span>
          ) : (
            "激活"
          )}
        </Button>

        <p className="activation__hint">卡密绑定当前设备，重装系统后需重新激活</p>
      </div>
    </div>
  );
}
