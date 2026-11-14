# Butter desktop shell

Tauri v2 + React 19. The Rust side owns the Python sidecar; the webview owns the UI.

```bash
pnpm install
pnpm dev          # UI only (expects a backend on 127.0.0.1:7911)
pnpm tauri dev    # full app: spawns `uv run butter` automatically
pnpm tauri build  # requires ../backend-dist/butter-backend (see ../scripts/build_sidecar.sh)
```

## Layout

```
src/
  api/client.ts        typed backend client (fetch + ws url + tauri invoke)
  hooks/               realtime context, react-query bindings, toasts
  components/          chrome (titlebar/rail), ui primitives, command palette
  views/               accounts · billing · network · logs · settings + dialogs
  styles/              tokens (theme) · kit (primitives) · per-view layers
src-tauri/src/lib.rs   sidecar lifecycle, port picking, health gate, log tail
```

## Invariants

- The UI renders nothing but a boot screen until `/api/health` answers.
- All secrets are redacted server-side; the UI never sees stored passwords.
- `Esc` closes every overlay; `⌘K` opens the palette.
