# 代理怎么用

Butter 只做一件事：**决定每个 Apple 请求从哪个 IP 出去**。界面里的「网络」页就是全部开关，改完立刻生效，存在 `~/Library/Application Support/butter/settings.json`。

---

## 0. 先理解一件容易踩坑的事

应用是**独立进程**，不继承你终端的代理环境变量。所以：

- 你在终端里 `export HTTP_PROXY=...` **不会**影响 Butter；
- 但如果你从终端启动它，`http_proxy / https_proxy / all_proxy` **会被 curl 底层读到**——我已经在代码里默认剥掉了（`BUTTER_IGNORE_ENV_PROXY=1`），
  所以「直连」是真直连。
- **macOS 系统代理（系统设置 → 网络 → 代理）也不影响它**，因为 curl_cffi 不读系统代理配置。

实测（同一台机器）：

```
no-proxy    ip=120.37.212.164  country=CN    ← 剥掉环境变量后，真直连
via-relay   ip=189.24.123.153  country=US    ← 走 SOCKS5 后，IP 变了
```

---

## 1. 三种模式

「网络」页顶部三个按钮：

| 模式 | 什么时候用 | 填什么 |
|---|---|---|
| **直连 / 自定义** | 本机就能直连 Apple；或你只有一个现成的代理 URL | 代理 URL（留空=纯直连） |
| **固定代理** | 你有机场/公司代理的 host+port+账号 | 上游主机 / 端口 / 类型 / 用户名 / 密码 |
| **本机 Clash** | 你已经在跑 Clash/ClashBar/Clash Verge（内核就是 mihomo） | 控制接口 + SOCKS 入站（默认 127.0.0.1:9090 / socks5h://127.0.0.1:7890） |
| **独立 mihomo** | 不想用现成客户端，或要「跳板链」 | 上游同样的字段 +（可选）HK 节点池 |

---

## 2. 直连 / 自定义（30 秒可用）

**纯直连**：`proxy_mode = direct`，URL 留空 → 什么都不走。

**用一个现成代理**（最常见的 Clash / Surge / V2Ray 本机端口）：

```
proxy_mode = direct
proxy_url  = socks5h://127.0.0.1:7890
```

支持的写法：

```
socks5h://host:port        ← DNS 也走代理（推荐，避免本地 DNS 泄漏/污染）
socks5://host:port         ← 本地解析 DNS
http://host:port           ← HTTP CONNECT
https://host:port
http://user:pass@host:port ← 带认证
```

> `socks5h` 里的 **h** 很重要：Apple 的域名会因为本地 DNS 结果不同而跳到不同边缘节点，用 `h` 让代理端解析。

验证方式：在「事件」页看日志，或让某个账号跑一次登录，日志里会出现 `[LoginFlow]` 起始行；也可以在终端里对照：

```bash
curl -x socks5h://127.0.0.1:7890 https://ipinfo.io/json
```

两个 IP 一致就说明生效了。

---

## 3. 固定代理（host + 账号）

适合「机房代理 / 住宅代理」，尤其是那种 `user-session-xxxx:pass@host:port` 形式的。

```
proxy_mode = custom
proxy_host = gate.example.com
proxy_port = 1080
proxy_type = socks5        ← 或 http / https
proxy_user = youruser
proxy_pass = yourpass
line       = HK            ← 可选，UI 里叫「落地线路」
```

「落地线路」的作用：如果代理服务商支持在用户名里带区域后缀，Butter 会拼成

```
user-region-HK-sid-<会话id>-t-10
```

其中 `sid` 每个账号不同（取邮箱前缀），所以**同一代理账号下，不同 Apple ID 会走不同出口会话**——这是批量操作时避免被关联的关键。

如果你的服务商不吃这套后缀，把「落地线路」留空即可，就只用原始的 `user:pass`。

---

## 3.5 本机 Clash（推荐，复用已在跑的内核）

如果你的 Clash 客户端内核是 mihomo（Clash Verge / ClashBar / ClashX Meta 都是），
**不要**用「独立 mihomo」再拉一个内核——那会端口冲突、两套规则、两套 fake-ip DNS。

选「本机 Clash」，填三项：

```
proxy_mode  = clash
clash_api   = 127.0.0.1:9090                 ← external-controller
clash_socks = socks5h://127.0.0.1:7890        ← 你的 socks/mixed 入站
clash_group = 节点选择                        ← 要切的 Selector 组
clash_secret= （没设就留空）
```

能做什么：

- 「重新检测」→ 读 `/version`、`/proxies`，显示内核版本 / 组 / 节点数；
- 下拉选组 → 决定按钮作用在哪个 Selector 上；
- **HK / US / UK 按钮** → 在该组里按区域名后缀轮换（`美国01` → `美国02` …），
  批量跑账号时每跑一个换一个出口；
- 点节点名 → 直接切到该节点；
- 延迟徽章 → 绿 <300ms / 黄 较慢 / 红 不可用。

**为什么这比独立内核好**：规则只有一份。你的配置里通常有
`GEOIP,CN,DIRECT` 和一堆 `SRC-IP-CIDR`，独立内核会另建一套路由，Apple 的请求
可能走错分流；复用现成内核 = 你现在浏览器怎么走，Butter 就怎么走。

验证（本机实测）：

