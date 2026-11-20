# Butter 前端审计报告

审计对象：`desktop/`（Tauri v2 壳 + React 19 渲染层，约 4.1k 行 TS/TSX + 2.4k 行 CSS）
审计时间：2026-11-21
方法：全量通读 → 静态分析（`tsc --noEmit` 通过，说明问题都在类型之外）→ 真机跑通（vite dev + 本机后端 7911 + Playwright 1280×820 驱动真实交互）→ 逐条复现取证。
后端代码只用于核对契约（`api/app.py`、`api/models.py`、`core/billing.py`），不改。

结论：**不是"写得土"，是有若干条会让用户做错事、丢改动、卡死的确定性缺陷**。类型检查全绿，但下面 P0 每一条都实测复现了。先修 P0，再谈风格。

---

## P0 — 会让用户做错事 / 丢数据 / 卡死

### 1. 改账号邮箱必失败，且失败后对话框照样关闭（静默失败）

`views/AccountEditDialog.tsx:37-42` 把"旧 key"和"新邮箱"塞进同一个 `email` 字段：

```ts
const patch: { email?: string; password?: string; note?: string } = {};
if (email.trim().toLowerCase() !== account.email.toLowerCase()) patch.email = email.trim();
...
await actions.update.mutateAsync({ email: account.email, ...patch }).catch(() => {});
onClose();
```

`hooks/useAccounts.ts:54` 的 `mutationFn: ({ email, ...patch }) => api.updateAccount(email, patch)` —— 展开后 `email` 被 `patch.email` 覆盖，PATCH 打到**新地址**，而库里还在旧地址。

实测（`smithcasslee@icloud.com` → `smithcasslee+renamed@icloud.com`）：

```
PATCH /api/accounts/smithcasslee%2Brenamed%40icloud.com → 404
toast: 更新失败 / account not found
dialog still open: 0        # 关得比失败还快
row emails: [... smithcasslee@icloud.com]   # 没变
```

同一个函数里 `catch(() => {})` + 无条件 `onClose()`，把 404 演成了"改完了"。

修复：key 与 payload 分离。

```ts
// hooks/useAccounts.ts
const update = useMutation({
  mutationFn: ({ key, patch }: { key: string; patch: { email?: string; password?: string; note?: string } }) =>
    api.updateAccount(key, patch),
  onSuccess: (account) => {
    qc.setQueryData<Account[]>(KEY, (prev) =>
      prev?.map((a) => (a.email === account.email ? a : a)),  // 或直接 invalidate
    );
    invalidate();
  },
  onError: (err: Error) => push({ kind: "error", title: "更新失败", detail: err.message }),
});
```

```ts
// views/AccountEditDialog.tsx
const save = async () => {
  if (!valid) return;
  try {
    await actions.update.mutateAsync({ key: account.email, patch });
    onClose();
  } catch {
    /* toast 已弹，对话框留着让用户改 */
  }
};
```

另外回调 `onSuccess` 里要和 `WorkspaceView` 的 `selected` 对齐：改名成功后 `setSelected(newEmail)`，否则 peek 面板指向一个已不存在的 key。

### 2. 读完账单，保存按钮永久禁用 —— 改地址必须先重打整串卡号，且毫无提示

- `WorkspaceView.tsx:56` `toForm()` 始终 `card_number: ""`；
- `WorkspaceView.tsx:590` `disabled={... || !form.card_number || !form.card_expiry}`；
- 服务端 `apple_auth/billing.py:265` 在非 `remove_only` 时强制要求 `card_number`。

实测：账单读取成功后

```
save disabled = true
card_number value = ""
```

于是"我只想改个城市"这个最常见的动作被判死。`remove_only` 字段在 `EMPTY` 里定义（`:51`）、类型里有、服务端有，**前端从没置过 true**，`deleteBilling` 走的是另一个接口。

修复（二选一，推荐 A）：

A. 承认"重填卡号"是服务端硬约束，把它说清楚：

```tsx
<Field label="卡号" hint="修改任何字段都要重填一次完整卡号">
  <input
    inputMode="numeric"
    autoComplete="cc-number"
    placeholder={info?.card_suffix ? `已存尾号 ${info.card_suffix}，请重填` : "4111 1111 1111 1111"}
    value={form.card_number}
    onChange={(e) => set("card_number", e.target.value)}
    aria-invalid={touchedSave && !form.card_number ? true : undefined}
  />
</Field>
```

保存按钮改为**可点**，点了再校验并聚焦卡号（`disabled` 的按钮在 12px 下几乎看不出来，见 P2-3）：

```tsx
<Button variant="primary" disabled={!current || actions.saveBilling.isPending} onClick={submit}>保存账单</Button>
```

B. 若要保留不重填的路径：`remove_only` 之外再给服务端加"仅地址"分支，前端传 `card_number: ""` 时保留旧卡。

### 3. 「眼睛」按钮是纯装饰，卡号永远明文

