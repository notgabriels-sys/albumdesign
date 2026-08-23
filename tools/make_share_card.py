#!/usr/bin/env python3
"""Draw the images link previews use, one per page.

    python tools/make_share_card.py

The PNGs are committed rather than built in CI on purpose. They are drawn with
a system font, and font versions differ between machines, so a build step would
produce slightly different files on every runner and there would be no stable
answer to "is this current?". Committing them means the files that ship are the
files someone looked at. Run this by hand when a card should change.

There used to be exactly one card, and every page pointed at it. That is fine
for the landing page and wrong for everything else: a link to the split sheet
posted anywhere previewed as "Free tools for releasing music", which describes
the site rather than the page, so the preview did none of the work a preview
exists to do. Each page now gets its own.

Nothing on a card is a claim. Every word is read out of the page it belongs to,
from that page's own <h1> and meta description, so a card cannot say something
the page does not already say.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# 1200x630 is what the major previews crop to. Anything else gets cut.
W, H = 1200, 630
GROUND = (11, 12, 16)
INK = (236, 238, 243)
MUTED = (145, 152, 168)
ACCENT = (139, 124, 255)
RULE = (36, 40, 50)
PAD = 72

FONTS = Path("/usr/share/fonts/truetype/dejavu")

# The landing page keeps share.png. Its name is in every previously shared
# link and in the artifact copies, so renaming it would break previews that
# are already out in the world for nothing.
CARDS = {
    "index.html": "share.png",
    "cover.html": "share-cover.png",
    "loudness.html": "share-loudness.png",
    "release.html": "share-release.png",
    "delivery.html": "share-delivery.png",
    "splits.html": "share-splits.png",
    "shop.html": "share-shop.png",
    # impressum.html deliberately has none and points at the site card. It is
    # a legal notice, not something anyone shares on purpose.
}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _field(src: str, pattern: str) -> str:
    m = re.search(pattern, src)
    assert m, pattern
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()


def read(page: str) -> tuple[str, str, str]:
    """(title, headline, description), all in the page's own words."""
    src = (DOCS / page).read_text(encoding="utf-8")
    return (
        _field(src, r"<title>([^<]*)</title>"),
        _field(src, r"<h1[^>]*>(.*?)</h1>"),
        _field(src, r'<meta name="description" content="([^"]*)"'),
    )


