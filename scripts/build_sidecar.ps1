# Bundle the Python backend into butter-backend.exe for the Tauri shell.
#
# Mirrors build_sidecar.sh. PyInstaller cannot cross-compile, so this must run on
# Windows; the Tauri binary must also be built there (NSIS is Windows-only).
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\build_sidecar.ps1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root 'backend-dist'
$Name = 'butter-backend'

Set-Location $Root

Write-Host '==> Installing build dependencies' -ForegroundColor Cyan
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt 'pyinstaller>=6.10'

Write-Host '==> Building sidecar' -ForegroundColor Cyan
python -m PyInstaller `
  --noconfirm --clean --onefile --noconsole --name $Name --paths src `
  --collect-all curl_cffi --collect-submodules uvicorn `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  --distpath $Out --workpath (Join-Path $Root 'build') --specpath (Join-Path $Root 'build') `
  src\butter\__main__.py

$Exe = Join-Path $Out "$Name.exe"
if (-not (Test-Path $Exe)) { throw "sidecar missing: $Exe" }

Write-Host "built -> $Exe" -ForegroundColor Green
