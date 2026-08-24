"""The em dash guard has to bite, and has to not cry wolf.

A reviewer broke the first version of this check twice over: it accepted any
em dash that merely shared a line with an allowed literal, and it failed on a
legitimate placeholder written with single quotes. Both are pinned here, so the
guard cannot quietly go back to passing everything.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "consistency_check", Path(__file__).resolve().parent.parent / "tools" / "consistency_check.py"
)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

allowed = cc._em_dash_allowed


class TestRejectsProse:
    def test_plain_sentence(self):
        assert not allowed("<p>or click to choose a file — it never leaves your device</p>")

    def test_footer(self):
        assert not allowed("<span>Studio Shop — Gabriel G Alonso.</span>")

    def test_sharing_a_line_with_an_allowed_literal_does_not_launder_it(self):
        # The bug: counting dashes let a real one ride along beside a placeholder.
        assert not allowed('x?"—":y; vt.textContent="Not ready — fix the red items";')

    def test_glyph_smuggled_back_as_a_separator(self):
        # The obvious way to undo the fix in cover.html, so it must not pass.
        assert not allowed('el.innerHTML="<b>"+word+"</b>"+"—"+label+"</div>";')
        assert not allowed('el.innerHTML="<b>"+word+"</b> "+"—"+" "+label;')

    def test_dash_inside_an_attribute(self):
        assert not allowed('<img alt="a wide — shot">')


class TestAllowsTheRealExceptions:
    def test_double_quoted_placeholder(self):
        assert allowed('["Aspect",w&&h?(w===h?"1:1 square":"x"):"—"],')

    def test_single_quoted_placeholder(self):
        # This file's own HTML builders use single quotes, so the guard must too.
        assert allowed("var v = measured ? fmt(x) : '—';")

    def test_fallback_placeholder(self):
        assert allowed('var out=["SPLIT SHEET","Track: "+(m[0]||"—"),"Artist: "+(m[1]||"—")];')

    def test_release_title(self):
        assert allowed('<div class="kh"><h3>Duress — Vol. 1</h3><span>18</span></div>')

    def test_quoted_stripe_product_name(self):
        assert allowed('turned out to be a 1,200 "Speech Audio QC — Full Audit (50% deposit)",')

    def test_slugify_example(self):
        assert allowed("""    \"\"\"'Lack of Fate — Untitled #3' -> 'lack-of-fate-untitled-3'.\"\"\"""")

    def test_two_exceptions_on_one_line(self):
        # Counting reported a false failure when one line carried two of them.
        assert allowed('<h3>Duress — Vol. 1</h3><script>var v=x?"—":y</script>')

    def test_bare_dash_in_markup_is_still_prose(self):
        # Not an exception: outside a string literal there is nothing to tell a
        # placeholder apart from a sentence, so it has to be spelled some other way.
        assert not allowed('<td class="v">—</td>')

    def test_line_without_any_dash(self):
        assert allowed("<p>nothing to see</p>")
