"""Console entry point: ``uv run butter`` starts the local control plane."""

from __future__ import annotations

import os
import sys


def main() -> None:
    # When frozen into a sidecar the module is imported from ``butter.api``.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    from .api.app import main as run  # noqa: PLC0415 - import after sys.path is final

    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
