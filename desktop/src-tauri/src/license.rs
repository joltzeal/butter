//! Offline licence checks.
//!
//! A licence is `{payload, sig}` where `payload` is base64url JSON and `sig` is
//! an Ed25519 signature over those exact bytes. The public key is compiled in;
//! the private key never ships, so editing a licence only breaks the signature.
//!
//! The store handshake and everything under `src/butter` can be decompiled, so
//! this gate lives in the binary that launches the backend: no valid licence,
//! no sidecar.

use std::path::PathBuf;

use base64::engine::general_purpose::URL_SAFE_NO_PAD as B64;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

/// Master public key. Rotating it invalidates every issued licence.
const PUBLIC_KEY_HEX: &str = "7fb80f6aebd9e7f32e56dda314ac11688e2a14407a9298480b1383e6b7a28c86";

/// A licence is only trusted for a short while without the server.
/// Must stay shorter than the shortest code (a week), or one purchase buys
/// a free week offline.
const OFFLINE_GRACE_SECS: i64 = 3 * 24 * 3600;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Payload {
    pub code: String,
    pub machine: String,
    pub plan: String,
    /// Unix seconds. Absolute, so a stolen clock cannot extend it.
    pub exp: i64,
    pub iat: i64,
    #[serde(default)]
    pub jti: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Licence {
    pub payload: String,
    pub sig: String,
    /// Unix seconds of the last successful contact with the activation server.
    #[serde(default)]
    pub checked: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub licensed: bool,
    pub reason: String,
    pub plan: String,
    pub exp: i64,
    pub days_left: i64,
}

fn licence_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|_| "no app data dir".to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("license.json"))
}

fn key() -> Result<VerifyingKey, String> {
    let raw = hex_to_bytes(PUBLIC_KEY_HEX)?;
    let bytes: [u8; 32] = raw.try_into().map_err(|_| "bad public key".to_string())?;
    VerifyingKey::from_bytes(&bytes).map_err(|e| e.to_string())
}

