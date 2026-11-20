#!/usr/bin/env bash
# Compile the Python backend.
#
# Nuitka by default: real machine code, and `--standalone` (not `--onefile`)
# because onefile unpacks to a temp dir at every start, which gives most of the
# compilation benefit back. The output is a directory the shell launches from.
#
# SIDECAR_ENGINE=pyinstaller falls back to the old path.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/backend-dist"
NAME="butter-backend"
ENGINE="${SIDECAR_ENGINE:-nuitka}"
cd "$ROOT"

# uv is preferred (fast, pinned); runners without it fall back to python.
if command -v uv >/dev/null 2>&1; then
  PIP() { uv pip install --quiet "$@"; }
  PY() { uv run python "$@"; }
else
  PIP() { python -m pip install --quiet "$@"; }
  PY() { python "$@"; }
fi

rm -rf "$OUT/$NAME.dist"
mkdir -p "$OUT"

if [ "$ENGINE" = "pyinstaller" ]; then
  PIP "pyinstaller>=6.10"
  PY -m pyinstaller \
    --noconfirm --clean --onefile --name "$NAME" --paths src \
    --collect-all curl_cffi --collect-submodules uvicorn \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.lifespan.on \
    --distpath "$OUT" --workpath "$ROOT/build" --specpath "$ROOT/build" \
    src/butter/__main__.py
  echo "built -> $OUT/$NAME (pyinstaller)"
  exit 0
fi

PIP "nuitka>=2.4" ordered-set zstandard
# curl_cffi ships libcurl-impersonate; it must travel as package data or the
# binary starts and then fails on first request.
PY -m nuitka \
  --standalone --assume-yes-for-downloads \
  --output-dir="$OUT" --output-filename="$NAME" \
  --include-package=butter --include-package=uvicorn \
  --include-package-data=curl_cffi \
  --nofollow-import-to=tkinter --nofollow-import-to=unittest \
  --python-flag=no_docstrings --python-flag=-O \
  --lto=yes \
  src/butter/__main__.py

# Nuitka names the dist dir after the main module (``__main__.dist``); rename it
# to a stable path the shell resolves and the bundle can map.
rm -rf "$OUT/$NAME.dist"
if [ -d "$OUT/__main__.dist" ]; then
  mv "$OUT/__main__.dist" "$OUT/$NAME.dist"
fi
rm -rf "$OUT/__main__.build" "$OUT/$NAME.build"
test -d "$OUT/$NAME.dist" || { echo "missing $OUT/$NAME.dist"; exit 1; }
echo "built -> $OUT/$NAME.dist/$NAME"
