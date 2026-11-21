# 发布检查单

一条命令发版，Windows 和 mac 都在 CI 上编译，产物自动进 R2 并换掉官网的下载地址：

```bash
scripts/release.sh
```

脚本自己按顺序做：

1. 检查工作区干净、在 `main` 上、`gh` 与 `wrangler` 已登录、updater 私钥在位
2. 递增 patch 版本（`package.json` / `tauri.conf.json` / `Cargo.toml` / `pyproject.toml`）并提交
3. 读当月 Actions 已用分钟数：剩余不足 90 分钟就把仓库转**公开**（公开仓库不计分钟），并记下要转回去
4. 推 `main` + tag → CI 在 `windows-latest` 出 NSIS，在 `macos-latest` 出 dmg 与 updater 包
5. 等这次 run，失败就打印失败 job 的日志并退出（此时线上没被动过）
6. 下载全部产物（含 `.sig`）→ 传 R2 的 `releases/v<版本>/`
7. 重写 `site/public/index.html` 的两个下载链接与体积，部署 Pages
8. 发布 release，把仓库转回私有

产物地址：`https://butter-site-4i1.pages.dev/dl/releases/v<版本>/…`，更新清单
`https://butter-site-4i1.pages.dev/dl/latest.json`（Pages Function 直接读 `butter-downloads` 桶，
`tauri.conf.json` 的 updater endpoint 就指向它）。

## 常用开关

| 变量 | 作用 |
|---|---|
| `--dry-run` | 走到额度判断为止，然后撤掉本地 commit 和 tag，不碰远端 |
| `--resume` | 不升版本，复用当前 tag 已有那次 CI run 继续后续步骤（编译已经跑过时用） |
| `NO_PUBLISH=1` | 产物照发，release 留在草稿状态 |
| `KEEP_VISIBILITY=1` | 永远不转公开，额度不够也私有跑 |
| `GITHUB_QUOTA_MINUTES=3000` | 计划额度读不到时改这个（free 2000 / pro 3000 / team 10000） |

失败后怎么办：

- 编译已经成功、只是后面某步断了 → `scripts/release.sh --resume`，不会重编。
- 编译本身失败 → 修代码，直接重跑 `scripts/release.sh`，会再升一个 patch 版本；同版本清单条目会合并，不会互相冲掉。
- 仓库卡在公开状态 → `gh repo edit joltzeal/butter --visibility private --accept-visibility-change-consequences`。
- 站点链接被改了一半 → `git restore site/public/index.html` 再重跑。

脚本成功结尾会把站点改动提交并推一次（此时仓库还是公开，用免费分钟跑那一次只跑测试）。

## 0. 仓库侧配置

| 类型 | 名字 | 用途 | 当前 |
|---|---|---|---|
| variable | `BUTTER_ACTIVATION_URL` | 构建期注入激活服务 | 已配 |
| secret | `TAURI_SIGNING_PRIVATE_KEY` | 给 updater 产物签名 | 已配 |
| secret | `UPDATE_TOKEN` | 私有仓库的 release 资产读权限（`VITE_UPDATE_TOKEN`） | 已配；用的是 `gh` 的 OAuth token，会随登录失效，建议换长期 PAT |
| secret | `APPLE_CERTIFICATE` / `APPLE_CERTIFICATE_PASSWORD` / `APPLE_SIGNING_IDENTITY` | Developer ID Application（base64 p12） | 未配；workflow 里这六个 env 是注释掉的——空值也会被 bundler 当成"有证书"，然后在空 p12 上失败 |
| secret | `APPLE_ID` / `APPLE_APP_PASSWORD` / `APPLE_TEAM_ID` | 公证 | 未配 |
| secret | Windows 代码签名（PFX + thumbprint / Azure Trusted Signing） | NSIS 的 Authenticode | 未配 → SmartScreen 会拦 |

缺签名证书时照样能出包，只是装机会弹「未知开发者 / 已阻止」。

## 1. 签名密钥保管

- 私钥在 `~/.tauri/butter-updater.key`（无密码），公钥烘在 `tauri.conf.json` 的 `plugins.updater.pubkey`。
- **丢了私钥 = 已发出去的版本永远收不到更新**，只能换 key 让用户手动重装。备份它。
- 脚本默认从这个路径读；也可以显式 `TAURI_SIGNING_PRIVATE_KEY=… scripts/release.sh`。

## 2. 版本号

- 只升不降：用户端比的是 semver，新版本号必须大于已装版本，所以脚本只做 patch 递增。
- 要跨版本（`0.2.0`）先手动跑 `uv run python scripts/bump_version.py` 再手工打 tag 走同一套流程。

## 3. updater 与清单

- `latest.json` 同时含 `darwin-aarch64` 与 `windows-x86_64`，缺一个那边就收不到更新，脚本在缺平台时直接失败。
- 私钥签名由 CI 的 `TAURI_SIGNING_PRIVATE_KEY` 产生，客户端用二进制里的公钥校验，改不了。
- 仓库私有/公开切换不影响更新链路：客户端读的是 R2 上的 `/dl/…`，不是 GitHub 资产。

## 4. 客户端侧

- 启动 4 秒后静默检查一次，有新版弹 toast（点「去设置」）。
- 设置 → 更新：检查 / 下载并安装（带进度）/ 重启并安装。
- macOS 上未公证的更新装入后会再次触发 Gatekeeper（配合第 0 步解决）。

## 5. 站点

`site/` 手工改完单独发：

```bash
cd site && npx wrangler pages deploy public --project-name butter-site --branch main
```
