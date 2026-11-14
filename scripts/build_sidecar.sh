#!/usr/bin/env bash
# Bundle the Python backend into a single executable the Tauri shell can spawn.
# Output lives inside the repo so Tauri resource paths stay relative to src-tauri/.
# Usage:  ./scripts/build_sidecar.sh    ->  ./backend-dist/butter-backend(.exe)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/backend-dist"
NAME="butter-backend"
cd "$ROOT"
uv pip install --quiet "pyinstaller>=6.10"
uv run pyinstaller \
  --noconfirm --clean --onefile --name "$NAME" --paths src \
  --collect-all curl_cffi --collect-submodules uvicorn \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --distpath "$OUT" --workpath "$ROOT/build" --specpath "$ROOT/build" \
  src/butter/__main__.py
echo "built -> $OUT/$NAME"
