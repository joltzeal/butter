//! Butter desktop shell.
//!
//! Owns the Python sidecar lifecycle and exposes a tiny command surface the
//! React UI uses on boot:
//!
//! * `backend_info` — current status, base URL, PID, and last log lines
//! * `backend_restart` — stop + respawn the sidecar
//!
//! The sidecar is discovered in this order:
//! 1. `BUTTER_BACKEND` env var (absolute path to an executable)
//! 2. bundled resource `backend/butter-backend` (PyInstaller build in release)
//! 3. `uv run butter` inside the repository (developer workflow)
//!
//! Health is probed by polling `/api/health` until the server answers or the
//! boot deadline elapses; the URL is handed to the UI only after that.

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{Manager, RunEvent, State};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

const HEALTH_PATH: &str = "/api/health";
const BOOT_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub status: String,
    pub base_url: Option<String>,
    pub port: Option<u16>,
    pub pid: Option<u32>,
    pub command: Option<String>,
    pub log_tail: Vec<String>,
}

struct BackendState {
    inner: Mutex<BackendInner>,
}

struct BackendInner {
    child: Option<Child>,
    info: BackendInfo,
    logs: Vec<String>,
}

impl Default for BackendState {
    fn default() -> Self {
        Self {
            inner: Mutex::new(BackendInner {
                child: None,
                info: BackendInfo {
                    status: "starting".into(),
                    base_url: None,
                    port: None,
                    pid: None,
                    command: None,
                    log_tail: vec![],
                },
                logs: Vec::new(),
            }),
        }
    }
}

fn push_log(inner: &mut BackendInner, line: String) {
    eprintln!("[butter-shell] {line}");
    inner.logs.push(line);
    if inner.logs.len() > 400 {
        let overflow = inner.logs.len() - 400;
        inner.logs.drain(0..overflow);
    }
    inner.info.log_tail = inner.logs.iter().rev().take(80).cloned().rev().collect();
}

/// Resolve how to start the backend.
fn resolve_command(app: &tauri::AppHandle) -> Result<(PathBuf, Vec<String>), String> {
    if let Ok(explicit) = std::env::var("BUTTER_BACKEND") {
        if !explicit.is_empty() {
            return Ok((PathBuf::from(explicit), vec![]));
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        // Tauri nests `../../x` resources under `_up_/_up_/`; check both shapes.
        let candidates = [
            resource_dir.join("backend"),
            resource_dir.join("_up_").join("_up_").join("backend-dist"),
            resource_dir.join("backend-dist"),
        ];
        for dir in candidates {
            for name in ["butter-backend", "butter-backend.exe"] {
                let candidate = dir.join(name);
                if candidate.exists() {
                    return Ok((candidate, vec![]));
                }
            }
        }
    }

    // Developer fallback: walk up from the executable and from the CWD looking for
    // the repository root that holds the Python package.
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        roots.extend(exe.ancestors().map(|p| p.to_path_buf()));
    }
    if let Ok(cwd) = std::env::current_dir() {
        roots.extend(cwd.ancestors().map(|p| p.to_path_buf()));
    }
    for dir in roots {
        if dir.join("pyproject.toml").exists() && dir.join("src").join("butter").exists() {
            let uv = which::which("uv").map_err(|_| "未找到 uv，无法启动 Python 后端".to_string())?;
            return Ok((uv, vec!["run".into(), "--project".into(), dir.display().to_string(), "butter".into()]));
        }
    }

    Err("未找到 Python 后端：请设置 BUTTER_BACKEND 或先执行 uv sync".into())
}

async fn wait_for_health(port: u16) -> bool {
    let client = match reqwest::Client::builder().timeout(Duration::from_millis(800)).build() {
        Ok(client) => client,
        Err(_) => return false,
    };
    let url = format!("http://127.0.0.1:{port}{HEALTH_PATH}");
    let started = std::time::Instant::now();
    while started.elapsed() < BOOT_TIMEOUT {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    false
}

async fn spawn_backend(app: tauri::AppHandle) -> Result<BackendInfo, String> {
    let (program, args) = resolve_command(&app)?;
    let port = portpicker::pick_unused_port().ok_or_else(|| "没有可用的本地端口".to_string())?;

    let mut cmd = Command::new(&program);
    cmd.args(&args)
        .env("BUTTER_PORT", port.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(parent) = program.parent() {
        if parent.ends_with("bin") {
            // keep uv's shims visible for the child
            if let Ok(path) = std::env::var("PATH") {
                cmd.env("PATH", format!("{}:{}", parent.display(), path));
            }
        }
    }

    let mut child = cmd.spawn().map_err(|err| format!("启动后端失败: {err}"))?;
    let pid = child.id();

    let state = app.state::<BackendState>();
    {
        let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
        if let Some(stdout) = child.stdout.take() {
            let handle = app.clone();
            tauri::async_runtime::spawn(async move {
                let mut lines = BufReader::new(stdout).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if let Some(state) = handle.try_state::<BackendState>() {
                        if let Ok(mut inner) = state.inner.lock() {
                            push_log(&mut inner, line);
                        }
                    }
                }
            });
        }
        if let Some(stderr) = child.stderr.take() {
            let handle = app.clone();
            tauri::async_runtime::spawn(async move {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if let Some(state) = handle.try_state::<BackendState>() {
                        if let Ok(mut inner) = state.inner.lock() {
                            push_log(&mut inner, line);
                        }
                    }
                }
            });
        }
        inner.child = Some(child);
        inner.info.command = Some(format!("{} {}", program.display(), args.join(" ")).trim().to_string());
        inner.info.port = Some(port);
        inner.info.pid = pid;
        inner.info.status = "booting".into();
    }

    let healthy = wait_for_health(port).await;
    let mut inner = state.inner.lock().map_err(|e| e.to_string())?;
    if healthy {
        inner.info.status = "ready".into();
        inner.info.base_url = Some(format!("http://127.0.0.1:{port}"));
    } else {
        inner.info.status = "failed".into();
    }
    Ok(inner.info.clone())
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut inner) = state.inner.lock() {
        if let Some(child) = inner.child.as_mut() {
            let _ = child.start_kill();
        }
        inner.child = None;
        inner.info.status = "stopped".into();
        inner.info.base_url = None;
    }
}

#[tauri::command]
async fn backend_info(state: State<'_, BackendState>) -> Result<BackendInfo, String> {
    let inner = state.inner.lock().map_err(|e| e.to_string())?;
    Ok(inner.info.clone())
}

#[tauri::command]
async fn backend_restart(app: tauri::AppHandle) -> Result<BackendInfo, String> {
    {
        let state = app.state::<BackendState>();
        stop_backend(&state);
        tokio::time::sleep(Duration::from_millis(400)).await;
    }
    spawn_backend(app).await
}

#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    tauri_plugin_opener::open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState::default())
        .invoke_handler(tauri::generate_handler![
            backend_info,
            backend_restart,
            open_external
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let boot_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(err) = spawn_backend(boot_handle).await {
                    if let Some(state) = handle.try_state::<BackendState>() {
                        if let Ok(mut inner) = state.inner.lock() {
                            push_log(&mut inner, format!("[shell] {err}"));
                            inner.info.status = "failed".into();
                        }
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the butter shell")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                if let Some(state) = app.try_state::<BackendState>() {
                    stop_backend(&state);
                }
            }
        });
}
