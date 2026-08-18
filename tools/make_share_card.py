#!/usr/bin/env python3
"""Draw docs/share.png, the image link previews use.

    python tools/make_share_card.py

The PNG is committed rather than built in CI on purpose. It is drawn with a
system font, and font versions differ between machines, so a build step would
produce a slightly different file on every runner and there would be no stable
answer to "is this current?". Committing it means the file that ships is the
file someone looked at. Run this by hand when the card should change.

Nothing on the card is a claim: it names the tools that exist and who made
them, and that is all.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "share.png"

# 1200x630 is what the major previews crop to. Anything else gets cut.
W, H = 1200, 630
GROUND = (11, 12, 16)
INK = (236, 238, 243)
MUTED = (145, 152, 168)
ACCENT = (139, 124, 255)

FONTS = Path("/usr/share/fonts/truetype/dejavu")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def main() -> int:
    img = Image.new("RGB", (W, H), GROUND)
    d = ImageDraw.Draw(img)

    # A rule in the accent colour, the one piece of the site's identity that
    # survives being shrunk to a thumbnail.
    d.rectangle([0, 0, W, 8], fill=ACCENT)

    # The loudness page's meter bars, which is the one motif the site already
    # owns. Decoration only: it carries no reading and states no number.
    bars = [0.32, 0.62, 0.45, 0.86, 0.40, 0.70, 0.28, 0.54]
    bw, gap, base, top = 26, 20, 470, 150
    x = W - 72 - (len(bars) * bw + (len(bars) - 1) * gap)
    for i, frac in enumerate(bars):
        h = int((base - top) * frac)
        shade = tuple(int(c * (0.45 + 0.55 * frac)) for c in ACCENT)
        d.rounded_rectangle([x, base - h, x + bw, base], radius=6, fill=shade)
        x += bw + gap

    brand = font("DejaVuSansMono-Bold.ttf", 30)
    d.text((72, 92), "P R E F L I G H T", font=brand, fill=INK)

    head = font("DejaVuSans-Bold.ttf", 66)
    d.text((72, 168), "Free tools for", font=head, fill=INK)
    d.text((72, 246), "releasing music", font=head, fill=ACCENT)

    body = font("DejaVuSans.ttf", 27)
    d.text(
        (72, 356),
        "Cover art, loudness, whole-release delivery,\nrelease checklist, split sheets.",
        font=body,
        fill=MUTED,
        spacing=12,
    )

    small = font("DejaVuSans.ttf", 23)
    d.text((72, 468), "Everything runs in your browser. Nothing is uploaded.", font=small, fill=MUTED)

    d.rectangle([72, 528, W - 72, 529], fill=(36, 40, 50))
    foot = font("DejaVuSans.ttf", 24)
    d.text((72, 554), "Gabriel G Alonso", font=foot, fill=INK)
    footm = font("DejaVuSans.ttf", 24)
    w = d.textlength("Gabriel G Alonso", font=foot)
    d.text((72 + w, 554), "  ·  mixing & mastering, Berlin", font=footm, fill=MUTED)

    # optimize=True keeps it well under the 5 MB most scrapers will fetch.
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
