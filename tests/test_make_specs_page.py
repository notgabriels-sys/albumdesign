"""Tests for tools/make_specs_page.py.

docs/ is a static Pages root, so the page is committed rather than built at
request time. That is only safe while the committed bytes and the generator
agree, which is exactly what stopped being true for share.png and left main's
CI red. So the first test here is the one that catches drift.

The second thing worth testing is the honesty constraint the page exists
under: targets.toml's `min_source` is COVERFORGE'S floor, not the platform's
published minimum, and its own header says so. A page that printed `min_source`
under "what the platform says" would be inventing a requirement, quietly, on
the page people arrive at from a search for that exact number.
"""

from __future__ import annotations

import html
import importlib.util
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PAGE = DOCS / "specs.html"


def _load():
    spec = importlib.util.spec_from_file_location(
        "make_specs_page", ROOT / "tools" / "make_specs_page.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_specs_page"] = module
    spec.loader.exec_module(module)
    return module


msp = _load()
TARGETS = tomllib.loads((ROOT / "coverforge" / "targets.toml").read_text(encoding="utf-8"))


def test_the_shipped_page_is_what_the_generator_produces():
    """The committed file is the file the current generator writes.

    Nothing here pins a date, because the generator no longer reads a clock.
    An earlier version printed the review stamp's age, which froze a sentence
    like "this month" into a committed file and would have failed this very
    test on the first of every month.
    """
    rendered = msp.render(TARGETS["targets"], TARGETS["meta"]["reviewed"])
    assert rendered == PAGE.read_text(encoding="utf-8"), (
        "docs/specs.html is stale; run python tools/make_specs_page.py"
    )


def test_every_target_reaches_the_page():
    body = PAGE.read_text(encoding="utf-8")
    for key, target in TARGETS["targets"].items():
        assert target["name"] in body, f"{key} is missing from the page"
    assert len(TARGETS["targets"]) >= 8, "the fixture set shrank; this test is comparing almost nothing"


def test_the_platform_column_is_the_note_and_nothing_else():
    """The one number this page must not present as a platform requirement.

    `min_source` is this project's own floor, the point below which it refuses
    to render rather than upscale. Someone arrives here from a search for
    "spotify cover art size"; printing 1600 as Spotify's minimum would invent a
    requirement on the page that exists to stop exactly that.

    Asserted structurally: the cell must equal the target's own `notes`, so
    anything computed and prepended fails whatever it is worded like. The first
    version of this test looked for the literal "min 1600" and "minimum 1600px"
    and was measured NOT biting: a mutation writing "Minimum 1600px." with a
    capital M sailed through. Guessing an attacker's phrasing is not a check.
    """
    body = PAGE.read_text(encoding="utf-8")
    cells = re.findall(r"<dt>What the platform says</dt><dd>(.*?)</dd>", body, flags=re.S)
    assert len(cells) == len(TARGETS["targets"]), (
        f"found {len(cells)} platform cells for {len(TARGETS['targets'])} targets, "
        "so this test is not reading what it thinks it is"
    )
    expected = {
        html.escape(str(t.get("notes", ""))) or "No note recorded."
        for t in TARGETS["targets"].values()
    }
    assert set(cells) == expected, "a platform cell holds something other than the target's note"


def test_a_target_without_a_source_says_so_rather_than_claiming_one():
    body = PAGE.read_text(encoding="utf-8")
    uncited = [t for t in TARGETS["targets"].values() if not t.get("source")]
    cited = [t for t in TARGETS["targets"].values() if t.get("source")]
    assert uncited and cited, "one branch has no target exercising it"
    assert body.count("No published source recorded") == len(uncited)
    for target in cited:
        assert target["source"] in body


def test_the_page_states_the_review_date_without_freezing_an_age_into_it():
    """A committed file cannot honestly say "this month"."""
    line = msp.review_line("2026-08")
    assert "2026-08" in line
    for stale in ("this month", "month ago", "months ago", "in the future"):
        assert stale not in line, f"{stale!r} would start true and become false"


@pytest.mark.parametrize("bad", ["soon", "2026-13", "2026", "", "2026-00"])
def test_an_unreadable_review_date_is_called_unverified(bad):
    line = msp.review_line(bad)
    assert "could not be read" in line and "unverified" in line
    assert bad not in line or not bad, "an unreadable stamp must not be printed as if it were a date"
