# Butter desktop shell

Tauri v2 + React 19. The Rust side owns the Python sidecar; the webview owns the UI.

```bash
pnpm install
pnpm dev          # UI only (expects a backend on 127.0.0.1:7911)
pnpm tauri dev    # full app: spawns `uv run butter` automatically
# Release build: needs the updater key so bundles can be signed.
TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/butter-updater.key)" pnpm tauri build
# requires ../backend-dist/butter-backend (see ../scripts/build_sidecar.sh)
# release checklist: ../docs/RELEASE.md
```

## Layout

```
src/
  api/client.ts        typed backend client (fetch + ws url + tauri invoke)
  hooks/               realtime context, react-query bindings, toasts
  components/          chrome (titlebar/rail), ui primitives, command palette
  views/               accounts workspace · network · logs · settings + dialogs
  styles/              tokens (theme) · kit (primitives) · per-view layers
src-tauri/src/lib.rs   sidecar lifecycle, port picking, health gate, log tail
```

## Invariants

- The UI renders nothing but a boot screen until `/api/health` answers.
- Stored passwords come back in the clear (`password_plain`) and are shown, and
  edited, without a reveal toggle. Apple only returns the card's last digits, so
  the PAN has to be retyped on any billing save.
- `Esc` closes every overlay, focus is trapped inside it and returns to the
  opener; `⌘K` opens the palette.
- Views stay mounted while hidden, so nav does not reset scroll, filters or the
  peek panel.
- Updates come from GitHub Releases through `tauri-plugin-updater`; the signing
  key path and the release checklist live in `../docs/RELEASE.md`.
