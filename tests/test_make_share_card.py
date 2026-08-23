"""Tests for tools/make_share_card.py.

The generator had none. That is the shape packcheck.py was in when it reported
a clean pack it had never listened to, and it is how both of this generator's
first two defects survived long enough to ship: a description cropped
mid-sentence, and meter bars drawn through the headline.

Two things are worth testing here and nothing else is:

  the guards fail loudly     a generator that crops, or that draws off the
                             edge, and then reports success is the whole
                             failure mode
  the shipped cards are      running the checks over the real docs/ output is
  actually clean             the only thing that says the cards on disk are
                             the cards someone would want

The font is a system font. Every test that needs one skips when it is absent
rather than passing on a machine that could not have drawn anything.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _load():
    spec = importlib.util.spec_from_file_location(
        "make_share_card", ROOT / "tools" / "make_share_card.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_share_card"] = module
    spec.loader.exec_module(module)
    return module


msc = _load()

pytestmark = pytest.mark.skipif(
    not (msc.FONTS / "DejaVuSans.ttf").is_file(),
    reason="DejaVu is a system font; without it nothing could have been drawn",
)


@pytest.fixture
def draw():
    from PIL import Image, ImageDraw

    return ImageDraw.Draw(Image.new("RGB", (msc.W, msc.H)))


@pytest.fixture
def column():
    return msc.W - 2 * msc.PAD


# --- the guards ---------------------------------------------------------


def test_wrap_breaks_on_spaces(draw, column):
    f = msc.font("DejaVuSans.ttf", 26)
    lines = msc._wrap(draw, "one two three four five six seven", f, 120)
    assert len(lines) > 1
    assert " ".join(lines) == "one two three four five six seven"


def test_a_word_wider_than_the_column_is_reported(draw, column):
    """_wrap cannot break inside a word, so something has to notice."""
    f = msc.font("DejaVuSans-Bold.ttf", 60)
    word = "Supercalifragilisticexpialidociousness"
    lines = msc._wrap(draw, word, f, column)
    assert lines == [word], "nothing can break this, so it stays one line"
    assert msc._overflows(draw, lines, f, column) == [word]


def test_lines_that_fit_are_not_reported(draw, column):
    f = msc.font("DejaVuSans.ttf", 26)
    lines = msc._wrap(draw, "a short line", f, column)
    assert msc._overflows(draw, lines, f, column) == []


def test_sentences_are_added_whole(draw, column):
    """The first version sliced a line list and shipped "...the way the"."""
    f = msc.font("DejaVuSans.ttf", 26)
    text = "First sentence here. Second one. Third one that will not fit at all."
    got = " ".join(msc._sentences_that_fit(draw, text, f, column, 1))
    assert got.endswith("."), f"ended mid-sentence: {got!r}"
    assert got in text
    # Whole sentences only: whatever was kept is a prefix ending at a full stop.
    assert text.startswith(got)


def test_it_raises_rather_than_cropping_the_first_sentence(draw, column):
    f = msc.font("DejaVuSans.ttf", 26)
    with pytest.raises(ValueError, match="does not fit"):
        msc._sentences_that_fit(draw, "A sentence far too long to fit." * 20, f, column, 1)


def test_an_unbreakable_word_is_not_quietly_accepted(draw, column):
    """A sentence containing one is not a fit, however few lines it makes."""
    f = msc.font("DejaVuSans.ttf", 26)
    huge = "x" * 200
    with pytest.raises(ValueError, match="does not fit"):
        msc._sentences_that_fit(draw, f"{huge}.", f, column, 3)


# --- reading the page ---------------------------------------------------


def test_field_strips_tags_and_unescapes(tmp_path):
    assert msc._field("<h1>A <em>bold</em> claim</h1>", r"<h1>(.*?)</h1>") == "A bold claim"
    assert msc._field("<h1>Bell &amp; Co</h1>", r"<h1>(.*?)</h1>") == "Bell & Co"


def test_read_returns_the_pages_own_words():
    title, headline, description = msc.read("loudness.html")
    body = (DOCS / "loudness.html").read_text(encoding="utf-8")
    assert f"<title>{title}</title>" in body
    assert headline in body
    assert description in body


# --- the cards actually on disk -----------------------------------------


def _png_text(path: Path) -> dict[str, str]:
    """PNG text chunks, from the raw bytes, as consistency_check.py reads them."""
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    found: dict[str, str] = {}
    i = 8
    while i + 8 <= len(raw):
        (length,) = struct.unpack(">I", raw[i : i + 4])
        kind, data = raw[i + 4 : i + 8], raw[i + 8 : i + 8 + length]
        i += 12 + length
        if kind == b"IEND":
            break
        if kind == b"iTXt":
            keyword, rest = data.split(b"\x00", 1)
            compressed, rest = rest[0], rest[2:]
            _lang, rest = rest.split(b"\x00", 1)
            _translated, text = rest.split(b"\x00", 1)
            if compressed:
                text = zlib.decompress(text)
            found[keyword.decode("latin-1")] = text.decode("utf-8")
    return found


@pytest.mark.parametrize("page,filename", sorted(msc.CARDS.items()))
def test_every_shipped_card_records_its_page(page, filename):
    text = _png_text(DOCS / filename)
    assert text.get("preflight:page") == page
    title, headline, description = msc.read(page)
    # All three strings the card draws, not two of them. The title is printed
    # as the eyebrow and went unrecorded, so a retitled page kept an old card.
    assert text.get("preflight:title") == title
    assert text.get("preflight:headline") == headline
    assert text.get("preflight:description") == description


@pytest.mark.parametrize("page,filename", sorted(msc.CARDS.items()))
def test_every_shipped_card_would_redraw_identically(page, filename, tmp_path):
    """The committed file is the file the current generator produces.

    Cards are committed rather than built in CI because they use a system font.
    That is only safe while the committed bytes and the generator agree, and
    nothing else says they do.
    """
    out = tmp_path / filename
    msc.draw_card(page, out)
    assert out.read_bytes() == (DOCS / filename).read_bytes()


@pytest.mark.parametrize("page", sorted(msc.CARDS))
def test_no_line_on_a_card_runs_off_the_edge(page, draw, column):
    """Redraw the text decisions and measure them, rather than trusting them."""
    title, headline, description = msc.read(page)
    head_text = headline.rstrip(".")
    for size in (60, 54, 48, 42):
        f = msc.font("DejaVuSans-Bold.ttf", size)
        lines = msc._wrap(draw, head_text, f, column)
        if len(lines) <= 3 and not msc._overflows(draw, lines, f, column):
            break
    else:
        pytest.fail(f"{page}: the headline does not fit at any size")

    body = msc.font("DejaVuSans.ttf", 26)
    kept = msc._sentences_that_fit(draw, description, body, column, 3)
    assert msc._overflows(draw, kept, body, column) == []
