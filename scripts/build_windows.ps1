# Build the full Butter Windows installer (NSIS .exe).
#
# Must run on Windows: PyInstaller cannot cross-compile, and NSIS is Windows-only.
# Produces  desktop\src-tauri\target\release\bundle\nsis\Butter_<version>_x64-setup.exe
#
# Prerequisites (install once):
#   - Python 3.12+   (python.org, "Add to PATH")
#   - Node.js 20+    (nodejs.org)
#   - Rust           (rustup.rs -> default toolchain msvc)
#   - MSVC Build Tools (Desktop development with C++)
#   - WebView2 runtime (preinstalled on Win11; Tauri bundles the bootstrapper)
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Require-Tool($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "missing '$name'. $hint"
    }
}

Write-Host '==> Checking toolchain' -ForegroundColor Cyan
Require-Tool python  'install Python 3.12+ from python.org'
Require-Tool node    'install Node.js 20+ from nodejs.org'
Require-Tool cargo   'install Rust from rustup.rs'
Require-Tool pnpm    'run: npm i -g pnpm'

# --- 1. version bump -----------------------------------------------------
Write-Host '==> Bumping version' -ForegroundColor Cyan
python (Join-Path $Root 'scripts\bump_version.py')

# --- 2. python deps + sidecar -------------------------------------------
Write-Host '==> Building backend sidecar' -ForegroundColor Cyan
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r (Join-Path $Root 'requirements.txt')
& (Join-Path $PSScriptRoot 'build_sidecar.ps1')

# --- 3. (resources already point at the sidecar directory) ---

# --- 4. frontend + tauri -------------------------------------------------
Write-Host '==> Building frontend and installer' -ForegroundColor Cyan
Push-Location (Join-Path $Root 'desktop')
try {
    pnpm install --frozen-lockfile
    pnpm tauri build --bundles nsis
} finally {
    Pop-Location
}

$Version = (Get-Content (Join-Path $Root 'desktop\package.json') | ConvertFrom-Json).version
$Setup = Join-Path $Root "desktop\src-tauri\target\release\bundle\nsis\Butter_$($Version)_x64-setup.exe"
if (Test-Path $Setup) {
    $Size = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
    Write-Host "`nInstaller ready: $Setup ($Size MB)" -ForegroundColor Green
} else {
    throw "installer not produced. Check the tauri build output above."
}
