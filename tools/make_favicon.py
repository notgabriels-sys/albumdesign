#!/usr/bin/env python3
"""Draw docs/favicon.svg, docs/favicon.ico and docs/apple-touch-icon.png.

    python tools/make_favicon.py

The site had no icon at all: nine pages, no icon file, so every tab showed the
browser's blank document glyph and every page load fired a 404 for
/favicon.ico. Someone who leaves a tool open in a crowded tab strip
could not find it again, which is most of what a favicon is for.

Three files because one format does not cover it. SVG for anything current,
.ico for Windows shell icons and Safari before 17, and a 180px PNG for an iOS
home screen.

All three are drawn from ONE geometry, the 16-pixel grid below. The first
version derived the raster sizes from the SVG's 32-unit grid and the rounding
put two bars into contact: at 16px it stopped being four bars and became one
block with steps in it. Inspected at 8x, which is the only way to see it.

Like the share cards, the outputs are committed rather than built in CI, and
a test asserts the committed bytes are what this script produces.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# The meter bars, the one motif the site already owns, at the only complexity
# that survives sixteen pixels. Four bars, nothing else.
#
# 3px bars with 1px gaps is the widest layout that keeps four separate marks in
# sixteen pixels. Every other size is a whole multiple of this grid, so nothing
# lands between pixels anywhere.
#   x, top, bottom   (inclusive, on a 16x16 grid)
BARS = [(1, 8, 15), (5, 4, 15), (9, 0, 15), (13, 6, 15)]
BAR_W = 3
GRID = 16

# The light and dark accents, straight from the pages' own tokens. A favicon
# sits on the browser's tab strip rather than on the page, so the light accent
# disappears on a white strip and the dark one disappears on a dark strip. The
# SVG switches; the rasters cannot, and take the light one, which is the more
# legible of the two against both.
ACCENT_LIGHT = "#5a46e0"
ACCENT_DARK = "#8b7cff"
GROUND = (11, 12, 16, 255)


def _rgba(hex_colour: str) -> tuple[int, int, int, int]:
    h = hex_colour.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def raster(scale: int, background) -> Image.Image:
    size = GRID * scale
    img = Image.new("RGBA", (size, size), background)
    d = ImageDraw.Draw(img)
    radius = scale if scale >= 2 else 0
    for x, top, bottom in BARS:
        box = [
            x * scale,
            top * scale,
            (x + BAR_W) * scale - 1,
            (bottom + 1) * scale - 1,
        ]
        if radius:
            d.rounded_rectangle(box, radius=radius, fill=_rgba(ACCENT_LIGHT))
        else:
            d.rectangle(box, fill=_rgba(ACCENT_LIGHT))
    return img


def svg() -> str:
    """The same bars as a vector, on a 32-unit grid so the units stay whole."""
    k = 2
    rects = "\n".join(
        f'  <rect class="b" x="{x * k}" y="{top * k}" '
        f'width="{BAR_W * k}" height="{(bottom + 1 - top) * k}" rx="{k}"/>'
        for x, top, bottom in BARS
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID * k} {GRID * k}" role="img" aria-label="Preflight">
  <title>Preflight</title>
  <style>
    .b {{ fill: {ACCENT_LIGHT} }}
    @media (prefers-color-scheme: dark) {{ .b {{ fill: {ACCENT_DARK} }} }}
  </style>
{rects}
</svg>
"""


def main() -> int:
    (DOCS / "favicon.svg").write_text(svg(), encoding="utf-8")

    # The largest frame has to be the base. Saving from the 16px one wrote a
    # single-size .ico and said nothing: Pillow will not upscale, so it kept
    # 16 and silently dropped the 32 and 48 it was asked for. A test counts
    # the sizes in the committed file rather than trusting the call.
    #
    # Each entry is still the frame drawn natively at that size rather than a
    # downsample of the largest, which is what keeps the 16px one crisp.
    small, medium, large = (raster(s, (0, 0, 0, 0)) for s in (1, 2, 3))
    large.save(
        DOCS / "favicon.ico",
        sizes=[(GRID, GRID), (GRID * 2, GRID * 2), (GRID * 3, GRID * 3)],
        append_images=[small, medium],
    )

    # The home-screen icon needs a margin the favicon does not. iOS applies a
    # rounded-rectangle mask to it, so bars drawn to the edge get their corners
    # cut off. Drawn full bleed first and looked at: the outer bars ran into
    # all four edges. 144 in 180 is a whole multiple of the grid and leaves the
    # 10 per cent of safe area the mask wants.
    #
    # iOS also squares off any transparency itself, so it gets the site's own
    # ground rather than letting the system pick white.
    apple = Image.new("RGBA", (180, 180), GROUND)
    apple.paste(raster(9, GROUND), (18, 18))
    apple.convert("RGB").save(DOCS / "apple-touch-icon.png", optimize=True)

    for name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        print(f"  wrote {name} ({(DOCS / name).stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
