#!/usr/bin/env bash
# Build, sign and publish a release from this machine.
#
# The installers and the updater manifest go to the Cloudflare R2 bucket behind
# the site's /dl route, so no CI run is needed. Windows artifacts are only
# included when a Windows sidecar + build exist in the bundle dir (see
# docs/RELEASE.md for the cross-compile notes).
#
#   TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/butter-updater.key)" \
#     scripts/release_local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c 'import json;print(json.load(open("desktop/package.json"))["version"])')"
BASE="https://butter-site-4i1.pages.dev/dl"
BUCKET="butter-downloads"
BUNDLE="desktop/src-tauri/target"
SITE_ORIGIN="https://butter-site-4i1.pages.dev"

: "${TAURI_SIGNING_PRIVATE_KEY:?export TAURI_SIGNING_PRIVATE_KEY first (see docs/RELEASE.md)}"

echo "==> building $VERSION"
cd desktop
case "$(uname -s)" in
  Darwin) pnpm tauri build --target aarch64-apple-darwin --bundles app,dmg ;;
  *)      pnpm tauri build --bundles nsis ;;
esac
cd "$ROOT"

MANIFEST="$(mktemp)"
python3 - "$VERSION" "$BASE" "$BUNDLE" "$SITE_ORIGIN" > "$MANIFEST" <<'PY'
import json, os, pathlib, sys

version, base, bundle, site = sys.argv[1:5]
root = pathlib.Path(bundle)
sig_files = sorted(root.glob("**/release/bundle/**/*.sig"))
platforms = {}
for sig_path in sig_files:
    artefact = pathlib.Path(str(sig_path)[: -len(".sig")])
    if not artefact.exists():
        continue
    if artefact.suffix == ".gz" and ".app.tar.gz" in artefact.name:
        key = "darwin-aarch64"
    elif artefact.suffix == ".exe":
        key = "windows-x86_64"
    elif artefact.suffix == ".dmg":
        continue
    else:
        continue
    platforms[key] = {
        "signature": sig_path.read_text().strip(),
        "url": f"{base}/releases/v{version}/{artefact.name}",
    }
    print(f"   {key}: {artefact.name}", file=sys.stderr)

if not platforms:
    sys.exit("no signed artefacts found — did the build run with the signing key?")

json.dump({"version": version, "notes": "", "pub_date": __import__("datetime").datetime.utcnow().isoformat() + "Z", "platforms": platforms}, sys.stdout, indent=2)
PY

echo "==> uploading to R2"
python3 - "$MANIFEST" "$BUCKET" <<'PY'
import json, subprocess, sys, pathlib

manifest_path, bucket = sys.argv[1:3]
manifest = json.load(open(manifest_path))
for entry in manifest["platforms"].values():
    name = entry["url"].rsplit("/", 1)[-1]
    local = list(pathlib.Path("desktop/src-tauri/target").glob(f"**/release/bundle/**/{name}"))
    if not local:
        sys.exit(f"missing local artefact {name}")
    subprocess.run(
        ["npx", "wrangler", "r2", "object", "put", f"{bucket}/releases/v{manifest['version']}/{name}",
         "--file", str(local[0]), "--remote"],
        check=True, stdout=subprocess.DEVNULL,
    )
    sig = local[0].with_name(local[0].name + ".sig")
    subprocess.run(
        ["npx", "wrangler", "r2", "object", "put", f"{bucket}/releases/v{manifest['version']}/{name}.sig",
         "--file", str(sig), "--remote"],
        check=True, stdout=subprocess.DEVNULL,
    )
    print(f"   uploaded {name}")
PY

echo "==> publishing manifest"
npx wrangler r2 object put "$BUCKET/latest.json" --file "$MANIFEST" --content-type application/json --remote >/dev/null
rm -f "$MANIFEST"

echo
echo "done. $SITE_ORIGIN/ now serves v$VERSION"
echo "manifest: $BASE/latest.json"
