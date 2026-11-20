import { Activity, Plus, Power, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { isRunning, type ClashLiveNode, type ClashStatus, type ProxyStatus, type Settings } from "../api/client";
import { useApi } from "../hooks/useRealtime";
import { useToasts } from "../hooks/useToasts";
import { useDebouncedCallback } from "../hooks/useDebouncedCallback";
import { Badge, Button, Empty, Field, Panel, Skeleton } from "../components/ui";

export function NetworkView() {
  const api = useApi();
  const { push } = useToasts();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<ProxyStatus | null>(null);
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [clash, setClash] = useState<ClashStatus | null>(null);
  const [nodeFilter, setNodeFilter] = useState("");
  const [portDraft, setPortDraft] = useState("");
  const [saved, setSaved] = useState(false);

  const loadSettings = async () => {
    setError(null);
    try {
      const next = await api.getSettings();
      setSettings(next);
      setPortDraft(next.proxy_port ? String(next.proxy_port) : "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取网络设置失败");
    }
  };

  useEffect(() => {
    void loadSettings();
    void api.proxyStatus().then(setStatus).catch(() => {});
  }, [api]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void api.proxyStatus().then(setStatus).catch(() => undefined);
      if (settings?.proxy_mode === "clash") void api.clashStatus().then(setClash).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [api, settings?.proxy_mode]);

  useEffect(() => {
    if (settings?.proxy_mode === "clash") void api.clashStatus().then(setClash).catch(() => undefined);
  }, [api, settings?.proxy_mode]);

  const { run: queueSave } = useDebouncedCallback(async (next: Partial<Settings>) => {
    try {
      await api.saveSettings(next);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1200);
    } catch (err) {
      const fresh = await api.getSettings().catch(() => null);
      if (fresh) {
        setSettings(fresh);
        setPortDraft(fresh.proxy_port ? String(fresh.proxy_port) : "");
      }
      push({ kind: "error", title: "设置未保存", detail: String(err) });
    }
  }, 300);

  if (!settings) {
    return (
      <div className="page">
        {error ? (
          <Empty icon={Activity} title="无法读取网络设置" action={<Button onClick={() => void loadSettings()}>重试</Button>}>
            {error}
          </Empty>
        ) : (
          <>
            <Skeleton height={42} />
            <Skeleton height={220} />
            <Skeleton height={160} />
          </>
        )}
      </div>
    );
  }

  const patch = (next: Partial<Settings>) => {
    setSettings((prev) => (prev ? { ...prev, ...next } : prev));
    queueSave(next);
  };

  const upstream = settings.proxy_mode === "custom" || settings.proxy_mode === "mihomo";

  const addNode = () =>
    patch({
      hk_nodes: [...settings.hk_nodes, { type: "ss", server: "", port: 443, cipher: "aes-128-gcm", password: "" }],
    });

  const updateNode = (index: number, key: string, value: string | number) => {
    const nodes = settings.hk_nodes.map((node, i) => (i === index ? { ...node, [key]: value } : node));
    patch({ hk_nodes: nodes });
  };

  const removeNode = (index: number) => patch({ hk_nodes: settings.hk_nodes.filter((_, i) => i !== index) });

  const running = isRunning(status);

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>网络</h1>
          <p>代理模式决定每个请求的出口线路{saved ? " · 已保存" : ""}</p>
        </div>
        <div className="page__actions">
          <Button
            icon={Activity}
            variant="ghost"
            onClick={async () => {
              try {
                setStatus(await api.proxyStatus());
              } catch (err) {
                push({ kind: "error", title: "状态查询失败", detail: String(err) });
              }
            }}
          >
            刷新状态
          </Button>
        </div>
      </div>

      <Panel title="出口模式" subtitle="修改后 0.3 秒自动保存">
        <div className="seg" style={{ marginBottom: 12 }}>
          {(
            [
              ["direct", "直连 / 自定义"],
              ["custom", "固定代理"],
              ["clash", "本机代理"],
              ["mihomo", "内置代理"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={settings.proxy_mode === value}
              data-on={settings.proxy_mode === value}
              onClick={() => patch({ proxy_mode: value })}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="dim tiny" style={{ marginBottom: 10, lineHeight: 1.6 }}>
          {settings.proxy_mode === "direct"
            ? "直连：URL 留空即完全直连；填 URL 则全局走该代理（socks5h:// 会让代理解析 DNS）。"
            : settings.proxy_mode === "custom"
              ? "固定代理：填上游 host/port/账号，所有账号按 sid 复用同一出口会话。"
              : settings.proxy_mode === "clash"
                ? "本机代理：复用你已经在运行的代理客户端，只切换节点，不改变原有规则。"
                : "内置代理：由 Butter 自动配置；不加节点为单跳，添加节点后按顺序轮换出站。"}
        </div>

        {upstream && !settings.proxy_host ? (
          <div className="note note--warn tiny" style={{ marginBottom: 10 }}>
            还没有填上游主机，这个模式暂时不会有出口。
          </div>
        ) : null}

        {settings.proxy_mode === "direct" ? (
          <Field label="自定义代理 URL" hint="留空则完全直连，例如 socks5h://127.0.0.1:1080">
            <input
              name="proxy_url"
              value={settings.proxy_url}
              placeholder="(直连)"
              onChange={(event) => patch({ proxy_url: event.target.value })}
            />
          </Field>
        ) : null}

        {upstream ? (
          <div className="grid-3">
            <Field label="上游主机">
              <input
                name="proxy_host"
                autoComplete="off"
                value={settings.proxy_host}
                onChange={(event) => patch({ proxy_host: event.target.value })}
              />
            </Field>
            <Field label="端口">
              <input
                name="proxy_port"
                inputMode="numeric"
                value={portDraft}
                onChange={(event) => setPortDraft(event.target.value.replace(/\D/g, ""))}
                onBlur={() => {
                  const next = Math.min(65535, Number(portDraft) || 0);
                  setPortDraft(next ? String(next) : "");
                  if (next !== settings.proxy_port) patch({ proxy_port: next });
                }}
              />
            </Field>
            <Field label="类型">
              <select
                name="proxy_type"
                value={settings.proxy_type}
                onChange={(event) => patch({ proxy_type: event.target.value })}
              >
                <option value="socks5">socks5</option>
                <option value="http">http</option>
                <option value="https">https</option>
              </select>
            </Field>
            <Field label="用户名">
              <input
                name="proxy_user"
                autoComplete="off"
                value={settings.proxy_user}
                onChange={(event) => patch({ proxy_user: event.target.value })}
              />
            </Field>
            <Field label="密码">
              <input
                name="proxy_pass"
                autoComplete="off"
                value={settings.proxy_pass}
                onChange={(event) => patch({ proxy_pass: event.target.value })}
              />
            </Field>
            <Field label="落地线路">
              <select
                name="line"
                value={settings.line}
                onChange={(event) => patch({ line: event.target.value as "HK" | "US" })}
              >
                <option value="HK">HK</option>
                <option value="US">US</option>
              </select>
            </Field>
          </div>
        ) : null}
      </Panel>

      {settings.proxy_mode === "mihomo" ? (
        <Panel
          title="HK 节点池（可选）"
          subtitle="不填 = 单跳直出上游代理；填了 = 上游经 HK-LB 轮询节点链式出站"
          actions={
            <Button icon={Plus} variant="ghost" onClick={addNode}>
              添加节点
            </Button>
          }
        >
          <div className="nodes">
            {settings.hk_nodes.length === 0 ? (
              <div className="dim tiny">
                当前为单跳模式：请求直接走上面的上游代理。需要多出口时再加节点。
              </div>
            ) : null}
            {settings.hk_nodes.map((node, index) => (
              <div className="node" key={index}>
                <input
                  aria-label={`节点 ${index + 1} 服务器`}
                  placeholder="server"
                  value={node.server}
                  onChange={(event) => updateNode(index, "server", event.target.value)}
                />
                <input
                  aria-label={`节点 ${index + 1} 端口`}
                  placeholder="port"
                  inputMode="numeric"
                  value={node.port || ""}
                  onChange={(event) => updateNode(index, "port", Number(event.target.value.replace(/\D/g, "")) || 0)}
                />
                <input
                  aria-label={`节点 ${index + 1} 密码`}
                  placeholder="password"
                  value={node.password}
                  onChange={(event) => updateNode(index, "password", event.target.value)}
                />
                <Button icon={Trash2} variant="ghost" onClick={() => removeNode(index)} ariaLabel="删除节点" />
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      {settings.proxy_mode === "clash" ? (
        <Panel
          title="本机代理控制"
          subtitle={
            clash?.ok
              ? `已连接 · ${clash.groups.length} 个线路组 · ${clash.nodes.length} 个节点`
              : clash?.message || "未连接"
          }
          actions={
            <Button
              icon={Activity}
              variant="ghost"
              onClick={async () => {
                try {
                  const next = await api.clashStatus();
                  setClash(next);
                  if (!next.ok) push({ kind: "error", title: "代理未连接", detail: next.message });
                } catch (err) {
                  push({ kind: "error", title: "检测失败", detail: String(err) });
                }
              }}
            >
              重新检测
            </Button>
          }
        >
          <div className="grid-3" style={{ marginBottom: 12 }}>
            <Field label="控制接口" hint="代理客户端的本地控制地址">
              <input
                name="clash_api"
                value={settings.clash_api}
                placeholder="127.0.0.1:9090"
                onChange={(event) => patch({ clash_api: event.target.value })}
              />
            </Field>
            <Field label="SOCKS 入站" hint="请求从这里出去">
              <input
                name="clash_socks"
                value={settings.clash_socks}
                placeholder="socks5h://127.0.0.1:7890"
                onChange={(event) => patch({ clash_socks: event.target.value })}
              />
            </Field>
            <Field label="密钥" hint="没设就留空">
              <input
                name="clash_secret"
                value={settings.clash_secret}
                onChange={(event) => patch({ clash_secret: event.target.value })}
              />
            </Field>
          </div>

          <div className="setting-row">
            <div className="setting-row__text">
              <strong>切换组</strong>
              <span>轮换/手动切节点都作用于这个 Selector 组</span>
            </div>
            <div className="setting-row__control">
              <select
                aria-label="切换组"
                style={{ width: 220 }}
                value={settings.clash_group}
                onChange={(event) => patch({ clash_group: event.target.value })}
              >
                <option value="">（未选择）</option>
                {(clash?.groups ?? []).map((group) => (
                  <option key={group.name} value={group.name}>
                    {group.name} · {group.now || "—"}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="setting-row">
            <div className="setting-row__text">
              <strong>按区域轮换</strong>
              <span>批量跑账号时每个账号换一个出口节点</span>
            </div>
            <div className="setting-row__control">
              {(["HK", "US", "UK"] as const).map((region) => (
                <Button
                  key={region}
                  variant="sm"
                  onClick={async () => {
                    try {
                      const r = await api.clashRotate(region, 1);
                      push({ kind: "ok", title: `${region} 已切换`, detail: `${r.now}（共 ${r.total} 个）` });
                      setClash(await api.clashStatus());
                    } catch (err) {
                      push({ kind: "error", title: "切换失败", detail: String(err) });
                    }
                  }}
                >
                  {region}
                </Button>
              ))}
            </div>
          </div>

          <div className="setting-row" style={{ alignItems: "flex-start" }}>
            <div className="setting-row__text">
              <strong>节点</strong>
              <span>点击即切换；括号内为最近一次延迟</span>
            </div>
            <div className="setting-row__control" style={{ minWidth: 320 }}>
              <input
                aria-label="筛选节点"
                type="search"
                placeholder="筛选：香港 / 美国 / 英国"
                value={nodeFilter}
                onChange={(event) => setNodeFilter(event.target.value)}
              />
            </div>
          </div>

          <div className="nodes" style={{ maxHeight: 240, overflow: "auto", marginTop: 8 }}>
            {(clash?.nodes ?? [])
              .filter(
                (node: ClashLiveNode) => !nodeFilter || node.name.toLowerCase().includes(nodeFilter.toLowerCase()),
              )
              .slice(0, 60)
              .map((node) => (
                <button
                  key={node.name}
                  className="pick"
                  onClick={async () => {
                    try {
                      const r = await api.clashRotate(node.name, 0);
                      push({ kind: "ok", title: "节点已切换", detail: r.now });
                      setClash(await api.clashStatus());
                    } catch (err) {
                      push({ kind: "error", title: "切换失败", detail: String(err) });
                    }
                  }}
                  style={{ width: "100%" }}
                >
                  <span className="pick__email">{node.name}</span>
                  <span className="pick__badge">
                    <Badge tone={node.alive ? (node.delay && node.delay < 300 ? "online" : "warn") : "offline"}>
                      {node.delay ? `${node.delay}ms` : "—"}
                    </Badge>
                  </span>
                </button>
              ))}
            {clash?.ok && (clash.nodes ?? []).length === 0 ? <div className="dim tiny">暂时没有可用节点。</div> : null}
          </div>
        </Panel>
      ) : null}

      <Panel
        title="内置代理"
        subtitle={
          settings.proxy_mode === "mihomo"
            ? "需要先完成上面的代理配置"
            : "仅「内置代理」模式需要在这里启动；「本机代理」会复用已运行的客户端"
        }
        actions={
          <>
            <Button
              icon={RotateCw}
              variant="ghost"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  setProfile(await api.previewProfile());
                } catch (err) {
                  push({ kind: "error", title: "生成配置失败", detail: String(err) });
                } finally {
                  setBusy(false);
                }
              }}
              disabled={settings.proxy_mode !== "mihomo"}
            >
              预览配置
            </Button>
            <Button
              icon={Power}
              variant={running ? "ghost" : "primary"}
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const next = running ? await api.stopProxy() : await api.startProxy();
                  setStatus(next);
                  push({
                    kind: isRunning(next) ? "ok" : "info",
                    title: isRunning(next) ? "mihomo 已启动" : "mihomo 已停止",
                    detail: next.error || next.config,
                  });
                } catch (err) {
                  push({ kind: "error", title: "操作失败", detail: String(err) });
                } finally {
                  setBusy(false);
                }
              }}
              disabled={settings.proxy_mode !== "mihomo"}
            >
              {running ? "停止" : "启动 mihomo"}
            </Button>
          </>
        }
      >
        <div className="stack">
          <div className="row row--between">
            <span className="muted tiny">状态</span>
            <Badge tone={running ? "online" : status?.error ? "offline" : "idle"} dot pulse={running}>
              {running ? "运行中" : status?.error ? status.error : "未运行"}
            </Badge>
          </div>
          <div className="row row--between">
            <span className="muted tiny">监听端口</span>
            <span className="mono tiny">{status?.port || "—"}</span>
          </div>
          <div className="row row--between">
            <span className="muted tiny">PID</span>
            <span className="mono tiny">{status?.pid ?? "—"}</span>
          </div>
          {profile ? <pre className="profile">{JSON.stringify(profile, null, 2)}</pre> : null}
        </div>
      </Panel>
    </div>
  );
}