```
GET  /api/clash/status   → ok=true, 内核 v1.19.33, 5 组, 107 节点
POST /api/clash/rotate   → 美国01 → 美国02 → …（每次换一个）
Transport(proxy=socks5h://127.0.0.1:7890) → 出口 189.24.123.155 US
```

## 4. 独立 mihomo（多节点 / 跳板）

这是原工具的核心玩法，Butter 完整保留：

```
       Apple
         ▲
         │  出口 = HK 节点池里轮询出来的那个 IP
   ┌─────┴─────┐
   │  HK-LB    │  load-balance / round-robin
   └──┬──┬──┬──┘
      │  │  │     HK-1  HK-2  HK-3 …
      └──┴──┴──► ISP（你的上游代理，带账号）
```

配置步骤：

1. 模式选 **mihomo 链式**；
2. 填上游：主机 / 端口 / 类型 / 用户名 / 密码（就是你平常那个机场）；
3. （可选）在「HK 节点池」里加节点：`server` / `port` / `password`，类型默认 `ss`、加密 `aes-128-gcm`；
   - **加节点 → 就是链式**：请求先到 HK 节点，再由节点用 ISP 账号出网；
   - **不加节点 → 就是单跳**：等价于固定代理，只是套了 mihomo 的端口给你；
4. 点「启动」，右侧会显示 `运行中 / 端口 / PID`；
5. 点「预览配置」可以看到生成的 YAML，确认 `dialer-proxy: HK-LB` 挂对了。

生成的配置骨架（不含密钥）：

```yaml
mixed-port: 17890
allow-lan: false
mode: rule
proxies:
  - {name: HK-1, type: ss, server: ..., port: 443, cipher: aes-128-gcm, password: ...}
  - {name: ISP,  type: socks5, server: ..., port: 1080, username: ..., dialer-proxy: HK-LB}
proxy-groups:
  - {name: HK-LB, type: load-balance, strategy: round-robin, proxies: [HK-1], url: http://www.gstatic.com/generate_204, interval: 60}
  - {name: FINAL, type: select, proxies: [ISP]}
rules:
  - MATCH,FINAL
```

### 关于 mihomo 可执行文件

Butter 只负责生成配置和拉起进程，**不自带内核**。按这个顺序找：

1. `PATH` 里的 `mihomo` / `clash-meta` / `clash-verge-mihomo`；
2. 常见 App 内置的：`/Applications/Clash Verge.app/Contents/Resources/mihomo` 等；
3. 放到 `~/Library/Application Support/butter/mihomo/mihomo`。

找不到时会直接报「未找到 mihomo 可执行文件」，不会静默降级。

> **你现在的机器上就没有内核**，而且 `7890` 端口也没人在听（`lsof` 为空），所以 mihomo 模式点了「启动」只会立刻报错。
> 顺带一提：你的 `settings.json` 现在是 `proxy_mode: mihomo` 但上游全空 —— 这是 UI 上点了模式没填参数留下的，点「启动」必然失败。

---

## 5. 每个账号独立出口（重要）

不管哪种模式，业务层都会在代理 URL 上挂一个会话后缀：

```
sid = 邮箱前缀的前 8 个字符
最终用户名 = <原用户名>-sid-<sid>-t-10
```

意义：**N 个账号 = N 条独立会话**，代理服务商会给它们分配不同出口 IP，避免「同一条线路跑十个 Apple ID」带来的关联风险。这条逻辑在 `apple_auth/http.py::rotate_sid`，单测覆盖过（重复调用会替换旧 sid，不会叠加）。

---

## 6. 换节点排除法（登录报错时）

登录被限流 / 被拒时，网络是第一嫌疑：

| 现象 | 含义 | 处理 |
|---|---|---|
| `step2: signin/init status=503` | Apple 对你的**出口 IP** 限流 | 换节点，等 10–15 分钟 |
| `step3: Apple 边缘错误 502/504` | 边缘网关超时 / 被拦 | 同上 |
| `store.authenticate: 无法获取 ssi` | Store 会话没建立（cookie 没带上） | 先解决登录；登录成功后这里自然通 |
| 登录成功但账单页一直「会话过期」 | `myacinfo/as_disa` 没拿到 | 换出口重登 |

换法：固定代理改 `line`（HK/US）；mihomo 模式多加点节点让它轮询，或者直接换上游。

---

## 7. 三个常见误区

1. **「我开了系统代理，为什么 Butter 不走？」** —— 它不读系统代理，请在应用里填。
2. **「我填了 7890 但 IP 没变」** —— 多半是那个端口没人听（代理软件没开 / 换了端口）。先 `lsof -nP -iTCP:7890 -sTCP:LISTEN` 确认。
3. **「代理 OK 但登录还是 step3 失败」** —— 那就不是网络问题了，是凭据/协议层（目前已知的分歧点在 SRP 的 M1 计算，跟代理无关）。

---

## 8. 附：命令行直接验证

```bash
# 1) 代理端口是否在听
lsof -nP -iTCP:7890 -sTCP:LISTEN

# 2) 这个端口出去是什么 IP
curl -x socks5h://127.0.0.1:7890 https://ipinfo.io/json

# 3) 直连是什么 IP（对比用）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  curl -s https://ipinfo.io/json
```

两个 IP 不同 → 代理链路通；相同 → 代理没生效。
