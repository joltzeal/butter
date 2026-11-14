# Butter — Apple Store 登录 / 账单协议

本文是 `src/butter/apple_auth/` 里协议实现的配套说明。所有结论都来自对线上接口的实测，不是推测。

---

## 一、全景

一次完整的会话要跨两个彼此独立的域：

```
idmsa.apple.com        身份认证（SRP + 两步验证）
    │  myacinfo / DES
    ▼
secureN.store.apple.com   商店会话（SHLD + authx）
    │  as_disa
    ▼
POST /shop/accounthomex   Graviton RPC（读 / 写账单）
```

**关键点：Apple ID 登录成功 ≠ store 已登录。** 两段会话互不相通，必须分别走完。

```
step0   authorize/signin        拿 aasp / session-id
        verify/device/key/challenge   建立 2FA 上下文
step1   federate                拿 hashcash 挑战
step2   signin/init             SRP 盐 + B
step3   signin/complete         M1/M2 → 409 hsa2
step4   securitycode            6 位验证码 → 204
step5   2sv/trust               → 204，myacinfo
step6   account/home → ssi      store 侧开始
step7   signIn/account          init_data.meta.h → x-aos-stk
step8   shld v3/q  GET + POST   → shld_bt_ck
step9   signIn/idms/authx       → as_disa
step10  accounthomex            Graviton 账单 RPC
```

---

## 二、IDMSA 阶段

### 常量

| 名称 | 值 |
|---|---|
| `WIDGET_KEY_STORE` | `a797929d224abb1cc663bb187bbcd02f7172ca3a84df470380522a7c6092118b` |
| `WIDGET_KEY_ACCOUNT` | `af1139274f266b22b68c2a3e7ad932cb3c0bbe854e13a79af78dcc73136882c3` |
| `X-Apple-Domain-Id` | **`39`**（固定，见下方说明） |
| `authVersion` | `8.0.2` |
| `SRP_k` | `05b9e8ef059c6b32ea59fc1d322d37f04aa30bae5aa9003b8321e21ddb04e300` |
| UA | Chrome/152 macOS |
| `Accept-Language` | `en-US,en;q=0.9` |

### `X-Apple-Domain-Id` 为什么不是页面里的值

`authorize/signin` 页的 boot_args 里带 `"domainId": 35`（或 39/42/49，每次不同）。**这个值不能当请求头用。**

实测对照：

| 页面 domainId | 请求头取值 | init 结果 |
|---|---|---|
| 35 | 35 | 400 |
| 35 | 39 | **200** |
| 35 | 42 | 400 |
| 35 | 11 | 503 |

请求头固定用 **39**。页面里的那个只影响静态资源版本号。

### 请求头

`step2` 及之后的最小可用集合：

```
Accept: application/json, text/javascript, */*; q=0.01
Accept-Language: en-US,en;q=0.9
Content-Type: application/json
Origin: https://idmsa.apple.com
Referer: https://idmsa.apple.com/
Sec-Fetch-Site: same-origin
Sec-Fetch-Mode: cors
Sec-Fetch-Dest: empty
X-Apple-Domain-Id: 39
X-Apple-Widget-Key: {WIDGET_KEY_STORE}
X-Apple-OAuth-Client-Id: {WIDGET_KEY_STORE}
X-Apple-OAuth-Client-Type: firstPartyAuth
X-Apple-OAuth-Redirect-URI: https://secureN.store.apple.com
X-Apple-OAuth-Response-Type: code
X-Apple-OAuth-Response-Mode: web_message
X-Apple-OAuth-State: {frame_id}
X-Apple-Frame-Id: {frame_id}
X-Apple-Locale: en_US
X-Requested-With: XMLHttpRequest
```

`frame_id` 格式：`auth-{8位}-{4位}-{4位}-{4位}-{8位}`，字符集为小写字母和数字。

### 会踩的坑