fn hex_to_bytes(hex: &str) -> Result<Vec<u8>, String> {
    if hex.len() % 2 != 0 {
        return Err("odd hex".into());
    }
    (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Verify signature, machine binding and expiry.
pub fn evaluate(app: &AppHandle) -> Status {
    let deny = |reason: &str| Status {
        licensed: false,
        reason: reason.into(),
        plan: String::new(),
        exp: 0,
        days_left: 0,
    };

    let path = match licence_path(app) {
        Ok(p) => p,
        Err(e) => return deny(&e),
    };
    let raw = match std::fs::read_to_string(&path) {
        Ok(r) => r,
        Err(_) => return deny("未激活"),
    };
    let licence: Licence = match serde_json::from_str(&raw) {
        Ok(l) => l,
        Err(_) => return deny("许可证损坏"),
    };

    let payload_bytes = match B64.decode(licence.payload.as_bytes()) {
        Ok(b) => b,
        Err(_) => return deny("许可证格式错误"),
    };
    let sig_bytes = match B64.decode(licence.sig.as_bytes()) {
        Ok(b) => b,
        Err(_) => return deny("签名格式错误"),
    };
    let sig_arr: [u8; 64] = match sig_bytes.try_into() {
        Ok(a) => a,
        Err(_) => return deny("签名长度错误"),
    };
    let signature = Signature::from_bytes(&sig_arr);
    let key = match key() {
        Ok(k) => k,
        Err(e) => return deny(&e),
    };
    if key.verify(&payload_bytes, &signature).is_err() {
        return deny("签名不匹配");
    }

    let payload: Payload = match serde_json::from_slice(&payload_bytes) {
        Ok(p) => p,
        Err(_) => return deny("载荷损坏"),
    };

    // Machine binding: a copied licence is useless on another box.
    match machine_id(app) {
        Ok(local) if local == payload.machine => {}
        _ => return deny("许可证不属于这台机器"),
    }

    let now = now();
    if payload.exp <= now {
        return deny("已过期");
    }
    // Clock rollback: a licence checked in the future means the clock moved back.
    if licence.checked > now + 3600 {
        return deny("系统时间被回拨");
    }
    if licence.checked > 0 && now - licence.checked > OFFLINE_GRACE_SECS {
        return deny("需要联网校验");
    }

    Status {
        licensed: true,
        reason: String::new(),
        plan: payload.plan,
        exp: payload.exp,
        days_left: ((payload.exp - now) + 86_399) / 86_400,
    }
}

pub fn save(app: &AppHandle, payload: &str, sig: &str, checked: i64) -> Result<(), String> {
    let licence = Licence {
        payload: payload.to_string(),
        sig: sig.to_string(),
        checked,
    };
    let path = licence_path(app)?;
    std::fs::write(path, serde_json::to_string(&licence).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

fn activation_url() -> String {
    if let Ok(v) = std::env::var("BUTTER_ACTIVATION_URL") {
        if !v.is_empty() {
            return v;
        }
    }
    option_env!("BUTTER_ACTIVATION_URL").unwrap_or("").to_string()
}

/// Refresh the licence from the server. Best effort: success rewrites `checked`
/// and pushes expiry forward, failure just leaves the offline grace running.
pub async fn renew(app: AppHandle) -> Result<Status, String> {
    let base = activation_url();
    if base.is_empty() {
        return Err("未配置激活服务器".into());
    }
    let machine = machine_id(&app)?;
    let body = serde_json::json!({ "machine": machine });

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .post(format!("{}/renew", base.trim_end_matches('/')))
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        let detail = res.text().await.unwrap_or_default();
        return Err(detail);
    }

    #[derive(Deserialize)]
    struct Reply {
        payload: String,
        sig: String,
        #[serde(default)]
        checked: i64,
    }
    let reply: Reply = res.json().await.map_err(|e| e.to_string())?;
    let checked = if reply.checked > 0 { reply.checked } else { now() };
    save(&app, &reply.payload, &reply.sig, checked)?;
    Ok(evaluate(&app))
}

/// Renew on a slow loop; the caller only starts it when already licensed.
pub fn spawn_renewer(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        loop {
            let status = evaluate(&app);
            if !status.licensed {
                break;
            }
            // Once a day is plenty against a 3-day leash.
            if let Ok(raw) = std::fs::read_to_string(licence_path(&app).unwrap_or_default()) {
                if let Ok(licence) = serde_json::from_str::<Licence>(&raw) {
                    if now() - licence.checked < 86_400 {
                        tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
                        continue;
                    }
                }
            }
            let _ = renew(app.clone()).await;
            tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
        }
    });
}

/// Licence payload/signature as env pairs, for the sidecar's param fetch.
pub fn fields(app: &AppHandle) -> Vec<(String, String)> {
    let Ok(raw) = std::fs::read_to_string(licence_path(app).unwrap_or_default()) else {
        return Vec::new();
    };
    let Ok(licence) = serde_json::from_str::<Licence>(&raw) else {
        return Vec::new();
    };
    vec![
        ("BUTTER_LICENSE_PAYLOAD".into(), licence.payload),
        ("BUTTER_LICENSE_SIG".into(), licence.sig),
    ]
}

pub fn mark_checked(app: &AppHandle) {
    let Ok(path) = licence_path(app) else { return };
    let Ok(raw) = std::fs::read_to_string(&path) else { return };
    let Ok(mut licence) = serde_json::from_str::<Licence>(&raw) else { return };
    licence.checked = now();
    if let Ok(out) = serde_json::to_string(&licence) {
        let _ = std::fs::write(path, out);
    }
}

/// Stable per-machine value: OS-provided UUIDs where available.
pub fn machine_id(_app: &AppHandle) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        let out = std::process::Command::new("ioreg")
            .args(["-rd1", "-c", "IOPlatformExpertDevice"])
            .output()
            .map_err(|e| e.to_string())?;
        let text = String::from_utf8_lossy(&out.stdout);
        for line in text.lines() {
            if line.contains("IOPlatformUUID") {
                if let Some(v) = line.split('"').nth(3) {
                    return Ok(hash(v.trim()));
                }
            }
        }
        Err("读不到机器标识".into())
    }
    #[cfg(target_os = "windows")]
    {
        let out = std::process::Command::new("reg")
            .args([
                "query",
                r"HKLM\SOFTWARE\Microsoft\Cryptography",
                "/v",
                "MachineGuid",
            ])
            .output()
            .map_err(|e| e.to_string())?;
        let text = String::from_utf8_lossy(&out.stdout);
        for line in text.lines() {
            if line.contains("MachineGuid") {
                if let Some(v) = line.split_whitespace().last() {
                    return Ok(hash(v.trim()));
                }
            }
        }
        Err("读不到机器标识".into())
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        Ok(hash(&std::env::var("HOSTNAME").unwrap_or_default()))
    }
}

/// Short, non-reversible machine fingerprint (FNV-1a, 16 hex chars).
fn hash(value: &str) -> String {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in value.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100_0000_01b3);
    }
    format!("{h:016x}")
}
