"""Increment the app version everywhere it is declared.

Cross-platform replacement for bump_version.sh: package.json is the source of
truth, and tauri.conf.json / Cargo.toml / butter/__init__.py follow it. Patch
number only — this ships local side-loads, not releases.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "desktop" / "package.json"


def bump(current: str) -> str:
    parts = current.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def main() -> int:
    data = json.loads(PKG.read_text(encoding="utf-8"))
    old = data["version"]
    new = bump(old)

    data["version"] = new
    PKG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    conf = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
    text = conf.read_text(encoding="utf-8")
    text = re.sub(r'"version"\s*:\s*"[^"]+"', f'"version": "{new}"', text, count=1)
    conf.write_text(text, encoding="utf-8")

    cargo = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
    lines = cargo.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("version = "):
            lines[i] = f'version = "{new}"'
            break
    cargo.write_text("\n".join(lines) + "\n", encoding="utf-8")

    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    # Only the [project] version, not dependency pins.
    text = re.sub(r'(?m)^(version\s*=\s*)"[^"]+"', f'\\1"{new}"', text, count=1)
    pyproject.write_text(text, encoding="utf-8")

    init = ROOT / "src" / "butter" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    if "__version__" in text:
        text = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new}"', text)
    else:
        text += f'\n__version__ = "{new}"\n'
    init.write_text(text, encoding="utf-8")

    print(f"{old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
