#!/usr/bin/env bash
# Increment the app version before a local build.
#
# Source of truth is package.json; tauri.conf.json, Cargo.toml and
# butter/__init__.py are kept in sync from it. Patch number only — this project
# ships local side-loads, not releases.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$ROOT/desktop/package.json"

CUR=$(python3 -c "import json,sys; print(json.load(open('$PKG'))['version'])")
NEXT=$(python3 - "$CUR" <<'PY'
import sys
parts = sys.argv[1].split(".")
parts[-1] = str(int(parts[-1]) + 1)
print(".".join(parts))
PY
)

python3 - "$ROOT" "$NEXT" <<'PY'
import json, pathlib, re, sys

root = pathlib.Path(sys.argv[1])
ver = sys.argv[2]

# package.json
pkg = root / "desktop" / "package.json"
data = json.loads(pkg.read_text(encoding="utf-8"))
data["version"] = ver
pkg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# tauri.conf.json (first "version": line)
conf = root / "desktop" / "src-tauri" / "tauri.conf.json"
text = conf.read_text(encoding="utf-8")
text = re.sub(r'"version"\s*:\s*"[^"]+"', f'"version": "{ver}"', text, count=1)
conf.write_text(text, encoding="utf-8")

# Cargo.toml (package version, not dependency versions)
cargo = root / "desktop" / "src-tauri" / "Cargo.toml"
lines = cargo.read_text(encoding="utf-8").splitlines()
for i, line in enumerate(lines):
    if line.startswith("version = "):
        lines[i] = f'version = "{ver}"'
        break
cargo.write_text("\n".join(lines) + "\n", encoding="utf-8")

# python package
init = root / "src" / "butter" / "__init__.py"
text = init.read_text(encoding="utf-8")
if "__version__" in text:
    text = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{ver}"', text)
else:
    text += f'\n__version__ = "{ver}"\n'
init.write_text(text, encoding="utf-8")
PY

echo "$CUR -> $NEXT"
