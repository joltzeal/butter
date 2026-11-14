# Butter

Apple ID / Apple Store 账单控制台。Python 负责协议与会话，Tauri 只负责窗口与渲染。

```
butter/
├── src/butter/                # Python 后端（uv 管理）
│   ├── apple_auth/            # IDMSA / Store / iforgot 协议层
│   ├── core/                  # 账号库、代理、剪贴板解析、业务编排
│   ├── api/                   # FastAPI + WebSocket 控制面
│   └── server.py              # `uv run butter` 入口
├── tests/                     # pytest（35 项，纯离线）
├── desktop/                   # Tauri v2 + React 19 + TS 前端
│   ├── src/                   # 视图、hooks、样式
│   └── src-tauri/             # Rust 壳：拉起并守护 Python 子进程
└── scripts/build_sidecar.sh   # PyInstaller 单文件后端
```

## 架构

```
┌──────────────── Tauri WebView (React) ────────────────┐
│ 视图：账号 / 账单 / 网络 / 事件 / 设置                  │
│ 数据：@tanstack/react-query + WebSocket 事件流          │
└───────────────┬──────────────────────────────┬─────────┘
                │ invoke(backend_info)         │ fetch + ws
┌───────────────▼──────────────┐  ┌────────────▼─────────────┐
│ Rust shell (src-tauri)       │  │ FastAPI 127.0.0.1:随机端口 │
│ · 选空闲端口                  │  │ · REST + /ws 进度广播      │
│ · 拉起 Python 子进程并守护     │  │ · 账号库 / 代理 / 指标      │
│ · 退出时 kill                 │  └────────────┬─────────────┘
└──────────────────────────────┘               │
                                    ┌──────────▼──────────┐
                                    │ apple_auth 协议层    │
                                    │ SRP · SHLD · Store   │
                                    └─────────────────────┘
```

**为什么分两层**：协议逻辑（SRP 握手、风控 cookie、RSA-OAEP 卡号加密、两步确认）
需要成熟的 Python 加密与 HTTP 生态；UI 需要原生窗口与流畅动效。Rust 壳只做
进程生命周期，不参与任何业务判断。

## 从原始工具迁移过来的逻辑

| 原工具（Qt） | Butter（新） | 说明 |
|---|---|---|
| `xbzhan_auth` 卡密 + 心跳 | **已移除** | 本地工具不需要第三方授权 |
| `session_store`（accounts.json） | `core/store.py` | 原子写，密码落盘但接口脱敏 |
| `login_worker`（QThread） | `core/services.py::login` | 改成协程，进度走 WebSocket |
| `_login_helper.run_login_flow` | `apple_auth/idmsa_client.py` | 保留 5 步 SRP 与 409 分支 |
| `shld_solver` / `hashcash` | `apple_auth/hashcash.py` | PoW 与 SHA-PoW 两种挑战 |
| `store_client` | `apple_auth/store_client.py` | `accounthomex` RPC 全方法 |
| `billing_worker` / `fetch_billing_worker` | `Services.update_billing` / `fetch_billing` | 读取→移除旧卡→RSA→校验→保存 |
| `address_parser`（6 种格式） | `core/address_parser.py` | 另加 JSON 形态 |
| `mihomo_manager` | `core/proxy.py` | 生成 YAML + 进程托管，可单测 |
| Qt 反调试 + 日志 | 日志保留（`register.log` 语义改为标准 logging） | 去掉反调试：本地工具无需对抗自己 |

## 快速开始

```bash
cd butter
uv sync --extra dev           # 后端依赖
uv run pytest -q             # 35 项离线测试
uv run butter                # 单独跑后端（默认 127.0.0.1:7860-7960）

cd desktop
pnpm install
pnpm tauri dev               # Rust 壳自动拉起 Python 后端
```

开发态下 Rust 壳会向上查找包含 `pyproject.toml` 的仓库根，用 `uv run butter` 启动；
浏览器里直接开 `pnpm dev` 也能跑（前端会退回到 `127.0.0.1:7911`）。

### 打包

```bash
./scripts/build_sidecar.sh             # -> ../backend-dist/butter-backend
cd desktop && pnpm tauri build         # 产出 .app / .dmg / .msi / .deb / .AppImage
```

打包后的壳优先使用 `BUTTER_BACKEND` 环境变量，其次是 bundle 内的
`backend/butter-backend`，最后才回退到开发态的 `uv run`。

## API 概览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 版本、数据目录、代理状态、curl_cffi 可用性 |
| GET/POST/PATCH/DELETE | `/api/accounts[/{email}]` | 账号 CRUD（密码脱敏） |
| POST | `/api/accounts/login` | 登录（含 HSA2 交互） |
| POST | `/api/accounts/{email}/hsa2` | 提交 6 位验证码 |
| POST | `/api/accounts/batch-relogin` | 批量重登 |
| GET/PUT/DELETE | `/api/accounts/{email}/billing` | 读取 / 保存 / 移除账单 |
| POST | `/api/sessions/check` | 会话探活（可指定列表或前 N 条） |
| POST | `/api/paste` | 剪贴板账单解析 |
| GET/PUT | `/api/settings` | 代理、线路、重试、UI 偏好 |
| GET/POST | `/api/proxy/preview|start|stop|status` | mihomo 配置生成与进程托管 |
| WS | `/ws` | `login.*` / `billing.*` / `session.*` / `batch.*` 进度事件 |

事件信封固定为 `{"event": string, "payload": object, "ts": ISO8601}`。

## 设计取向

- **本地优先**：只监听 `127.0.0.1`，CORS 白名单限定 loopback 与 Tauri 协议头。
- **单一强调色**：暖琥珀用于"可操作"，其余用中性层次；没有渐变装饰、没有发光卡片。
- **状态即颜色**：在线/掉线/未读取各自一种 tone，表格里一眼可读。
- **键盘优先**：`⌘K` 命令面板，`Esc` 关闭任意浮层，表格行单击展开详情。
- **可回归**：协议层与解析层全部纯函数化，35 个离线用例覆盖卡号加密、SRP 摘要
  形状、6 种粘贴格式、代理 YAML 生成与结构化存储。

## 代理

详见 [docs/PROXY.md](docs/PROXY.md)：三种模式、每个账号独立 `sid` 出口、
mihomo 内核放置位置，以及"为什么系统代理不生效"。

## 已知边界

- 协议实现按原工具还原，Apple 侧风控策略变动时需要同步调整头部与挑战求解。
- iforgot 分支遇到图形 CAPTCHA 只做保存与提示，不做自动识别。
- mihomo 模式需要自备 `mihomo` 可执行文件（放入数据目录 `mihomo/` 或加入 PATH）。
