"""Console entry point: ``uv run butter`` starts the local control plane."""

from __future__ import annotations

import os
import sys
import threading
import time


def _watch_parent() -> None:
    """Exit when the shell that spawned us is gone.

    ``kill_on_drop`` only covers a clean shutdown; a dev restart (or a crash)
    that kills the Tauri process left the sidecar listening on its old port
    forever, and the next boot quietly talked to the stale server.
    """
    pid = int(os.environ.get("BUTTER_PARENT_PID") or 0)
    if pid <= 0:
        return

    while True:
        time.sleep(2.0)
        try:
            os.kill(pid, 0)
        except OSError:
            os._exit(0)


def main() -> None:
    # When frozen into a sidecar the module is imported from ``butter.api``.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    threading.Thread(target=_watch_parent, name="parent-watchdog", daemon=True).start()
    from .api.app import main as run  # noqa: PLC0415 - import after sys.path is final

    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