| 现象 | 原因 | 修法 |
|---|---|---|
| init 404 | 缺 `Accept` 头 | 补上。这一条最难查，因为其他头都齐了也不报错 |
| init 404 | init 阶段带了 `X-Apple-Auth-Attributes` | 只在 complete 之后带 |
| init 404 | `scnt` 用了 cookie jar 里残留的旧值 | 只认本轮响应 `set-cookie` 新下发的 |
| init 404 | `redirect_uri` 不是真实的 `secureN` 主机 | 先访问 `account/home` 解析出真实域名 |
| init 404 | authorize 之前先访问了 store | 调整顺序，先 authorize |
| init 400/404 | `X-Apple-Domain-Id` 不是 39 | 固定 39 |
| 503 | `Accept-Encoding` 与 `X-Apple-Privacy-Consent` 同时带 | 两者都不要带 |
| authorize 拿不到完整页 | `Sec-Fetch-Dest` 用了 `document` | 改成 `iframe` |

### SRP

Apple 用的是 SRP-6a 的私有变体，不能直接套 RFC 5054：

```
k  = H(N) ⊕ H(pad(g))          # 注意是 XOR，不是 RFC 的 H(N|pad(g))
x  = H(salt | H(":" | PBKDF2(password, salt, iterations)))
u  = H(A | B)                  # 不补零
S  = (B - k·g^x)^(a + u·x) mod N
K  = H(S)
M1 = H(H(N) ⊕ H(g) | H(account) | salt | A | B | K)
M2 = H(A | M1 | K)
```

`protocol` 字段可能返回 `s2k` 或 `s2k_fo`，两者 `PBKDF2` 处理一致；`iteration` 实测 `20919` ~ `20948` 之间浮动。

### hashcash

`federate` 响应头带 `X-Apple-HC-Bits` 和 `X-Apple-HC-Challenge`。提交时构造：

```
X-APPLE-HC: 1:{bits}:{YYYYMMDDHHMMSS}:{challenge}:{nonce}
```

`nonce` 需让 `SHA-1(整个串)` 的前导**零比特**数 ≥ `bits`。注意是比特不是十六进制位。

### 两步验证

```
POST /appleauth/auth/verify/trusteddevice/securitycode
body: {"securityCode": {"code": "123456"}}
头：  Content-Type: application/json
      X-Apple-App-Id: {WIDGET_KEY_STORE}
      scnt: {最新的 scnt}
```

- **必须带 `Content-Type` 和 `scnt`**，缺任一个都是 403 空响应体
- 验证码只能试一次，重复使用会 403
- 204 之后再 `POST /appleauth/auth/2sv/trust` 拿 `myacinfo`

---

## 三、Store 阶段

### ssi 的获取

```
GET /shop/account/home                          → 303  Location: https://secureN.store.apple.com/shop/account/home
GET {那个 Location}                             → 302  Location: .../shop/signIn/account?ssi=XXXX
```

两跳都要手动跟，不能开自动重定向，否则 `ssi` 会被吞掉。导航请求要用**裸头**：

```
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Sec-Fetch-Site: none / cross-site
Sec-Fetch-Mode: navigate
Sec-Fetch-Dest: document
Upgrade-Insecure-Requests: 1
```

不能带 `Origin`、`X-Requested-With`、`syntax` 这些 XHR 头，否则拿到的是落地页而不是重定向。

### x-aos-stk 从哪来

在 `signIn/account` 页面的：

```html
<script id="init_data" type="application/json">
{"meta": {"h": {
    "x-aos-model-page": "idmsSignInPage",
    "modelVersion": "v2",
    "x-aos-stk": "yAYh9qwNhtTKW4HvK8eSux5MxDcYgEkysfAJQG-VeR0",
    "syntax": "graviton"
}}, "signIn": {…}}
</script>
```

**只在 `meta.h` 里。** 直接在 HTML 里搜 `"x-aos-stk"` 也能命中，但会同时匹配到 CDN bundle，拿到的是别的 token，提交上去返回 541。

### SHLD 工作量证明

`authx` 之前必须先过这道闸，否则一律 **541**。

