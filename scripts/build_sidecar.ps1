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

$Engine = if ($env:SIDECAR_ENGINE) { $env:SIDECAR_ENGINE } else { 'nuitka' }

if ($Engine -eq 'nuitka') {
  Write-Host '==> Building sidecar (nuitka)' -ForegroundColor Cyan
  python -m pip install --quiet 'nuitka>=2.4' ordered-set zstandard
  python -m nuitka `
    --standalone --assume-yes-for-downloads `
    --output-dir=$Out --output-filename=$Name `
    --include-package=butter --include-package=uvicorn `
    --include-package-data=curl_cffi `
    --nofollow-import-to=tkinter --nofollow-import-to=unittest `
    --python-flag=no_docstrings --python-flag=-O `
    --lto=yes `
    src\butter\__main__.py
  # Nuitka names the dist dir after the main module.
  $Raw = Join-Path $Out "__main__.dist"
  $Dist = Join-Path $Out "$Name.dist"
  if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
  if (Test-Path $Raw) { Move-Item $Raw $Dist }
  Write-Host "built -> $Dist\$Name.exe" -ForegroundColor Green
  exit 0
}

Write-Host '==> Building sidecar (pyinstaller)' -ForegroundColor Cyan
python -m pip install --quiet 'pyinstaller>=6.10'
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
