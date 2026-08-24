"""Tests for tools/make_favicon.py.

The icons are committed rather than built in CI, same as the share cards, so
the only thing that says the committed bytes are what the generator produces
is a test that produces them again and compares.

The two things worth asserting beyond that are the two mistakes that were
actually made while drawing these: bars that merge into one block at 16px, and
a home-screen icon drawn to the edge where iOS masks the corners off.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _load():
    spec = importlib.util.spec_from_file_location(
        "make_favicon", ROOT / "tools" / "make_favicon.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_favicon"] = module
    spec.loader.exec_module(module)
    return module


mf = _load()


def test_the_committed_svg_is_what_the_generator_writes():
    assert (DOCS / "favicon.svg").read_text(encoding="utf-8") == mf.svg()


def test_the_committed_rasters_are_what_the_generator_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "DOCS", tmp_path)
    mf.main()
    for name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        assert (tmp_path / name).read_bytes() == (DOCS / name).read_bytes(), name


def test_the_ico_carries_the_three_sizes_browsers_ask_for():
    from PIL import Image

    with Image.open(DOCS / "favicon.ico") as im:
        assert im.ico.sizes() >= {(16, 16), (32, 32), (48, 48)}


def test_four_separate_bars_survive_sixteen_pixels():
    """The failure this replaced: two bars rounded into contact and the icon
    became one block with steps in it."""
    from PIL import Image

    with Image.open(DOCS / "favicon.ico") as im:
        im.size = (16, 16)
        px = im.convert("RGBA").load()

    # Read the row through every bar and count runs of opaque pixels.
    row = 15  # the bottom row, where all four bars are present
    runs, inside = 0, False
    for x in range(16):
        opaque = px[x, row][3] > 0
        if opaque and not inside:
            runs += 1
        inside = opaque
    assert runs == 4, f"{runs} bars visible at 16px, not 4"


def test_the_bars_differ_in_height_at_sixteen_pixels():
    """Four bars of the same height is a barcode, not a meter."""
    from PIL import Image

    with Image.open(DOCS / "favicon.ico") as im:
        im.size = (16, 16)
        px = im.convert("RGBA").load()

    tops = []
    for x, _top, _bottom in mf.BARS:
        column = [y for y in range(16) if px[x + 1, y][3] > 0]
        assert column, f"no bar at x={x}"
        tops.append(min(column))
    assert len(set(tops)) == len(tops), f"bars share a height: {tops}"


def test_the_home_screen_icon_keeps_its_safe_margin():
    """iOS masks the corners off, so bars drawn to the edge lose them."""
    from PIL import Image

    with Image.open(DOCS / "apple-touch-icon.png") as im:
        assert im.size == (180, 180)
        px = im.convert("RGB").load()
        ground = tuple(mf.GROUND[:3])

        margin = 18
        edges = (
            [(x, y) for x in range(180) for y in range(margin)]
            + [(x, y) for x in range(180) for y in range(180 - margin, 180)]
            + [(x, y) for y in range(180) for x in range(margin)]
            + [(x, y) for y in range(180) for x in range(180 - margin, 180)]
        )
        painted = [p for p in edges if px[p] != ground]
        assert not painted, f"{len(painted)} pixels drawn into the masked margin"


def test_every_page_asks_for_all_three():
    """Duplicates the consistency check on purpose: this one runs in the pytest
    job, which is the only job a contributor is likely to run by hand."""
    wanted = (
        '<link rel="icon" href="favicon.svg" type="image/svg+xml">',
        '<link rel="icon" href="favicon.ico" sizes="32x32">',
        '<link rel="apple-touch-icon" href="apple-touch-icon.png">',
    )
    pages = sorted(DOCS.glob("*.html"))
    assert pages, "no pages found, so this test proved nothing"
    for page in pages:
        body = page.read_text(encoding="utf-8")
        for link in wanted:
            assert link in body, f"{page.name} is missing {link}"