```
① GET /shop/shld/work/v3/q?jr=30
   Accept: /
   Referer: {base}/shop/signIn/account?ssi={ssi}
   Sec-Fetch-Site: same-origin / Mode: cors / Dest: empty

   → 200 {"challenge_version":3,"algorithm":"SHA-384","timeout":3000,
          "salt":"…","challenge":"…","t":1794558971.883,"signature":"…"}
   → 401 {"retry_interval":200,"retry_count":3}   还没准备好，等一会重试

② 求解：swap_tail4(SHA384(salt + str(n))).hex() == challenge
   n 在 0 ~ 1000000 之间暴力。实测 1~5ms 就能出结果。

③ POST 同一个 URL
   Content-Type: text/plain;charset=UTF-8
   body: 原挑战字段 + {
       "flagskv": {"patSkip": true, "patOkNoCk": false},
       "number": <解出的 n>,
       "took": <耗时毫秒>,
       "jsa": {"s":30,"f":["P"],"d":{"u":"c","p":1,"r":"oxxxxxo"}}
   }

   → Set-Cookie: shld_bt_ck=…
```

**`jr` 只能是 `30`。** 29 / 31 / `s3` / 空 全部 404。它和 `shld_bt_m` 的第一段不是同一个东西。

另一种挑战形态是乘积分解（`X` / `low` / `high` / `number`），代码里两个求解器都实现了。

### authx

```
POST /shop/signIn/idms/authx?ssi={ssi}
Accept: /
Content-Type: application/x-www-form-urlencoded
Origin: {base}
Referer: {base}/shop/signIn/account?ssi={ssi}
Sec-Fetch-Site: same-origin / Mode: cors / Dest: empty
X-Requested-With: Fetch
syntax: graviton
modelVersion: v2
x-aos-model-page: idmsSignInPage
x-aos-stk: {stk}

body: grantCode=        ← 空值，字面就是 "grantCode="
```

成功返回 200 + `Set-Cookie: as_disa=…`。

---

## 四、Graviton 账单 RPC

所有业务调用都是同一个入口：

```
POST /shop/accounthomex
Content-Type: application/x-www-form-urlencoded

a  = ["fetchDashboard"]          动作
m  = home.dashboards             模型路径
ds = home                        数据集
```

请求头额外带：

```
x-aos-model-page: RetailHome          ← 不是 idmsSignInPage
x-aos-stk: {stk}
x-aos-ui-fetch-call-{N}: {8位随机}     ← N 每次递增
```

### 模型路径

**账单不在 dashboard 里。** `fetchDashboard` 只返回动作广告和一堆
`"Information about … is currently unavailable"`，真正的数据要再打一次
`fetchCustomerAccount`。

| 用途 | 路径 |
|---|---|
| 概览（仅动作广告） | `home.dashboards` |
| **账单（真实数据）** | `home.customerAccount` |
| 编辑面板 | `home.customerAccount.billingInfo` |

### 调用形式的坑

`fetchCustomerAccount` 必须用 **query 参数**：

```
POST /shop/accounthomex?_a=fetchCustomerAccount&_m=home.customerAccount
```

把 `a`/`m` 放在 body 里也能拿到 `head.status: 200`，但每个区块都会被替换成
`"Information about … is currently unavailable"`。这看起来像"账号没绑卡"，
实际上是请求形式不对——排查时极易误判。

页面的 `a` 字段自己就给出了正确形式：

```json
{"fetchCustomerAccount": {
   "url": "https://secureN.store.apple.com/shop/accounthomex?_a=fetchCustomerAccount&_m=home.customerAccount",
   "submit": true}}
```

### 账单数据结构（实测）

```
customerAccount.billingInfo
    .billingAddress.d            street / street2 / city / state / postalCode
                                 / countryCode / companyName
    .billingContact.d            firstName / lastName / fullDaytimePhone / emailAddress
    .billingPaymentDetails
        .paymentDetails.d        paymentType("VISA") / paymentTypeLabel("Visa")
                                 / cardExpiry("12/34")
```

注意 **`billingInfo.d` 是 null**，子块直接挂在 `billingInfo` 下；
支付信息还比地址多一层 `paymentDetails`。

### 调用前置：warmup → prepare → 取数

