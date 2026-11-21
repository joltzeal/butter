#!/usr/bin/env bash
# One command to ship a version.
#
#   scripts/release.sh            # bump, build both platforms in CI, publish
#   scripts/release.sh --dry-run  # stop before touching the remote
#
# What it does, in order:
#   1. preflight: clean tree, on main, gh + wrangler logged in, signing key present
#   2. bump the patch version everywhere and commit it
#   3. read the remaining Actions quota; if it is short, flip the repo PUBLIC
#      (public repos do not bill minutes), remember to flip it back
#   4. push main + tag → CI builds the Windows NSIS installer and the mac dmg
#   5. wait for the run, fail loudly with the failed job log
#   6. download every artefact, push them to the R2 bucket behind /dl
#   7. rewrite the site's download links to the new version and deploy the site
#   8. publish the draft release, restore the repo to private
#
# Env:
#   TAURI_SIGNING_PRIVATE_KEY  updater signing key (defaults to ~/.tauri/butter-updater.key)
#   GITHUB_QUOTA_MINUTES       plan quota when the billing API is unreadable
#                              (free=2000, pro=3000, team=10000)
#   KEEP_VISIBILITY=1          never flip the repo, even when out of minutes
#   NO_PUBLISH=1               leave the release as a draft
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SITE_ORIGIN="https://butter-site-4i1.pages.dev"
BASE="$SITE_ORIGIN/dl"
BUCKET="butter-downloads"
NEED_MINUTES="${NEED_MINUTES:-90}"
WORK="$(mktemp -d)"
REPO=""
DRY=0
FLIPPED=0

step() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m  x %s\033[0m\n' "$*" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,26p' "${BASH_SOURCE[0]}" | sed -e 's/^# \{0,1\}//' -e '/^$/q'; exit 0 ;;
    *) die "unknown argument: $arg" ;;
  esac
done

cleanup() {
  rc=$?
  if [[ $FLIPPED == 1 && "${KEEP_VISIBILITY:-0}" != 1 && -n "$REPO" ]]; then
    step "restoring repository visibility: private"
    gh repo edit "$REPO" --visibility private --accept-visibility-change-consequences \
      || warn "could not set the repo private again — do it by hand"
  fi
  rm -rf "$WORK"
  exit $rc
}

