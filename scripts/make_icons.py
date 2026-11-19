"""Generate every icon variant from one square source, with rounded corners.

The source art is full-bleed and fully opaque, so rounding has to be baked into
the pixels — a CSS border-radius does not travel to the dock, the taskbar or the
installer.

Two shapes, on purpose:

* macOS gets a superellipse ("squircle") inset by 10% on a transparent canvas,
  which is what Big Sur expects and what makes the dock icon sit correctly.
* Windows and the in-app logo get a plain rounded rectangle, full-bleed, because
  a squircle at 16-22 px reads as a blob.

Usage:  uv run python scripts/make_icons.py
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets-app-icon.png"
ICONS = ROOT / "desktop" / "src-tauri" / "icons"
PUBLIC = ROOT / "desktop" / "public"

# Tauri's icon set; each entry is (filename, pixels).
PNG_SIZES = [
    ("32x32.png", 32),
    ("64x64.png", 64),
    ("128x128.png", 128),
    ("128x128@2x.png", 256),
    ("256x256.png", 256),
    ("512x512.png", 512),
    ("icon.png", 512),
]


def squircle_mask(size: int, inset_ratio: float = 0.10, exponent: float = 4.6) -> Image.Image:
    """Transparent canvas with an opaque superellipse in the middle."""
    scale = 4  # supersample, then downscale: keeps the curve smooth at 32 px
    big = size * scale
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)

    inset = int(big * inset_ratio)
    box = (inset, inset, big - inset, big - inset)
    # Superellipse |x|^n + |y|^n = 1 sampled into a polygon.
    cx = cy = big / 2
    r = (big - 2 * inset) / 2
    points = []
    steps = 720
    for i in range(steps):
        theta = 2 * 3.141592653589793 * i / steps
        cos_t, sin_t = _cos_sin(theta)
        x = cx + r * _sgn(cos_t) * abs(cos_t) ** (2 / exponent)
        y = cy + r * _sgn(sin_t) * abs(sin_t) ** (2 / exponent)
        points.append((x, y))
    draw.polygon(points, fill=255)

    assert box  # keep the intent visible
    return mask.resize((size, size), Image.LANCZOS)


def rounded_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """Full-bleed rounded rectangle mask."""
    scale = 4
    big = size * scale
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=int(big * radius_ratio), fill=255
    )
    return mask.resize((size, size), Image.LANCZOS)


def _sgn(v: float) -> float:
    return -1.0 if v < 0 else 1.0


def _cos_sin(theta: float) -> tuple[float, float]:
    import math

    return math.cos(theta), math.sin(theta)


def render(src: Image.Image, size: int, shape: str) -> Image.Image:
    if shape == "squircle":
        # Big Sur wants padding around the shape. Build the squircle at the
        # inner size first, then centre it on a transparent canvas — masking a
        # full-canvas art would clip the outer curve back into a square.
        inner = int(size * 0.80)
        tile = src.resize((inner, inner), Image.LANCZOS).convert("RGBA")
        tile.putalpha(squircle_mask(inner, inset_ratio=0.0))
        art = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = (size - inner) // 2
        art.paste(tile, (offset, offset))
        return art

    art = src.resize((size, size), Image.LANCZOS).convert("RGBA")
    art.putalpha(rounded_mask(size))
    return art


def main() -> None:
    src = Image.open(SOURCE).convert("RGBA")

    for name, px in PNG_SIZES:
        # icon.png doubles as the Linux/in-app mark: rounded rect, full bleed.
        shape = "rounded" if name in ("icon.png", "32x32.png") else "squircle"
        render(src, px, shape).save(ICONS / name)

    # Windows .ico — rounded rect at several sizes.
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [render(src, s, "rounded") for s in ico_sizes]
    frames[-1].save(
        ICONS / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=frames[:-1],
    )

    # macOS .icns — squircle through iconutil.
    iconset = ROOT / "build" / "Butter.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for px in (16, 32, 64, 128, 256, 512, 1024):
        render(src, px, "squircle").save(iconset / f"icon_{px}x{px}.png")
        if px <= 512:
            render(src, px * 2, "squircle").save(iconset / f"icon_{px}x{px}@2x.png")
    import subprocess

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICONS / "icon.icns")],
        check=True,
    )

    # In-app titlebar mark.
    render(src, 128, "rounded").save(PUBLIC / "butter.png")

    print("icons regenerated")


if __name__ == "__main__":
    main()