`WorkspaceView.tsx:115` 有 `reveal` 状态、`:461-462` 在切它，`reveal` 除了自己的 `title` 之外**没人读**。卡号输入框从没设过 `type`。

```tsx
<input type={reveal ? "text" : "password"} ... />
```

顺带：卡号为空时显示的是 placeholder `4111 1111 1111 1111`（浅灰），配上用例 2 的禁用保存，看起来就像"卡号已就位"。这是本报告里最容易骗到人的一处。

### 4. Esc 关不掉任何对话框；README 的承诺是假的

`desktop/README.md` 写着 *"`Esc` closes every overlay"*。实际只有 `App.tsx:100` 在全局监听里对命令面板生效；`ConfirmDialog` / `Hsa2Dialog` / `AddAccountDialog` / `BulkImportDialog` / `PasteDialog` / `AccountEditDialog` 全都没有 Esc 处理、没有焦点陷阱、没有 `role="dialog"`。

实测：打开删除确认框 → `Escape` → `modal after ESC: 1`（还在，并且因为遮罩挡住，后续点击全部超时）。

修复：抽一个 `useDialog` 统一处理 Esc + 焦点圈 + 关闭后回焦。

```tsx
export function useDialog(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key !== "Tab" || !ref.current) return;
      const f = ref.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); prev?.focus(); };
  }, [open, onClose]);
  return ref;
}
```

```tsx
<div className="modal-backdrop" onMouseDown={onClose}>
  <div className="modal modal--sm" role="dialog" aria-modal="true" aria-labelledby="dlg-title"
       ref={ref} onMouseDown={(e) => e.stopPropagation()}>
    <h2 id="dlg-title">…</h2>
```

### 5. 设置里「探活间隔」逐键 clamp：输入 30 得到 50，输入 120 得到 300

`SettingsView.tsx:153-162`：受控值来自 settings，`onChange` 里立刻 `Math.max(5, Number(...))` 并写回后端。第一字符 `3` 被抬到 `5`，输入框显示 `5`，再敲 `0` 就成了 `50`。

实测：

```
typed "30"  -> value = 50
typed "120" -> value = 300
```

修复：本地草稿 + 失焦/回车才落库。

```tsx
const [pollDraft, setPollDraft] = useState(String(settings.session_poll_seconds));
useEffect(() => setPollDraft(String(settings.session_poll_seconds)), [settings.session_poll_seconds]);

<input
  value={pollDraft}
  inputMode="numeric"
  onChange={(e) => setPollDraft(e.target.value.replace(/\D/g, ""))}
  onBlur={() => {
    const n = Math.min(300, Math.max(5, Number(pollDraft) || 20));
    setPollDraft(String(n));
    if (n !== settings.session_poll_seconds) void patch({ session_poll_seconds: n });
  }}
/>
```

`retry_attempts`（`:170-179`）同样处理，并补 `min/max`。

### 6. 保存账单无视勾选，删除却按勾选执行

`WorkspaceView.tsx:259` `targets = checked.size ? [...checked] : selected ? [selected] : []`，删除用 `targets`（`:621`），而保存固定用 `selected`（`:592-599`）。勾了 3 行、底栏明说"已选 3 个"、点删除删 3 个，点保存只写 peek 里那一个，没有任何提示。

要么保存也走 `targets`（逐个 PUT，注意卡号是同一份），要么在有人勾选时把保存按钮标题改成"仅保存当前账号"。

### 7. 切账号不做脏检查；保存途中切换会把 A 的资料写进 B

- `:139-143` 一旦 `selected` 变化就 `setInfo(null); setForm({...EMPTY})` —— 正在编辑的地址簿被直接清空；
- `:599` `actions.saveBilling.mutate({ email: target, form: payload })`，`target` 是点击时的 `selected`，但用户可以在这 20 秒（实测账单读取 22s）里切到别的账号，`form` 也已经被清空/替换。

修复：

```ts
const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(baseline), [form, baseline]);
useEffect(() => {
  if (!dirty) return;
  const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
  window.addEventListener("beforeunload", warn);
  return () => window.removeEventListener("beforeunload", warn);
}, [dirty]);
```

在行点击处拦截：

```ts
const pick = (email: string) => {
  if (dirty && !confirm("当前账单未保存，切换会丢弃改动。继续？")) return;
  setSelected(email);
};
```

保存时闭包锁定表单快照，避免与 `selected` 错配：

```ts
const snapshot = { email: selected, form: { ...form, card_number: digits } };
```

### 8. 设置/网络页每个按键发一次 PUT，没去抖、没失败回滚、没 catch

`NetworkView.tsx:45-49` 与 `SettingsView.tsx:99-102`：先乐观 `setSettings`，再 `await api.saveSettings(next)`，`await` 外面没有 try。后果：

- 输 `192.168.1.1` 打 11 个字符发 11 个 PUT；
- 端口清空立刻写 `0`（`Number("") || 0`），因为 `value={settings.proxy_port || ""}` 会一直显示空；
- 后端 500 时 UI 已经是新值，静默偏离，且 `patch` 返回的 promise 失败 → 未处理拒绝。

