"""The artifact copies must not carry links that go nowhere.

An artifact is one page with no siblings, so a relative `href="index.html"`
resolves to nothing once published. Every artifact shipped with a dead "all
tools" link that way, and after the Impressum went in, a dead Impressum link
too. The derivation rewrites them to the live site; these pin that it rewrites
what it should and leaves alone what it should not.
"""

from __future__ import annotations

import importlib.util
import sys
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


class TestARunThatReadNothingIsNotAPass:
    """Both modes reported success on an empty loop.

    `main()` loops over `pages()` and, at the end, prints "artifact copies are
    current" (or "written to ...") and returns 0. With no pages the loop runs
    zero times and both messages are still printed, so a run that derived and
    compared nothing announced that everything was fine. The write mode is
    CI's "artifact copies derive cleanly" step, which means that green said
    nothing had been derived.

    Measured before fixing: with a docs/ holding no pages, `--check` exited 0
    saying "artifact copies are current" and the write mode exited 0 saying
    "written to ...".
    """

    def _run(self, monkeypatch, docs, argv):
        monkeypatch.setattr(sa, "DOCS", docs)
        monkeypatch.setattr(sys, "argv", ["sync_artifacts.py", *argv])
        return sa.main()

    def test_check_over_no_pages_does_not_report_current(self, tmp_path, monkeypatch):
        docs = tmp_path / "docs"
        docs.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        assert self._run(monkeypatch, docs, ["--check", "--out", str(out)]) != 0

    def test_writing_no_pages_is_not_a_clean_derivation(self, tmp_path, monkeypatch):
        # This is the mode CI runs as its gate.
        docs = tmp_path / "docs"
        docs.mkdir()
        assert self._run(monkeypatch, docs, ["--out", str(tmp_path / "out")]) != 0

    def test_it_says_where_it_looked(self, tmp_path, monkeypatch, capsys):
        docs = tmp_path / "docs"
        docs.mkdir()
        self._run(monkeypatch, docs, ["--check", "--out", str(tmp_path / "out")])
        assert str(docs) in capsys.readouterr().err

    def test_a_real_page_still_passes(self, tmp_path, monkeypatch):
        # The guard must not fire on the ordinary case.
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "only.html").write_text("<!doctype html>\n<p>hi</p>\n</html>\n")
        out = tmp_path / "out"
        assert self._run(monkeypatch, docs, ["--out", str(out)]) == 0
        assert self._run(monkeypatch, docs, ["--check", "--out", str(out)]) == 0

    def test_the_real_docs_directory_is_not_empty(self):
        # A canary: if this repo's own docs/ ever stops matching the glob, the
        # tests above would be the only thing standing between that and a
        # green CI run over nothing.
        assert sa.pages(), "docs/ has no pages, so every derivation is vacuous"


class TestACopyWithNoPageBehindItIsNotCurrent:
    """A page deleted from docs/ left its derived copy in the output directory.

    The loop only ever asked whether each page's copy matched. Nothing asked
    the reverse, so the orphan sat there and `--check` called the directory
    current with it present. Measured before fixing: exit code 0.
    """

    def _check(self, monkeypatch, docs, out):
        monkeypatch.setattr(sa, "DOCS", docs)
        monkeypatch.setattr(
            sys, "argv", ["sync_artifacts.py", "--check", "--out", str(out)]
        )
        return sa.main()

    def _seed(self, tmp_path, monkeypatch):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "only.html").write_text("<!doctype html>\n<p>hi</p>\n</html>\n")
        out = tmp_path / "out"
        monkeypatch.setattr(sa, "DOCS", docs)
        monkeypatch.setattr(sys, "argv", ["sync_artifacts.py", "--out", str(out)])
        assert sa.main() == 0
        return docs, out

    def test_an_orphan_copy_fails_the_check(self, tmp_path, monkeypatch):
        docs, out = self._seed(tmp_path, monkeypatch)
        (out / "deleted_page.html").write_text("<p>stale orphan</p>\n")
        assert self._check(monkeypatch, docs, out) != 0

    def test_it_names_the_orphan(self, tmp_path, monkeypatch, capsys):
        docs, out = self._seed(tmp_path, monkeypatch)
        (out / "deleted_page.html").write_text("<p>stale orphan</p>\n")
        self._check(monkeypatch, docs, out)
        assert "deleted_page.html" in capsys.readouterr().out

    def test_a_renamed_artifact_is_not_mistaken_for_an_orphan(
        self, tmp_path, monkeypatch
    ):
        # index.html derives preflight.html, so preflight.html has a page
        # behind it even though no file of that name is in docs/.
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "index.html").write_text("<!doctype html>\n<p>hi</p>\n</html>\n")
        out = tmp_path / "out"
        monkeypatch.setattr(sa, "DOCS", docs)
        monkeypatch.setattr(sys, "argv", ["sync_artifacts.py", "--out", str(out)])
        assert sa.main() == 0
        assert (out / "preflight.html").exists()
        assert self._check(monkeypatch, docs, out) == 0

    def test_a_non_html_file_in_the_output_is_left_alone(self, tmp_path, monkeypatch):
        docs, out = self._seed(tmp_path, monkeypatch)
        (out / "notes.txt").write_text("not an artifact\n")
        assert self._check(monkeypatch, docs, out) == 0

    def test_the_real_output_of_a_full_run_has_no_orphans(self, tmp_path):
        # The repo's own pages, derived fresh, must check clean against
        # themselves. Proves the orphan rule does not fire on a correct run.
        import subprocess

        out = tmp_path / "artifacts"
        w = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "sync_artifacts.py"), "--out", str(out)],
            capture_output=True,
            text=True,
        )
        assert w.returncode == 0, w.stderr
        c = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "sync_artifacts.py"),
                "--check",
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert c.returncode == 0, c.stdout + c.stderr
