"""The artifact copies must not carry links that go nowhere.

An artifact is one page with no siblings, so a relative `href="index.html"`
resolves to nothing once published. Every artifact shipped with a dead "all
tools" link that way, and after the Impressum went in, a dead Impressum link
too. The derivation rewrites them to the live site; these pin that it rewrites
what it should and leaves alone what it should not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "sync_artifacts", ROOT / "tools" / "sync_artifacts.py"
)
sa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sa)

SITE = sa.SITE


class TestRewrites:
    def test_sibling_page(self):
        assert sa.absolutise('<a href="index.html">all tools</a>') == (
            f'<a href="{SITE}index.html">all tools</a>'
        )

    def test_impressum(self):
        assert sa.absolutise('<a href="impressum.html">Impressum</a>') == (
            f'<a href="{SITE}impressum.html">Impressum</a>'
        )

    def test_every_link_on_a_line_not_just_the_first(self):
        out = sa.absolutise('<a href="index.html">a</a><a href="shop.html">b</a>')
        assert out.count(SITE) == 2


class TestLeavesAlone:
    def test_mailto(self):
        line = '<a href="mailto:hologrampeoplemusic@gmail.com">mail</a>'
        assert sa.absolutise(line) == line

    def test_in_page_anchor(self):
        line = '<a class="skip" href="#main">Skip to content</a>'
        assert sa.absolutise(line) == line

    def test_already_absolute(self):
        line = '<a href="https://buy.stripe.com/dRm28q3Z06fM6s27JTabK02">Pay</a>'
        assert sa.absolutise(line) == line

    def test_does_not_double_rewrite_its_own_output(self):
        once = sa.absolutise('<a href="index.html">a</a>')
        assert sa.absolutise(once) == once


class TestAgainstTheRealPages:
    def test_no_relative_page_link_survives_derivation(self):
        for page in sorted((ROOT / "docs").glob("*.html")):
            body = sa.derive(page)
            leftovers = sa.INTERNAL_HREF.findall(body)
            assert not leftovers, f"{page.name} still links to {leftovers}"

    def test_the_site_links_are_actually_present(self):
        # A rewrite that silently matched nothing would pass the test above.
        body = sa.derive(ROOT / "docs" / "delivery.html")
        assert f'href="{SITE}index.html"' in body
        assert f'href="{SITE}impressum.html"' in body

    def test_every_rewritten_target_is_a_page_that_exists(self):
        for page in sorted((ROOT / "docs").glob("*.html")):
            for name in sa.INTERNAL_HREF.findall(page.read_text(encoding="utf-8")):
                assert (ROOT / "docs" / name).exists(), f"{page.name} -> {name}"