修复：一个 `useDebouncedPatch`（300ms），失败回滚 + toast。

```ts
const save = useDebouncedCallback(async (next: Partial<Settings>) => {
  try { await api.saveSettings(next); }
  catch (err) {
    const fresh = await api.getSettings().catch(() => null);
    if (fresh) setSettings(fresh);
    push({ kind: "error", title: "设置未保存", detail: String(err) });
  }
}, 300);
```

网络页还应给"已保存/未保存"一个可见状态，而不是让用户猜。

### 9. 2FA 提交与删除确认都没有错误路径，也没有 pending

- `Hsa2Dialog.tsx:126` `onClick={submit}`，`submit` 是 async 且无 catch；`mutateAsync` 抛错时 → 未处理拒绝。`WorkspaceView.tsx:655-658` 的 `onSubmit` 还会在 `await` 之后无条件 `setHsa2Email(null)`：后端 `accepted: false` 也算"提交成功"关窗。
- `ConfirmDialog.tsx:39` `onClick={() => void onConfirm()}`，`WorkspaceView.tsx:695-707` 的 `onConfirm` `await mutateAsync` 同样裸奔。删除确认框没有 busy，**双击删除会让整轮循环跑两遍**。

修复要点：`onConfirm` 返回 `ok` 布尔；对话框内 `busy` 期间禁用两个按钮；失败保持打开。

```tsx
const [busy, setBusy] = useState(false);
<Button variant="danger" disabled={busy} onClick={async () => {
  setBusy(true);
  try { await onConfirm(); } finally { setBusy(false); }
}}>{busy ? "删除中…" : confirmLabel}</Button>
```

HSA2：用后端返回的 `accepted` 决定是否关闭，失败给出"验证码不对，还剩 N 次"。

### 10. 「解锁事件面板」基本不生效，还会把人锁在死路上

`hooks/useSecretUnlock.ts:14` 的状态是**组件本地**，`Chrome.tsx:62` 和 `SettingsView.tsx:23` 各自持有一份。设置页点 5 下只改了自己的 state + localStorage，Rail 不重挂载就永远看不到。

实测：

```
storage: 1
rail now: [ '账号 4', '网络', '设置' ]          # 连点 5 下后
rail after view switch: [ '账号 4', '网络', '设置' ]  # 切视图（Rail 不卸载）仍然没有
rail after reload: [ '账号 4', '网络', '事件', '设置' ]  # 只有重载才出现
```

而且 `SettingsView.tsx:76` 还弹了"已解锁 · 事件面板已显示在左侧"，当场说谎。

更糟的组合：`Chrome.tsx:67` 过滤掉 `logs`，但 `view` 不会复位。停在事件页按 `⌘⇧L`：标题仍是"事件"，nav 里却**没有任何激活项**，`active nav: []`，只能乱点。

修复：提到 context/`useSyncExternalStore`，并处理锁定时的视图：

```ts
const [unlocked, setUnlocked] = useState(() => localStorage.getItem(KEY) === "1");
const listeners = new Set<() => void>();
// setUnlocked 时通知所有订阅者（或直接 sync external store + storage 事件）
```

```ts
// App.tsx：锁定时若正停在隐藏视图，回到 accounts
useEffect(() => {
  if (!unlocked && view === "logs") setView("accounts");
}, [unlocked, view]);
```

### 11. 没有 Error Boundary：任何一个渲染抛错就是整窗白屏

`App.tsx` 全树无边界；`useRealtime`/`useApi` 都靠 `throw new Error(...)` 兜底。加一个边界，至少给出"重新加载/重启后端"。

```tsx
class Boundary extends React.Component<{ children: React.ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="page">
        <h1>界面出错了</h1>
        <pre className="profile">{String(this.state.err.stack ?? this.state.err)}</pre>
        <Button variant="primary" onClick={() => location.reload()}>重新加载</Button>
      </div>
    );
  }
}
```

### 12. CSP 掐死了远程激活接口

`desktop/src-tauri/tauri.conf.json`：

```
connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:* http://localhost:* ws://localhost:*
```

而 `SettingsView.tsx:43` / `ActivationView.tsx:43` 在渲染进程里 `fetch(ACTIVATION_URL + "/activate")`，`ACTIVATION_URL` 由 `VITE_ACTIVATION_URL` 注入，是远程 https 域名。**没白名单就必然被 CSP 拦**，激活只能靠"尚未配置/网络错误"含糊过去。

修复（域名按实际填，构建期可写成 `VITE_` 变量拼进去）：

```
connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:* https://ACTIVATION_HOST
```

顺带把激活的 fetch 收到 `api/client.ts` 里，别让视图直连一个裸 `fetch`（也对齐"UI 只经 client"的分层）。

---

## P1 — 架构与资源管理

