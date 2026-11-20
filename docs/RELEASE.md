# 发布检查单

发一版需要同时满足：**代码能过 CI**、**能签名**、**能更新**。下面按顺序来。

## 0. 仓库侧配置（一次性）

| 类型 | 名字 | 用途 | 当前 |
|---|---|---|---|
| variable | `BUTTER_ACTIVATION_URL` | 构建期注入激活服务 | 已配 |
| secret | `TAURI_SIGNING_PRIVATE_KEY` | 给 updater 产物签名 | 已配 |
| secret | `UPDATE_TOKEN` | 私有仓库的 release 资产需要读权限，构建期烘进 `VITE_UPDATE_TOKEN` | 已配（用的是 `gh` 的 OAuth token，会随登录失效，建议换长期 PAT） |
| secret | `APPLE_CERTIFICATE` / `APPLE_CERTIFICATE_PASSWORD` / `APPLE_SIGNING_IDENTITY` | Developer ID Application 证书（base64 p12） | 未配 → 现在产出的是未签名 app |
| secret | `APPLE_ID` / `APPLE_APP_PASSWORD` / `APPLE_TEAM_ID` | 公证 | 未配 |
| secret | Windows 代码签名 | NSIS 的 Authenticode（PFX + thumbprint，或 Azure Trusted Signing） | 未配 → SmartScreen 会拦 |

缺签名证书时 CI 仍然能出包，但装机会弹「未知开发者 / 已阻止」。

想让 `latest.json` 可以被匿名拉取，还有一个更省事的办法：把仓库转公开，然后删掉 `UPDATE_TOKEN` 和 `client.ts` 里对应的 header。

## 1. 签名密钥保管

- 私钥在 `~/.tauri/butter-updater.key`（无密码），公钥已烘进 `tauri.conf.json` 的 `plugins.updater.pubkey`。
- **丢了私钥 = 已发出去的版本永远收不到更新**，只能换 key + 让用户手动重装。备份它。
- 本地出包同样要签：

```bash
cd desktop
TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/butter-updater.key)" pnpm tauri build
```

## 2. 改版本

```bash
uv run python scripts/bump_version.py 0.1.22   # 同步 package.json / Cargo.toml / tauri.conf.json
```

CI 会校验 tag 与 `desktop/package.json` 的版本是否一致，不一致直接 fail（不然装上的版本号是错的，updater 比较会失效）。

## 3. 打 tag 触发

```bash
git tag v0.1.22 && git push origin v0.1.22
```

CI 会：跑 pytest + 前端 `pnpm build` → Windows NSIS / macOS universal app+dmg → 上传带 `.sig` 的 updater 产物和 `latest.json` → 建一个**草稿** release。

## 4. 发布 release（关键）

草稿 release 不算 `latest`，`releases/latest/download/latest.json` 取不到。检查草稿里的 artifact，然后点 **Publish**，更新才会推送到已装用户。

## 5. 客户端侧

- 启动 4 秒后静默检查一次，有新版弹 toast（点「去设置」）。
- 设置 → 更新：检查 / 下载并安装（带进度）/ 重启并安装。
- 签名由壳内公钥校验，公钥在二进制里，改不了。
- macOS 上未公证的更新装入后会再次触发 Gatekeeper（配合第 0 步解决）。

## 版本号与 updater 的约束

- 只升不降：用户端比较的是 semver，新版本号必须大于已装版本。
- 一次发布里两个平台的 `latest.json` 由 `tauri-action` 合并，不要手工替换成只含单平台的版本。
- 草稿改完再发，重复点 Publish 不会重发已上传资产。
