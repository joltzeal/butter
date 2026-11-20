import { Sun } from "lucide-react";
import { useEffect, useState } from "react";
import type { Settings } from "../api/client";
import { useApi } from "../hooks/useRealtime";
import { useSecretUnlock } from "../hooks/useSecretUnlock";
import { useToasts } from "../hooks/useToasts";
import { invoke } from "@tauri-apps/api/core";
import { Button, Panel, Skeleton } from "../components/ui";

/** Activation endpoint; set via VITE_ACTIVATION_URL at build time. */
const ACTIVATION_URL = (import.meta.env.VITE_ACTIVATION_URL as string | undefined) ?? "";

export function SettingsView() {
  const api = useApi();
  const { push } = useToasts();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [version, setVersion] = useState("—");
  const [machineId, setMachineId] = useState("");
  const [license, setLicense] = useState<{ licensed: boolean; plan: string; exp: number; free_limit: number } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [licenseError, setLicenseError] = useState("");
  const { tapAbout } = useSecretUnlock();
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("butter.theme") ?? "dark");

  useEffect(() => {
    void api.getSettings().then(setSettings);
    void api.version().then((v) => setVersion(v.version));
    void api.license().then(setLicense).catch(() => {});
    void invoke<string>("license_machine").then(setMachineId).catch(() => {});
  }, [api]);

  const activate = async () => {
    const trimmed = code.trim().toUpperCase();
    if (trimmed.length < 8 || busy) return;
    setBusy(true);
    setLicenseError("");
    try {
      if (!ACTIVATION_URL) {
        setLicenseError("尚未配置激活服务器");
        return;
      }
      const res = await fetch(`${ACTIVATION_URL.replace(/\/$/, "")}/activate`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: trimmed, machine: machineId }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        payload?: string;
        sig?: string;
        checked?: number;
        detail?: string;
      };
      if (!res.ok || !body.payload || !body.sig) {
        setLicenseError(body.detail ?? "激活码无效");
        return;
      }
      await invoke("license_apply", {
        payload: body.payload,
        sig: body.sig,
        checked: body.checked ?? Math.floor(Date.now() / 1000),
      });
      setCode("");
      push({ kind: "ok", title: "已激活", detail: "额度已更新" });
      void api.license().then(setLicense).catch(() => {});
    } catch (err) {
      setLicenseError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleAboutClick = () => {
    const next = tapAbout();
    if (next) {
      push({
        kind: "ok",
        title: "已解锁",
        detail: "事件面板已显示在左侧",
      });
    }
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("butter.theme", theme);
  }, [theme]);

  if (!settings) {
    return (
      <div className="page">
        <Skeleton height={42} />
        <Skeleton height={180} />
        <Skeleton height={180} />
      </div>
    );
  }

  const patch = async (next: Partial<Settings>) => {
    setSettings({ ...settings, ...next });
    await api.saveSettings(next);
  };

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>设置</h1>
          <p>外观与探测节奏</p>
        </div>
      </div>

      <Panel title="外观" className="settings-panel">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong>主题</strong>
            <span>深色为默认；浅色适合强光环境</span>
          </div>
          <div className="setting-row__control">
            <div className="seg">
              {["dark", "light"].map((value) => (
                <button key={value} data-on={theme === value} onClick={() => setTheme(value)}>
                  {value === "dark" ? "深色" : "浅色"}
                </button>
              ))}
            </div>
            <Sun style={{ width: 14, color: "var(--text-dim)" }} />
          </div>
        </div>
      </Panel>

      <Panel title="行为" className="settings-panel">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong>会话实时探活</strong>
            <span>定期检查会话是否还可答，失效的账号立刻标记离线</span>
          </div>
          <div className="setting-row__control">
            <button
              className="switch"
              data-on={settings.session_poll}
              onClick={() => void patch({ session_poll: !settings.session_poll })}
              aria-label="toggle"
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>探活间隔</strong>
            <span>秒；只发一个轻量请求，可设得比较短</span>
          </div>
          <div className="setting-row__control">
            <input
              style={{ width: 80, textAlign: "right" }}
              value={settings.session_poll_seconds}
              inputMode="numeric"
              onChange={(event) =>
                void patch({
                  session_poll_seconds: Math.min(300, Math.max(5, Number(event.target.value.replace(/\D/g, "")) || 20)),
                })
              }
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>网络重试次数</strong>
            <span>仅对代理 / TLS 类错误重试，密码错误不重试</span>
          </div>
          <div className="setting-row__control">
            <input
              style={{ width: 80, textAlign: "right" }}
              value={settings.retry_attempts}
              inputMode="numeric"
              onChange={(event) =>
                void patch({ retry_attempts: Number(event.target.value.replace(/\D/g, "")) || 1 })
              }
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>详细网络日志</strong>
            <span>把每个请求的状态码记入事件日志</span>
          </div>
          <div className="setting-row__control">
            <button
              className="switch"
              data-on={settings.verbose_network_log}
              onClick={() => void patch({ verbose_network_log: !settings.verbose_network_log })}
              aria-label="toggle"
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>浏览器版本</strong>
            <span>用于匹配请求特征</span>
          </div>
          <div className="setting-row__control">
            <select
              style={{ width: 160 }}
              value={settings.impersonate}
              onChange={(event) => void patch({ impersonate: event.target.value })}
            >
              <option value="chrome142">chrome142</option>
              <option value="chrome134">chrome134</option>
              <option value="chrome145">chrome145</option>
            </select>
          </div>
        </div>
      </Panel>

      <Panel className="settings-panel" title="激活">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong>{license?.licensed ? "已激活" : "未激活"}</strong>
            <span>
              {license?.licensed
                ? `${license.plan} · 剩余 ${
                    Math.max(0, Math.ceil((license.exp * 1000 - Date.now()) / 86_400_000))
                  } 天`
                : `最多 ${license?.free_limit ?? 2} 个账号，激活后不限`}
            </span>
          </div>
          <div className="setting-row__control">
            <span className="mono tiny">{machineId || "—"}</span>
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>{license?.licensed ? "续期" : "输入激活码"}</strong>
            <span>{license?.licensed ? "再输入一个码即可延长" : "绑定当前设备"}</span>
          </div>
          <div className="setting-row__control">
            <input
              style={{ width: 200, textAlign: "center", fontFamily: "var(--font-mono)" }}
              placeholder="XXXX-XXXX-XXXX-XXXX-X"
              value={code}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === "Enter") void activate();
              }}
            />
            <Button
              variant="primary"
              disabled={busy || code.trim().length < 8}
              onClick={() => void activate()}
            >
              {busy ? "提交中…" : license?.licensed ? "续期" : "激活"}
            </Button>
          </div>
        </div>
        {licenseError ? (
          <div className="setting-row">
            <span className="tiny" style={{ color: "var(--danger)" }}>
              {licenseError}
            </span>
          </div>
        ) : null}
      </Panel>

      <Panel className="settings-panel" title="关于">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong
              onClick={handleAboutClick}
              style={{ cursor: "default", userSelect: "none" }}
              title=""
            >
              关于
            </strong>
            <span>Butter · 版本 {version}</span>
          </div>
          <div className="setting-row__control">
            <span className="mono tiny dim">{version}</span>
          </div>
        </div>
      </Panel>
    </div>
  );
}