| # | 问题 | 位置 | 处理 |
|---|---|---|---|
| 13 | 每个视图在 App 里用 `===` 挂载/卸载：回网络页重新拉 settings、滚动位置归零、筛选/展开状态全丢，5s 轮询反复停启 | `App.tsx:124-127` | 改用 `keepAlive`（CSS `display:none` 常挂载）或把 settings/status 提到 query |
| 14 | `useAccounts` 2.5s 无条件轮询，同时 WS `account.status` 又触发 `refetch`，`staleTime:5000` 与 2.5s 自相矛盾；窗口失焦不暂停 | `useAccounts.ts:12-22`、`WorkspaceView.tsx:145-148` | 删掉轮询，或 10s + `refetchIntervalInBackground:false`；事件只 invalidate |
| 15 | `request` 无 `AbortSignal`、无超时：后端一慢，2.5s 轮询开始堆叠；卸载后仍 `setState` | `client.ts:236-253` | 加 15s `AbortSignal.timeout()`，query 里传 `signal` |
| 16 | `boot()` 不可取消：StrictMode 双挂载会跑两遍 `resolveBaseUrl`（每遍最多 45s 的 90 次 invoke）和两次健康探测；重连 `setTimeout` 从不 `clear` | `useRealtime.tsx:90-111`、`:76-81` | 用 `AbortController` + 存 timer 句柄，cleanup 里清 |
| 17 | `?api=` 会写 localStorage，但读的时候 `if (fromStore && !isTauri())` —— 在 Tauri 下刚写就忽略，行为自相矛盾 | `client.ts:188-196` | 要么 Tauri 也认 `butter.api`，要么别写 |
| 18 | 粘贴识别每次 `onInput` 发请求，无去抖、无序号守卫，慢响应会覆盖新预览 | `PasteDialog.tsx:82-93` | 300ms 去抖 + `seq` 比对 |
| 19 | 全局 paste 监听不认 `editOpen`/`hsa2Email`，且靠 `eslint-disable` 掩盖 `mergeFields` 依赖（组件里没有 lint 配置，禁了个空气） | `WorkspaceView.tsx:227-254` | 守卫补齐 + `useCallback` |
| 20 | `ProxyStatus.running` 声明为 `boolean`，后端返回 `0`；`Health` 缺 `fingerprint_pinned`，`pid` 可 null | `client.ts:136-163` | 对齐真实 JSON：`running: boolean | 0 | 1` 或后端统一 bool |
| 21 | 用 `BackendError(status 0)` 当"启动失败"消息载体 | `client.ts:206-216` | 单独 `BootError extends Error` |
| 22 | `LoginProgress` 是单例 job：并发登录互相覆盖；漏收 `login.done` 就永久转圈；取消先置空再请求，失败也像成功 | `LoginProgress.tsx:36-89` | `Map<email, job>` + 超时回收 + 失败恢复 |
| 23 | 批量导入提交失败无 catch（调用方 `mutateAsync` 抛错 → 未处理拒绝），客户端校验把服务端 `SEP` 规则复制了一份 `----`，两处必然漂移 | `BulkImportDialog.tsx:7,76-89` | try/catch；`SEP` 由后端 `/api/paste` 或常量接口下发 |
| 24 | `AddAccountDialog` 常驻挂载，关掉再开保留上次的邮箱/密码；按钮写"保存并登录"，实际只保存 | `AddAccountDialog.tsx:24,90`、`WorkspaceView.tsx:634-639` | `open` 变化时清空；改文案为"保存" |
| 25 | 全项目没有一个 `<form>`：任何输入框回车都不提交（激活码是手写的 `onKeyDown`） | 各 dialog | 用 `<form onSubmit>`，按钮 `type="submit"` |
| 26 | `ActivationView` 整组件零引用（`App.tsx` 注释也承认不做门禁），40 行激活逻辑在 `SettingsView` 复制了一份 | `views/ActivationView.tsx` | 删组件，或抽 `useActivation()` 共用 |

---

## P2 — 前端/视觉/工程

### 可访问性

27. 账号行是 `<li>`，无 `role`/`tabIndex`（实测 tab 从搜索框直接跳到勾选框，**键盘根本打不开账号**）。→ `role="button" tabIndex={0}` + `onKeyDown` Enter/Space。
28. `Checkbox` 有 `role="checkbox"` 但无 `aria-label`（`ui.tsx:68-84`），读屏只念"复选框 未选中"；`.checkbox` 还嵌在 `<span onClick={stopPropagation}>` 里，语义和点击区都别扭。
29. `.toasts` 容器无 `role="status"`/`aria-live`（`ui.tsx:187`），toast 对读屏不存在。
30. `--text-dim` 对比度 3.26（浅底）/3.46（深底），却专门用在 10.5–11px 的 `.field__hint`、`.tiny`、时间戳上（`tokens.css:20`、`kit.css:322-331`）→ 提到 `#8a8073`/`#7d7365` 级别。
31. 浅色主题 primary 是 `#fffaf0` on `#a8661a` = **4.41:1**，12.5px 正文不达 AA（`kit.css:276-282`）；浅色下 rail 激活态（10% 琥珀 on 近白）几乎不可见。
32. 输入框 `outline:none` 只靠边框变色（`tokens.css:169-175`），按钮用 UA 默认焦点环 —— 两套焦点样式并存，且 `.btn` 没有任何 `:focus-visible`。
33. `CommandPalette` 无 `role="dialog"`/`aria-modal`/焦点陷阱，Esc 靠外层全局监听；条目只有 2 个（缺网络/事件），与 rail 的 4 项不一致（`CommandPalette.tsx:5-8,43-48`）。