`fetch_billing_worker` 的顺序，缺一步都会退化成 `SESSIONEXPIRY`：

```python
client.warmup_with_retry()   # 依次探测 secureN 主机，留下能跳转的那个
client.authenticate()        # 拿到新鲜的 x-aos-stk
client.alive_payload()       # 一次轻量 RPC 确认会话真的活着
client.fetch_billing_info()  # 真正取账单
```

`x-aos-stk` 每次握手都会轮换，必须用 `authenticate()` 的返回值覆盖旧值，
否则后续 RPC 会以 403 被拒。

### 会话失效的两种表现

```
{"head":{"status":302,"data":{"url":"…accounthome/sorry?type=SESSIONEXPIRY"}},"body":{}}
```

或者响应变成 `text/html`，内容是自动提交的 repost 表单页（缺 `X-Requested-With: Fetch` 时会这样）。

两种都要当成"重新登录"处理。

### 卡号加密

```
RSA-OAEP(MGF1-SHA256, SHA256)
公钥：审计包里的 publicKey（DER，base64）
输出：{"cipherText": base64(密文), "publicKeyHash": key_hash}
```

---

## 五、会话持久化

`src/butter/apple_auth/session.py` 负责把会话存进 `accounts.json`。

### 存什么

```
DES*            刷新令牌，能换回整个 Apple ID 会话
myacinfo        IDMSA 会话（属 idmsa.apple.com 域）
as_disa         store 会话（属 .apple.com 域）
as_sfa / dssid2 / dssf / shld_bt_ck / shld_bt_m / geo     风控 cookie
stk             当前 x-aos-stk
```

### 域归属

**这一点很关键：** `myacinfo` / `aasp` / `ifssp` 属于 `idmsa.apple.com`，其余属于 `.apple.com`。恢复时如果全塞到 `.apple.com`，IDMSA 那一半会静默丢失，表现为"cookie 都在但会话无效"。

```python
_IDMSA_COOKIES = ("myacinfo", "aasp", "ifssp")
```

### 用法

```python
from butter.apple_auth.session import SessionManager

sm = SessionManager()

# 登录后保存
sm.save(email, session, stk=stk, store_base=base)

# 下次启动直接读
saved = sm.load(email)
if saved.has_store:          # as_disa 还在，可以直接查账单
    info = await sm.fetch_billing(email, proxy=...)
```

`fetch_billing` 会在 `as_disa` 缺失时自动补做 store 握手，并把新拿到的 cookie 写回去。

---

## 六、模块对应

| 文件 | 内容 |
|---|---|
| `apple_exe_replica.py` | IDMSA 全流程 + store 握手 + shld 接入 |
| `apple_shld_v3.py` | SHLD 双求解器（SHA / 乘积分解） |
| `apple_store_client.py` | Graviton RPC、账单读写、卡号加密 |
| `apple_fd_client_info.py` | `X-Apple-I-FD-Client-Info` 的 `F` 字段 |
| `apple_hashcash.py` | `X-APPLE-HC` |
| `apple_shld_solver.py` | 早期 SHLD 实现（保留） |
| `session.py` | 会话持久化 + 账单读写入口 |

---

## 七、排查顺序

遇到问题按这个顺序查，能覆盖绝大多数情况：

1. **init 404** → 先看 `Accept` 头在不在，再看 `X-Apple-Domain-Id` 是不是 39
2. **complete 401** → SRP 的 M1 错了，重点查 `u` 是否补零、`k` 是否用 XOR
3. **securitycode 403** → 看 `Content-Type` 和 `scnt` 都在不在，验证码是否已被用过
4. **authx 541** → SHLD 没过。先确认 `jr=30`，再看 `shld_bt_ck` 有没有进 jar
5. **accounthomex 返回 SESSIONEXPIRY** → `as_disa` 过期，重新走 store 握手
6. **accounthomex 返回 HTML 表单页** → 缺 `X-Requested-With: Fetch`
7. **恢复会话后无效** → 检查 cookie 域归属，`myacinfo` 要落在 idmsa 域
