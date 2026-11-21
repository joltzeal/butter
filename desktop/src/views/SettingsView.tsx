import { invoke } from "@tauri-apps/api/core";
import { Download, KeyRound, RefreshCw, RotateCw, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { activate, applyLicense, isTauri, type License, type Settings } from "../api/client";
import { useApi } from "../hooks/useRealtime";
import { useSecretUnlock } from "../hooks/useSecretUnlock";
import { useToasts } from "../hooks/useToasts";
import { useDebouncedCallback } from "../hooks/useDebouncedCallback";
import { useUpdater } from "../hooks/useUpdater";
import { Button, Panel, Skeleton } from "../components/ui";

export function SettingsView() {
  const api = useApi();
  const { push } = useToasts();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState("—");
  const [machineId, setMachineId] = useState("");
  const [license, setLicense] = useState<License | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [licenseError, setLicenseError] = useState("");
  const { tapAbout, unlocked } = useSecretUnlock();
  const updater = useUpdater();
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("butter.theme") ?? "dark");

  // Inputs are drafts: clamping on every keystroke turned "30" into "50".
  const [pollSeconds, setPollSeconds] = useState("20");
  const [retries, setRetries] = useState("3");

  const load = async () => {
    setError(null);
    try {
      const next = await api.getSettings();
      setSettings(next);
      setPollSeconds(String(next.session_poll_seconds));
      setRetries(String(next.retry_attempts));
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取设置失败");
    }
  };

  useEffect(() => {
    void load();
    void api.version().then((v) => setVersion(v.version)).catch(() => {});
    void api.license().then(setLicense).catch(() => {});
    void invoke<string>("license_machine").then(setMachineId).catch(() => {});
  }, [api]);

  // Theme is local-only; write both the attribute and the store.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("butter.theme", theme);
  }, [theme]);

  const { run: queueSave } = useDebouncedCallback(async (next: Partial<Settings>) => {
    try {
      await api.saveSettings(next);
    } catch (err) {
      // Put the server's truth back rather than leaving an unsaved value on screen.
      const fresh = await api.getSettings().catch(() => null);
      if (fresh) {
        setSettings(fresh);
        setPollSeconds(String(fresh.session_poll_seconds));
        setRetries(String(fresh.retry_attempts));
      }
      push({ kind: "error", title: "设置未保存", detail: String(err) });
    }
  }, 250);

  const patch = (next: Partial<Settings>) => {
    setSettings((prev) => (prev ? { ...prev, ...next } : prev));
    queueSave(next);
  };

  // The sidecar carries the same id; prefer it over a failed invoke.
  const machine = machineId || license?.machine || "";

  const activateCode = async () => {
    const trimmed = code.trim().toUpperCase();
    if (trimmed.length < 8 || busy) return;
    setBusy(true);
    setLicenseError("");
    try {
      const ticket = await activate(trimmed, machine);
      const applied = await applyLicense(ticket);
      setCode("");
      if (applied) {
        setLicense(applied);
        push({ kind: "ok", title: "已激活", detail: `到期 ${new Date(applied.exp * 1000).toLocaleDateString("zh-CN")}` });
      } else if (!isTauri()) {
        push({ kind: "info", title: "激活码有效", detail: "浏览器预览不落盘，窗口内粘贴即可写入" });
      }
    } catch (err) {
      setLicenseError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleAboutClick = () => {
    if (tapAbout()) {
      push({
        kind: "ok",
        title: "已解锁",
        detail: "「事件」已出现在左侧导航",
      });
    }
  };

  if (!settings) {
    return (
      <div className="page">
        {error ? (
          <Panel title="设置" subtitle={error}>
            <Button icon={KeyRound} onClick={() => void load()}>
              重试
            </Button>
          </Panel>
        ) : (
          <>
            <Skeleton height={42} />
            <Skeleton height={180} />
            <Skeleton height={180} />
          </>
        )}
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>设置</h1>
        </div>
      </div>

      <Panel title="外观" className="settings-panel">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong>主题</strong>
          </div>
          <div className="setting-row__control">
            <div className="seg">
              {["dark", "light"].map((value) => (
                <button key={value} type="button" data-on={theme === value} onClick={() => setTheme(value)}>
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
          </div>
          <div className="setting-row__control">
            <button
              type="button"
              className="switch"
              data-on={settings.session_poll}
              aria-pressed={settings.session_poll}
              aria-label="会话实时探活"
              onClick={() => patch({ session_poll: !settings.session_poll })}
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>探活间隔</strong>
            <span>秒（5–300）</span>
          </div>
          <div className="setting-row__control">
            <input
              name="session_poll_seconds"
              style={{ width: 80, textAlign: "right" }}
              inputMode="numeric"
              value={pollSeconds}
              onChange={(event) => setPollSeconds(event.target.value.replace(/\D/g, ""))}
              onBlur={() => {
                const next = Math.min(300, Math.max(5, Number(pollSeconds) || 20));
                setPollSeconds(String(next));
                if (next !== settings.session_poll_seconds) patch({ session_poll_seconds: next });
              }}
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>网络重试次数</strong>
            <span>0–10</span>
          </div>
          <div className="setting-row__control">
            <input
              name="retry_attempts"
              style={{ width: 80, textAlign: "right" }}
              inputMode="numeric"
              value={retries}
              onChange={(event) => setRetries(event.target.value.replace(/\D/g, ""))}
              onBlur={() => {
                const next = Math.min(10, Math.max(0, Number(retries) || 0));
                setRetries(String(next));
                if (next !== settings.retry_attempts) patch({ retry_attempts: next });
              }}
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>详细网络日志</strong>
          </div>
          <div className="setting-row__control">
            <button
              type="button"
              className="switch"
              data-on={settings.verbose_network_log}
              aria-pressed={settings.verbose_network_log}
              aria-label="详细网络日志"
              onClick={() => patch({ verbose_network_log: !settings.verbose_network_log })}
            />
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>浏览器版本</strong>
          </div>
          <div className="setting-row__control">
            <select
              name="impersonate"
              style={{ width: 160 }}
              value={settings.impersonate}
              onChange={(event) => patch({ impersonate: event.target.value })}
            >
              <option value="chrome145">chrome145</option>
              <option value="chrome142">chrome142</option>
              <option value="chrome134">chrome134</option>
            </select>
          </div>
        </div>
      </Panel>

      <Panel
        className="settings-panel"
        title="更新"
        subtitle={`当前版本 ${version}`}
        actions={
          <Button
            icon={RefreshCw}
            variant="ghost"
            loading={updater.state === "checking"}
            disabled={updater.state === "downloading" || updater.state === "ready"}
            onClick={() => void updater.find()}
          >
            检查更新
          </Button>
        }
      >
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong>
              {updater.state === "available"
                ? `可更新到 ${updater.info?.version}`
                : updater.state === "downloading"
                  ? "正在下载…"
                  : updater.state === "ready"
                    ? "已就绪，重启后生效"
                    : updater.state === "current"
                      ? "已是最新"
                      : updater.state === "checking"
                        ? "正在检查…"
                        : updater.state === "error"
                          ? "检查失败"
                          : "自动更新"}
            </strong>
            <span>
              {updater.state === "error"
                ? updater.error
                : updater.state === "available"
                  ? updater.info?.notes || "下载后需重启应用"
                  : ""}
            </span>
            {updater.state === "downloading" ? (
              <div className="progress" aria-label="下载进度" role="progressbar" aria-valuenow={updater.progress}>
                <span style={{ width: `${updater.progress}%` }} />
              </div>
            ) : null}
          </div>
          <div className="setting-row__control">
            {updater.state === "available" ? (
              <Button icon={Download} variant="primary" onClick={() => void updater.download()}>
                下载并安装
              </Button>
            ) : updater.state === "ready" ? (
              <Button icon={RotateCw} variant="primary" onClick={() => void updater.restart()}>
                重启并安装
              </Button>
            ) : updater.state === "downloading" ? (
              <span className="mono tiny">{updater.progress}%</span>
            ) : null}
          </div>
        </div>
      </Panel>

      <Panel className="settings-panel" title="激活">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <strong>{license?.licensed ? "已激活" : "未激活"}</strong>
            <span>
              {license?.licensed
                ? `${license.plan} · 剩余 ${Math.max(
                    0,
                    Math.ceil((license.exp * 1000 - Date.now()) / 86_400_000),
                  )} 天`
                : `最多 ${license?.free_limit ?? 2} 个账号，激活后不限`}
            </span>
          </div>
          <div className="setting-row__control">
            <span className="mono tiny" title="机器码">
              {machine || "—"}
            </span>
          </div>
        </div>
        <div className="setting-row">
          <div className="setting-row__text">
            <strong>{license?.licensed ? "续期" : "输入激活码"}</strong>
          </div>
          <div className="setting-row__control">
            <input
              name="activation_code"
              style={{ width: 200, textAlign: "center", fontFamily: "var(--font-mono)" }}
              placeholder="XXXX-XXXX-XXXX-XXXX-X"
              spellCheck={false}
              value={code}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === "Enter") void activateCode();
              }}
            />
            <Button
              variant="primary"
              disabled={busy || code.trim().length < 8}
              loading={busy}
              onClick={() => void activateCode()}
            >
              {busy ? "提交中…" : license?.licensed ? "续期" : "激活"}
            </Button>
          </div>
        </div>
        {licenseError ? (
          <div className="setting-row">
            <span className="field__hint field__hint--error">{licenseError}</span>
          </div>
        ) : null}
      </Panel>

      <Panel className="settings-panel" title="关于">
        <div className="setting-row" style={{ paddingTop: 0 }}>
          <div className="setting-row__text">
            <button type="button" className="about-title" onClick={handleAboutClick} title="连点 5 下解锁「事件」">
              关于
            </button>
            <span>
              Butter · 版本 <span className="mono">{version}</span>
            </span>
          </div>
          <div className="setting-row__control">
            {unlocked ? (
              <BadgeInline />
            ) : (
              <span className="dim tiny">连点「关于」5 下可解锁事件面板</span>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}

function BadgeInline() {
  return <span className="badge badge--card">事件已解锁</span>;
}