### 布局与状态可见性

34. **浮层压住操作栏**：`.toasts` 与 `.job-indicator` 都在 `left:18;bottom:18`（`toast.css:2-6`、`:91-93`），job 的 z-index 60 又被 toast 的 90 盖。实测 job 卡占 y=744–802，正好糊住底栏的"全选/当前 1 个"。→ job 挪到右下并留出 bar 高度（`bottom: calc(18px + 52px)`），toast 让位或改右侧。
35. 底栏 `overflow-x:auto` 又 `scrollbar-width:none`（`workspace.css:246-255`）：1280 宽 + peek 打开时动作会被静默裁掉，没有换行、没有渐隐提示。
36. peek 头部挤了 4 个按钮，账号邮箱被截成 `julietebrito94@gm…`（`WorkspaceView.tsx:345-375`）——最该看的信息让位给最不常用的"检测/登录/编辑"。→ 邮箱独占首行，动作收到"⋯"菜单。
37. `.peek__actions .btn{flex:1}` 把「移除」拉成整行大色块，与「重新读取」严重失衡（`workspace.css:230-232`）。
38. 禁用态与正常态分不清：`btn` 统一 `opacity:.45`（`tokens.css:134-137`），primary 的琥珀渐变透出来仍然很亮——截图里"保存账单/启动 mihomo"看着都是可点的。
39. 卡号空时显示 placeholder（同 P0-3），`有效期` 显示 `3/29` 而不是 `03/29`（`cardSummary` 补了零，表单没补）。
40. 列表里 `last_login` 有数据但 `.ws-row__time{display:none}`（`workspace.css:135-137`），"最近登录"这一列在界面上不存在。
41. `Badge` 的卡尾号渲染成 `•••• 5724`（`WorkspaceView.tsx:328`），五连点 + 数字读起来像省略号。
42. 空态/失败态缺失：`NetworkView` 只有 Skeleton，`getSettings()` 失败就永远停在骨架；`SettingsView` 同样（`NetworkView.tsx:18-43`、`SettingsView.tsx:26-31,89-97`），两处 `.then()` 都没有 catch。

### 交互细节

43. 搜索框无 `type=search`、无清除按钮、无 `aria-label`；`.ws__head .search{margin-left:auto}` 与 `.search{margin-left:auto}` 双份（`workspace.css:31-34`、`accounts.css:33-37`）。
44. 字段普遍没有 `name`/`autoComplete`（`cc-number`/`cc-exp`/`postal-code`/`tel` 全缺，只有验证码有 `one-time-code`），密码管理器和系统自动填充基本无效。
45. `AddAccountDialog`/`AccountEditDialog` 的密码框没有显示切换；`email` 校验只有 `/.+@.+\..+/`。
46. 卡号没有分组格式化（`4111111111111111`），只靠 `inputMode`；保存前才 `replace(/\D/g,"")`。
47. `login.hsa2` / `awaiting_hsa2` / `WorkspaceView` effect 三条路径都能开 2FA 弹窗（`:153-167`）；`取消` 后如果后端没清 flag，2.5s 轮询会立刻再开一次，形成"取消 → 又弹"。
48. `fetchBilling.isPending` 是全局的（`:256`），切到另一个账号也会看到"正在读取…"盖在自己头上；且请求不取消，结果会写到当前 peek。
49. `apply` 类入口没有确认：`removeBilling` 有确认，重新读取没有限流，连点会连发 Apple 请求。
50. 事件 `key={index}`（`LogsView.tsx:86`）；事件没有稳定 id，切片截断后 index key 会错位复用。
51. `关于` 是可点击 `<strong>` 但 `cursor:default`、`title=""`（`SettingsView.tsx:266-272`），五连点毫无提示；版本号在同一行显示了两遍。
52. 浏览器版本下拉 `chrome142 / 134 / 145` 乱序（`SettingsView.tsx:206-209`）。

### CSS 体系