# ---------------------------------------------------------------- preflight --
step "preflight"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git repository"
[[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] || die "release from main, not $(git rev-parse --abbrev-ref HEAD)"
[[ -z "$(git status --porcelain)" ]] || { git status --short; die "working tree has changes — commit or stash first"; }
command -v gh >/dev/null || die "gh is not installed"
command -v python3 >/dev/null || die "python3 is not installed"
gh auth status >/dev/null 2>&1 || die "gh is not logged in"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
trap cleanup EXIT
if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
  KEY_FILE="$HOME/.tauri/butter-updater.key"
  [[ -f "$KEY_FILE" ]] || die "no updater key: export TAURI_SIGNING_PRIVATE_KEY"
  TAURI_SIGNING_PRIVATE_KEY="$(cat "$KEY_FILE")"
fi
export TAURI_SIGNING_PRIVATE_KEY
npx wrangler whoami >/dev/null 2>&1 || die "wrangler is not logged in (npx wrangler login)"
echo "   repo $REPO, site $SITE_ORIGIN"

# --------------------------------------------------------------------- bump --
step "bump version"
OLD="$(python3 -c 'import json;print(json.load(open("desktop/package.json"))["version"])')"
python3 scripts/bump_version.py
VERSION="$(python3 -c 'import json;print(json.load(open("desktop/package.json"))["version"])')"
TAG="v$VERSION"
[[ "$VERSION" != "$OLD" ]] || die "version did not change"
git add -A
git commit -q -m "release $VERSION"
git tag "$TAG"
echo "   $OLD -> $VERSION"

# -------------------------------------------------------------------- quota --
# GitHub bills per job, rounded up to the minute, times the runner multiplier
# (linux 1x, windows 2x, macos 10x). The runs/{id}/timing endpoint reports 0 for
# this account, so the numbers come from the jobs endpoint instead.
step "checking Actions quota"
VISIBILITY="$(gh repo view --json visibility --jq .visibility)"
if ! __quota_out="$(python3 scripts/quota_remaining.py)"; then
  warn "quota probe failed — treating the quota as exhausted"
  __quota_out="9999 0"
fi
USED_MIN="${__quota_out%% *}"
REMAIN="${__quota_out##* }"
echo "   used ~$USED_MIN min, remaining ~$REMAIN"

# A run that dies in seconds with no runner assigned means the quota is spent,
# whatever the arithmetic above thinks.
if [[ "$VISIBILITY" != "PUBLIC" ]]; then
  LAST="$(gh run list --workflow build.yml --limit 1 --json databaseId,createdAt,conclusion --jq '.[0].databaseId' 2>/dev/null || true)"
  if [[ -n "$LAST" ]]; then
    DEAD="$(gh api "/repos/$REPO/actions/runs/$LAST/jobs?per_page=20" \
      --jq '[.jobs[]|select(.runner_name == "" or .runner_name == null)]|length' 2>/dev/null || echo 0)"
    TOTAL="$(gh api "/repos/$REPO/actions/runs/$LAST/jobs?per_page=20" --jq '.total_count' 2>/dev/null || echo 0)"
    if [[ "${DEAD:-0}" != 0 && "$DEAD" == "$TOTAL" ]]; then
      warn "last run ($LAST) never got a runner — quota is exhausted"
      REMAIN=0
    fi
  fi
fi

if [[ "$VISIBILITY" == "PUBLIC" ]]; then
  echo "   repo is already public — minutes are free"
elif [[ "${KEEP_VISIBILITY:-0}" == 1 ]]; then
  echo "   KEEP_VISIBILITY=1 — staying private"
elif (( REMAIN >= NEED_MINUTES )); then
  echo "   enough quota, staying private"
elif [[ $DRY == 1 ]]; then
  echo "   dry run: would flip to public"
else
  step "flipping repository to public (public repos do not bill minutes)"
  gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences
  FLIPPED=1
fi

if [[ $DRY == 1 ]]; then
  step "dry run — dropping the local commit and tag"
  git tag -d "$TAG" >/dev/null 2>&1 || true
  git reset -q --hard HEAD~1
  exit 0
fi

# -------------------------------------------------------------------- build --
step "pushing $TAG and waiting for CI"
git push origin main
git push origin "$TAG"
SHA="$(git rev-parse HEAD)"
RUN=""
for _ in $(seq 1 30); do
  RUN="$(gh run list --workflow build.yml --commit "$SHA" --limit 5 \
         --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
  [[ -n "$RUN" ]] && break
  sleep 5
done
[[ -n "$RUN" ]] || die "no workflow run appeared for $SHA"
echo "   run $RUN"
if ! gh run watch "$RUN" --interval 20 --exit-status >/dev/null 2>&1; then
  gh run view "$RUN" --log-failed | tail -60 || true
  die "CI failed — nothing published; fix it and re-run (the bump commit is already pushed)"
fi

# ---------------------------------------------------------------- artefacts --
step "downloading artefacts"
gh run download "$RUN" -D "$WORK"
EXE="$(find "$WORK" -name '*_x64-setup.exe' | head -1)"
DMG="$(find "$WORK" -name '*.dmg' | head -1)"
MAC_UPD="$(find "$WORK" -name '*.app.tar.gz' | head -1)"
[[ -n "$EXE" && -f "$EXE.sig" ]] || die "windows installer or its signature is missing"
[[ -n "$DMG" ]] || die "dmg is missing"
[[ -n "$MAC_UPD" && -f "$MAC_UPD.sig" ]] || die "mac updater bundle or its signature is missing"

# ------------------------------------------------------------------- upload --
step "uploading to R2"
find "$WORK" -type f \( -name '*_x64-setup.exe' -o -name '*_x64-setup.exe.sig' -o -name '*.dmg' \
  -o -name '*.app.tar.gz' -o -name '*.app.tar.gz.sig' \) -print0 |
while IFS= read -r -d '' f; do
  npx wrangler r2 object put "$BUCKET/releases/v$VERSION/${f##*/}" --file "$f" --remote >/dev/null
  echo "   ${f##*/}"
done

step "writing updater manifest"
MANIFEST="$WORK/latest.json"
python3 - "$MANIFEST" "$VERSION" "$BASE" "$MAC_UPD" "$EXE" <<'PY'
import json, sys, urllib.request

out, version, base, mac, exe = sys.argv[1:6]
platforms = {
    "darwin-aarch64": {
        "signature": open(mac + ".sig").read().strip(),
        "url": f"{base}/releases/v{version}/{mac.rsplit('/', 1)[-1]}",
    },
    "windows-x86_64": {
        "signature": open(exe + ".sig").read().strip(),
        "url": f"{base}/releases/v{version}/{exe.rsplit('/', 1)[-1]}",
    },
}
try:  # a retried release may already have entries for this version live
    with urllib.request.urlopen(f"{base}/latest.json", timeout=15) as resp:
        live = json.load(resp)
    if live.get("version") == version:
        for key, entry in live.get("platforms", {}).items():
            platforms.setdefault(key, entry)
except Exception:
    pass
json.dump({"version": version, "notes": "",
           "pub_date": __import__("datetime").datetime.utcnow().isoformat() + "Z",
           "platforms": platforms}, open(out, "w"), indent=2)
PY
npx wrangler r2 object put "$BUCKET/latest.json" --file "$MANIFEST" --content-type application/json --remote >/dev/null
echo "   $BASE/latest.json"

# --------------------------------------------------------------------- site --
step "swapping the site download links"
python3 - "$VERSION" "$DMG" "$EXE" <<'PY'
import pathlib, re, sys

version, dmg, exe = sys.argv[1:4]
page = pathlib.Path("site/public/index.html")
html = page.read_text(encoding="utf-8")
for path, pattern, label in (
    (dmg, r'/dl/releases/v[^"]+?/Butter_[^"]+?_aarch64\.dmg', "macOS"),
    (exe, r'/dl/releases/v[^"]+?/Butter_[^"]+?_x64-setup\.exe', "Windows"),
):
    href = f"/dl/releases/v{version}/{path.rsplit('/', 1)[-1]}"
    html, n = re.subn(pattern, href, html)
    if n != 1:
        sys.exit(f"{label} link matched {n} times")
    size = round(pathlib.Path(path).stat().st_size / 1e6)
    html = re.sub(rf'(href="{re.escape(href)}" download>.*?<span class="dl__meta">[^<]*?· )\d+ MB',
                  rf"\g<1>{size} MB", html, flags=re.S)
page.write_text(html, encoding="utf-8")
print(f"   index.html -> {version}")
PY
(cd site && npx wrangler pages deploy public --project-name butter-site --branch main --commit-dirty=true >/dev/null)
echo "   $SITE_ORIGIN/ deployed"

# ------------------------------------------------------------------ release --
if [[ "${NO_PUBLISH:-0}" != 1 ]]; then
  step "publishing release $TAG"
  gh release edit "$TAG" --draft=false >/dev/null || warn "could not un-draft $TAG — publish it by hand"
else
  warn "NO_PUBLISH=1 — $TAG stays a draft"
fi

cat <<EOF

done. v$VERSION is live.
  site:     $SITE_ORIGIN/
  manifest: $BASE/latest.json
  mac:      $BASE/releases/v$VERSION/${DMG##*/}
  windows:  $BASE/releases/v$VERSION/${EXE##*/}
EOF
