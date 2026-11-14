# Windows 构建

`PyInstaller` 不能交叉编译，`NSIS` 也只有 Windows 版本，所以 Windows 安装包必须在 Windows 上生成。

## 一次性准备

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12+ | 安装时勾选 **Add to PATH** |
| Node.js | 20+ | 官网安装包 |
| pnpm | 最新 | `npm i -g pnpm` |
| Rust | stable-msvc | [rustup.rs](https://rustup.rs)，默认工具链即可 |
| VS Build Tools | 2022 | 勾选 **Desktop development with C++** |

WebView2 在 Win11 已内置；Win10 由 Tauri 的安装程序自动安装。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

脚本按顺序做四件事：

1. 递增版本号（`package.json` → `tauri.conf.json` → `Cargo.toml` → `__init__.py`）
2. 安装 Python 依赖，用 PyInstaller 产出 `backend-dist\butter-backend.exe`
3. 把 `tauri.conf.json` 的资源映射指向 `.exe`
4. `pnpm tauri build --bundles nsis`

产物：

```
desktop\src-tauri\target\release\bundle\nsis\Butter_<version>_x64-setup.exe
```

`currentUser` 安装模式，不需要管理员权限。

## 两个平台的资源差异

`tauri.conf.json` 里只声明无扩展名的 sidecar，因为 macOS 的产物就叫 `butter-backend`。Windows 需要 `butter-backend.exe`，所以由 `build_windows.ps1` 在构建时改配置——这样任何一方都不会把一个空占位文件带进安装包。

Rust 侧的 `resolve_command()` 同时查找两个文件名，所以运行期不需要再判断平台。

## 单独构建后端

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_sidecar.ps1
```

## 常见问题

**`cargo` 找不到 MSVC 链接器**
→ 装了 VS Build Tools 但没勾 C++ 组件。重新运行安装程序补上。

**`pnpm tauri build` 卡在下载 NSIS**
→ 首次构建 Tauri 会自动下载 NSIS 到 `%LOCALAPPDATA%\tauri`。网络不通时手动装 [NSIS 3.x](https://nsis.sourceforge.io/) 并确保 `makensis.exe` 在 PATH 中。

**安装后启动白屏**
→ 后端没起来。在安装目录执行 `backend\butter-backend.exe --port 8899`，看是否报缺 DLL；通常是漏了 `curl_cffi` 的 `--collect-all`。