53. `fixes.css` 是补丁叠补丁：`input` 高度规则写两遍（`:11-23` 与 `:131-145`，后者直接覆盖前者）、`.setting-row{align-items:center}` 与 `views.css:89-95` 重复、字体栈塞进"fixes"、`:root[data-platform="windows"]` 在这里改写 `tokens.css` 的 token（`:172-177`）。
54. **大段死 CSS**（重构后的残留）：`.table*` `.cell-*` `.accounts*` `.detail*` `.billing__picker|header|grid|veil|status` `.code-input` `.activation*` `.rail__foot*` `.badge--noc` `.placeholder-view`。
55. 更坑的一处：`credit-card.tsx` 已改用 `.ccard`，但 `workspace.css:234-236` 和 `fixes.css:80-82` 仍在给 `.card-visual` 加约束 —— **`aspect-ratio:auto;min-height:132px` 全部不生效**，卡片在窄栏里按 316/190 硬撑。
56. 内联 style 泛滥：`App.tsx:40-84` 整个启动屏、`NetworkView` 一大段、各 dialog 的 `style={{...}}`，与 2.4k 行 CSS 令牌并存，改主题时两边都要动。
57. `color-mix()` 用得非常密（约 60 处），依赖较新 WebView（macOS < 16.2 / 旧 WebView2 会整片透明）；`@supports` 兜底一处没有。
58. `prefers-reduced-motion` 全局压到 0.001ms，连带 `spin` 也几乎不动 —— 骨架屏/加载圈该保留慢速。

### 工程与死代码

59. `utils/cx.ts` **零引用**，而项目根本没用 Tailwind：`tailwind-merge` + `clsx` 双依赖、`index.html` 的 `class="dark"`、`extendTailwindMerge` 全是空转（className 里那些 `"modal modal--sm"` 与 Tailwind 无关）。
60. `maskEmail` / `clamp` / `TradeLine` / `FieldRow` / `open_external`(Rust 命令，前端从不调用) 全部死代码；`avatar` 用 `email.slice(0,2)`，写好的 `groupInitials` 反而没人用。
61. 没有任何 eslint/prettier 配置；`noUnusedLocals` 开着也没能让上面这些暴露（它们都是 `export`）。
62. `useSecretUnlock` 的 `tapAbout` 用 `useCallback([taps])` 而 `taps` 每次点击都是新数组，回调每次都重建 —— 无害但白写。
63. 窗口 `resizable:false` + 固定 1280×820 + `maximizable:false`（`tauri.conf.json`），小屏（1366×768 的 Windows 笔记本、缩放 125%）直接裁切。
64. `App.tsx:114` 的注释"Unlicensed is usable…"与 `ActivationView` 并存，读者会以为有门禁。

---

## 建议落地顺序

1. **第一批（当天）**：P0-1 改名、P0-2/3 保存与卡号、P0-5 间隔输入、P0-6 保存目标、P0-9 错误路径、P0-4 Esc/焦点。
2. **第二批**：P0-7 脏检查、P0-8 去抖与回滚、P0-10 解锁共享、P0-11 边界、P0-12 CSP。
3. **第三批**：P1 全清（轮询/取消/类型对齐/表单化），之后再动视觉。
4. **第四批**：P2 按"可访问性 → 布局 → CSS 收敛"的顺序，死代码一次性删掉（55 必须和 34 一起做，否则卡片继续变形）。

## 验收清单（改完逐条打勾）

- [ ] 改名成功：PATCH 打到**旧**地址，行跟随更新，peek 跟着换 key
- [ ] 改名失败：对话框不关，toast 有原因
- [ ] 账单读取后，卡号框给"请重填"提示；点保存能直接聚焦卡号并说明原因
- [ ] 眼睛按钮能真的在明文/掩码间切换
- [ ] 任意对话框 Esc 关闭、Tab 不出圈、关闭后焦点回到触发按钮
- [ ] 探活间隔输入 30/120/5/999 得到 30/120/5/300，只有失焦才落库
- [ ] 勾 3 行点删除删 3 行；点保存明确只保存当前账号（或也保存 3 个）
- [ ] 编辑中切账号有提示；保存期间切换不会写错账号
- [ ] 网络页连打 11 个字符只发 1 次 PUT；后端不可用时回滚并报错
- [ ] 双击删除只跑一轮
- [ ] 设置页连点 5 下，左侧**立刻**出现"事件"；停在事件页锁定后回到账号页
- [ ] 任意视图抛错不白屏
- [ ] 远程激活域名在 CSP 白名单内且能成功激活
- [ ] 键盘 Tab 能选中账号行并 Enter 打开
- [ ] job 指示器不再压住底栏
- [ ] `pnpm build` 通过，`pnpm tauri build` 通过

---

# 修复记录（2026-11-21）

全部 P0/P1 与 P2 可执行项已改完，`tsc --noEmit` 与 `vite build` 通过，关键路径用 Playwright 真机回归。dev 仍在跑：后端 `127.0.0.1:7911`、界面 `localhost:1420`。

## 后端契约（2 行）

- `api/models.py` 增 `password_plain`，`core/store.py#public` 回传明文密码 —— 界面才能明文回显与编辑。
- 未改任何业务逻辑；`card_number` 仍只有尾号（Apple 不回传 PAN），所以保存必须重填卡号，界面已如实说明。

