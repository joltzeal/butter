#!/usr/bin/env bash
# Start `pnpm tauri dev` with exactly one shell process.
#
# A leftover dev shell from a previous run keeps its window alive; the new run
# opens a second one on the same account store, so both windows sit on the same
# 2FA prompt and it looks like the app asked twice.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pkill -f "target/debug/butter" 2>/dev/null || true
for _ in $(seq 1 40); do
  pgrep -f "target/debug/butter" >/dev/null || break
  sleep 0.25
done
pgrep -f "target/debug/butter" >/dev/null && pkill -9 -f "target/debug/butter" || true

cd "$ROOT/desktop"
exec pnpm tauri dev "$@"