def _wrap(draw, text: str, f, width: int) -> list[str]:
    """Wrap to a pixel width, measuring rather than guessing a character count."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=f) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _overflows(draw, lines: list[str], f, width: int) -> list[str]:
    """Lines wider than the column, which _wrap cannot prevent on its own.

    Wrapping breaks on spaces, so a single word wider than the column comes out
    on a line of its own and stays too wide. Measured: a 38-character word at
    60px produced a 1277px line in a 1056px column, drawn straight off the
    right edge, and the generator reported success.

    That is the crop bug's twin. Both are the generator producing a broken
    image and saying it worked, so both fail loudly instead.
    """
    return [line for line in lines if draw.textlength(line, font=f) > width]


def _sentences_that_fit(draw, text: str, f, width: int, max_lines: int) -> list[str]:
    """As many whole sentences of `text` as fit, never a fragment of one.

    The first version wrapped the description to a character count and sliced
    the list, which shipped a card reading "...the way the" and stopping. A
    preview that ends mid-sentence looks broken, and it looked broken in the
    one place the reader decides whether to click.

    So sentences are added whole, and if not even the first one fits this
    raises rather than cropping it. A card nobody can read is not a smaller
    card, and the fix belongs in the page's description, not in a slice.
    """
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", text) if p.strip()]
    kept: list[str] = []
    lines: list[str] = []
    for part in parts:
        trial = _wrap(draw, " ".join(kept + [part]), f, width)
        if len(trial) > max_lines or _overflows(draw, trial, f, width):
            break
        kept.append(part)
        lines = trial
    if not lines:
        raise ValueError(
            f"the first sentence of {text!r} does not fit in {max_lines} lines; "
            f"shorten the page's meta description rather than cropping the card"
        )
    return lines


def draw_card(page: str, out: Path) -> None:
    title, headline, description = read(page)

    img = Image.new("RGB", (W, H), GROUND)
    d = ImageDraw.Draw(img)

    # A rule in the accent colour, the one piece of the site's identity that
    # survives being shrunk to a thumbnail.
    d.rectangle([0, 0, W, 8], fill=ACCENT)

    # The loudness page's meter bars, the one motif the site already owns.
    # Decoration only: they carry no reading and state no number.
    #
    # They used to stand full height on the right, which cost the text a third
    # of the card and put the tallest bar straight through the headline: the
    # decoration was drawn first and the text was then measured as if it were
    # not there. Now they sit on the brand line, out of the way, and every word
    # gets the full width. Nothing is layered over anything.
    bars = [0.32, 0.62, 0.45, 0.86, 0.40, 0.70, 0.28, 0.54]
    bw, gap, base, top = 16, 12, 128, 62
    bars_left = W - PAD - (len(bars) * bw + (len(bars) - 1) * gap)
    x = bars_left
    for frac in bars:
        h = int((base - top) * frac)
        shade = tuple(int(c * (0.45 + 0.55 * frac)) for c in ACCENT)
        d.rounded_rectangle([x, base - h, x + bw, base], radius=4, fill=shade)
        x += bw + gap

    column = W - 2 * PAD

    brand = font("DejaVuSansMono-Bold.ttf", 30)
    d.text((PAD, 92), "P R E F L I G H T", font=brand, fill=INK)

    # The page's own name, so the card says which page it is before anyone
    # reads a word of the headline.
    if page != "index.html":
        eyebrow = font("DejaVuSansMono-Bold.ttf", 22)
        w = d.textlength("P R E F L I G H T", font=brand)
        left = PAD + w + 22
        # The eyebrow shares its line with the wordmark and the meter bars, so
        # it has less room than anything else on the card. Measured rather than
        # assumed, for the same reason every other line is.
        if _overflows(d, [title.upper()], eyebrow, bars_left - 24 - left):
            raise ValueError(
                f"{page}: the title {title!r} is too long for the card's eyebrow"
            )
        d.text((left, 99), title.upper(), font=eyebrow, fill=ACCENT)

    # The headline is the page's h1, at the largest size that still leaves room
    # for the description underneath. Sized by measuring, not by counting
    # characters, because a capital W and a lowercase i are not the same width.
    head_text = headline.rstrip(".")
    for size in (60, 54, 48, 42):
        head = font("DejaVuSans-Bold.ttf", size)
        head_lines = _wrap(d, head_text, head, column)
        wide = _overflows(d, head_lines, head, column)
        if len(head_lines) <= 3 and not wide:
            break
    else:
        raise ValueError(
            f"{page}: the h1 {head_text!r} will not fit the card at any size "
            f"(too many lines, or a single word wider than the column: {wide})"
        )

    y = 172
    for i, line in enumerate(head_lines):
        d.text((PAD, y), line, font=head, fill=ACCENT if i else INK)
        y += size + 10

    body = font("DejaVuSans.ttf", 26)
    y += 22
    # Whatever vertical space the headline left, in whole lines above the rule.
    room = max(1, (500 - y) // 36)
    for line in _sentences_that_fit(d, description, body, column, room):
        d.text((PAD, y), line, font=body, fill=MUTED)
        y += 36

    d.rectangle([PAD, 528, W - PAD, 529], fill=RULE)
    foot = font("DejaVuSans.ttf", 24)
    d.text((PAD, 554), "Gabriel G Alonso", font=foot, fill=INK)
    w = d.textlength("Gabriel G Alonso", font=foot)
    d.text((PAD + w, 554), "  ·  mixing & mastering, Berlin", font=foot, fill=MUTED)

    # The card carries the exact strings it was drawn from.
    #
    # Without this a card is a picture of a claim with nothing tying it to the
    # claim. Editing a page's h1 left its card showing the old headline and the
    # whole suite still passed, because the checks asserted the file existed
    # and was unique, never that it said what the page says. That is the same
    # drift this file exists to prevent, one level down.
    #
    # consistency_check.py reads these back out of the raw bytes rather than
    # importing this module, so the two agree by both being right.
    meta = PngInfo()
    meta.add_itxt("preflight:page", page)
    meta.add_itxt("preflight:title", title)
    meta.add_itxt("preflight:headline", headline)
    meta.add_itxt("preflight:description", description)

    # optimize=True keeps each one well under the 5 MB most scrapers fetch.
    img.save(out, "PNG", optimize=True, pnginfo=meta)
    print(f"  wrote {out.name} ({out.stat().st_size:,} bytes, {W}x{H})  {page}")


def main() -> int:
    for page, name in CARDS.items():
        draw_card(page, DOCS / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