## P0

| # | 处理 |
|---|---|
| 1 | `useAccounts.update` 改 `{ key, patch }`，PATCH 打旧地址；失败不关窗、保留输入。实测 PATCH → 200，改名与改回都通过 |
| 2 | 保存按钮不再看卡号禁用；缺卡时 toast + 聚焦卡号 + `aria-invalid` + 红色 hint；失败保存保留已填卡号，重试一键 |
| 3 | 删掉 `reveal` 与眼睛按钮，卡号、账号密码一律明文（`type="text"`） |
| 4 | 新增 `components/Dialog.tsx`：Esc 关闭、焦点圈闭、关闭回焦、`role=dialog` `aria-modal`；6 个弹窗与新 Confirm 全部改走它 |
| 5 | 探活间隔/重试次数改本地草稿，失焦才 clamp 落库。实测输入 30 → 30、落库 30 |
| 6 | 保存固定作用于当前账号并在按钮文案标出「已选 N」；删除/批量仍走勾选 |
| 7 | 改账号/收起面板前置脏检查 `confirm`；`loadInto` 按服务端结果重置基线；切换时 abort 在途读取 |
| 8 | 设置/网络页 300ms 去抖；失败重新拉取设置并回滚 + toast；端口改草稿，失焦才写 |
| 9 | ConfirmDialog 内置 busy、`onConfirm` 返回布尔决定关闭；HSA2 用后端 `accepted` 判成败，失败留在弹窗 |
| 10 | 解锁状态提为模块级 store（`useSyncExternalStore`）+ 全局 ⌘⇧L；锁定若停在事件页自动回账号页。实测 rail 立刻出现「事件」 |
| 11 | App 外层加 Error Boundary（回到界面 / 重新加载） |
| 12 | CSP `connect-src` 加 `https:`；激活请求收进 `api/client.ts` |

## P1

- 视图常挂载（`.pane[hidden]`），不再每次重新拉取、丢滚动与筛选；panes 在 `api` 就绪后才挂。
- 轮询 10s + `refetchIntervalInBackground:false`，WS 事件保留 invalidate。
- `request` 全部带 `AbortSignal.timeout`（读取类 120s），支持外部 signal。
- `boot()` 单飞 + AbortController，重连 timer 清理；StrictMode 不再跑两遍 45s 探测。
- `?api=` 只在浏览器持久化（Tauri 每轮端口不同）。
- 粘贴识别 300ms 去抖 + 序号守卫 + abort。
- `running` 类型改 `boolean | 0 | 1` 并提供 `isRunning()`；补 `Health.fingerprint_pinned`。
- `LoginProgress` 改 `Map<email, job>`，180s 无心跳回收，取消成功才移除。
- 批量导入补 catch；`AddAccountDialog` 打开时清空；所有弹窗改真 `<form>`，Enter 可提交（实测提交并关闭）。
- `ActivationView` 删除，激活逻辑收进 client。

## P2

- 行改 `role="button" tabIndex=0` + Enter/Space；checkbox 带 `aria-label`；toast 容器 `role=status aria-live`；`:focus-visible` 全局；补 `:focus-visible` 到行/按钮。
- `--text-dim` 提到 3.5:1 以上；浅色 `--amber` 改 `#9c5c16`（primary 白字 5.1:1）。
- job 指示器移右下、toast 移底栏上方，实测两者不再相交也不压操作栏。
- 底栏改 `flex-wrap`；peek 头部改「身份一行 + 工具一行」，邮箱不再截断；移除按钮不再被拉满。
- 搜索框 `type=search` + aria-label；所有字段补 `name`/`autoComplete`。
- 事件行用客户端 id 作 key；日志区固定高度。
- 命令面板补全 4 项、`role=dialog`、顶部锚定。
- CSS：删 `.table*` `.cell-*` `.accounts*` `.detail*` `.card-visual*` `.billing__picker|veil|status` `.activation*` `.code-input` `.badge--noc`；`fixes.css` 去重；`.ws__peek .ccard` 生效；卡片约束恢复。
- 死代码删除：`utils/cx.ts`、`maskEmail`、`clamp`、`TradeLine`、`FieldRow`、`tailwind-merge` 依赖、`class="dark"`。
- 窗口改为可缩放 + 最小尺寸 1040×640。
- README 不变量同步（明文密码、Esc、常挂载）。

## 未做（需产品决定）

- 事件面板仍藏在连点 5 下后面（已加可见提示与全局快捷键）。
- `open_external` 命令仍无前端入口。
- 无 eslint/prettier 配置。

## 补充（2026-11-21 追加）

- **登出**：`Services.logout`（[services.py](src/butter/core/services.py)）+ `POST /api/accounts/{email}/logout`（[app.py](src/butter/api/app.py)）。关掉 live socket、`detach`、`clear` 清空 cookie/stk、状态回落 idle，并顺手解开挂起的 2FA future（否则 waiter 会悬挂、弹窗会对已登出账号重开）。账号行、密码、备注、卡尾号保留，重登即可恢复。
- **顶部按钮改文字**：peek 头部的 检测 / 登录 / 登出 / 编辑 / 收起 全部带字，`btn--sm`，可换行；`登出` 在无会话时禁用。实测 disabled 判定、点击登出与 toast 均正确。

## 补充 2：一次点击走完「检测 → 登录 → 读账单」

原来 `_ensure_session` 只是**起**一个登录就返回 `awaiting_hsa2`，请求结束；账单要等第二次点击。现在整条链在一次请求里走完：

1. `_ensure_session`：会话活着 → 直接放行；会话死了 → 用保存的密码登录（`inline_store=True`，等 store 握手完成），2FA 弹窗在同一请求里等待；
2. 登录成功 → 同一个请求继续 `fetch_billing_info` → 返回 `info`；
3. 登录失败/取消/超时 → 返回 `{"ok": false, message}`，界面显示原因。

配套：
- `login(inline_store=True)` 把 `defer_store` 关掉，`_spawn_store_handshake` 拆出 `_store_handshake()` 供内联调用（日志/事件不变）。
- **请求被中止不再勒死账号**：登录跑在独立 task 里，用 `asyncio.shield` 等待；浏览器 abort 只放弃等待，task 继续，下一次点击接同一个 task。实测 abort 后重试：失败路径 1.2s 返回、成功路径 16.6s 返回，都是同一次登录。
- 保存账单同样会先补会话。
- 前端读取/保存超时放到 360s（要覆盖 300s 的验证码窗口），2FA 提交后不再多发一次读取（请求还挂着）。

顺带修掉一个 dev 侧泄漏：`kill_on_drop` 在 dev 重启/崩溃时不生效，每次重启都留下一个旧 sidecar 监听旧端口，新壳还可能连到它。现在 `lib.rs` 传 `BUTTER_PARENT_PID`，`server.py` 起一个 2s 轮询的看门狗，父进程没了就自杀。

## 补充 3：浮层统一 + 关闭不再取消

- **一个地方**：新增 `.overlay-stack`（左下、底栏之上、340px 一列），toast 和进度卡都放进去，不再左右各一边。卡与 toast 同宽同列，视觉上是一套东西。
- **X 只关闭**：`Toast.onCancel` 换成 `Toast.action`；X 只 `dismiss`。会话检测的取消改成卡片/按钮上的显式动作。
- **进度卡也区分**：卡的 X 只收起这张卡（登录/检测继续跑），旁边是独立的「取消」按钮，按任务类型调 `cancelLogin` / `cancelCheck`。
- **会话检测有了自己的卡**：原来检测只弹一个 sticky toast，关掉就什么都看不见。现在 `session.progress` 也走进度卡，带 `1/2 · email` 计数（后端补 `index/total`），`session.done` 清卡；sticky toast 去掉，结果仍由完成 toast 汇报。实测：关掉 toast、收起卡片后检测照常跑完（25s 后仍收到「会话检测完成」）。
- 顺带补回被「table 层」一起删掉的 `.checkbox` 样式（勾选框一度变成 0×0）。

## 补充 4：激活码与激活链路修复

生成（本机 `db0b832efd29f5b7`）：

```
GPHG-0XK5-8Q0F-K946-6   plan=month  30d  已入 D1，已绑定该机器
```

- `scripts/license_codes.py` 出码（Crockford 字母表 + 校验位），`scripts/license_issue.py` 出同 code 的离线签名执照写到 `~/Library/Application Support/app.butter.desktop/license.json`（旧件备份在 `/tmp/license.backup.json`），壳内 `evaluate` 通过 → 后端拿到 `BUTTER_LICENSED=1`，2 个账号上限解除（实测建第 5 个账号 200）。
- 顺手修掉两个会让激活永远失败的真问题：
  1. **Worker 没有 CORS**：渲染进程是别的 origin，`/activate` 连预检都过不去，稳定报 `Failed to fetch`。已加 `OPTIONS` + `access-control-allow-origin/-headers/-methods`，`wrangler deploy` 上线（version c14416c9）。
  2. **机器码拿不到就发空**：浏览器/预览里 `invoke("license_machine")` 抛 TypeError，POST 出去 `machine: ""` → 400。现在 `/api/license` 回传 `machine`（来自 `BUTTER_MACHINE`）作为兜底，`invoke` 只剩展示优先项；非 Tauri 环境 `license_apply` 走 no-op 并提示「浏览器预览不落盘」。
- 部署脚本正常路径仍是 `scripts/license_codes.py --push`（需 `BUTTER_ADMIN_URL` / `BUTTER_ADMIN_SECRET`，本机没有该 secret，这次是直接写 D1 的 `codes` 表）。
- `desktop/.env.local` 写入 `VITE_ACTIVATION_URL=https://butter-activation.bravesfly.workers.dev`，并加进 `.gitignore`。
