#!/usr/bin/env python3
"""Derive the Artifact copies of the docs/ pages, ready to publish.

The published artifacts must not carry `<!doctype html>`, `<html lang>` or the
charset meta, because the Artifact host supplies that wrapper itself. The
docs/ copies do need them. Deriving that by hand every time is how the two
drift apart, so this does it in one step.

Run:  python tools/sync_artifacts.py [--out DIR] [--check]

--check exits non-zero if the derived copies differ from what is already in
the output directory, which answers "are the published artifacts stale?"
without publishing anything.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Only the pages whose artifact filename differs from their docs/ filename,
# because those artifacts were published under their own titles and the URLs
# must stay stable. Everything else keeps its name.
#
# Pages are discovered, not listed: a hardcoded list here meant splits.html
# shipped with no artifact copy at all, which is the same bug the test suites
# had for the same reason.
RENAMED = {
    "index.html": "preflight.html",
    "cover.html": "coverforge.html",
}


# An artifact is one page with no siblings, reached by its own URL. The error
# page is the one page that makes no sense in that form: it exists to catch
# someone who asked the site for a URL it does not have, and nobody arrives at
# an artifact by mistyping. Deriving a copy would only produce a file nobody
# publishes, sitting in the output directory looking like an orphan.
NOT_AN_ARTIFACT = {"404.html"}


def pages() -> dict[str, str]:
    return {
        p.name: RENAMED.get(p.name, p.name)
        for p in sorted(DOCS.glob("*.html"))
        if p.name not in NOT_AN_ARTIFACT
    }

# The wrapper lines the Artifact host supplies itself. The language was
# hardcoded to "en", so the German Impressum stopped the strip loop at its
# `<html lang="de">` and left the charset line in the body, which then tripped
# the check below. A page may be in any language; match that rather than one.
STRIP_LINE = re.compile(
    r'^(?:<!doctype html>|<html\s+lang="[^"]*"\s*>|<meta\s+charset="utf-8"\s*/?>)$',
    re.IGNORECASE,
)


# An artifact is a single page with no siblings, so `href="index.html"` in its
# footer resolves to nothing at all: every published copy carried a dead "all
# tools" link, and after the Impressum went in, a dead Impressum link too.
# Point them at the live site instead, which is where those pages actually are.
SITE = "https://notgabriels-sys.github.io/albumdesign/"
INTERNAL_HREF = re.compile(r'href="(?!https?:|mailto:|#)([A-Za-z0-9._-]+\.html)"')


def absolutise(body: str) -> str:
    return INTERNAL_HREF.sub(lambda m: f'href="{SITE}{m.group(1)}"', body)


def derive(page: Path) -> str:
    lines = page.read_text(encoding="utf-8").split("\n")
    while lines and STRIP_LINE.match(lines[0].strip()):
        lines.pop(0)
    while lines and lines[-1].strip() in ("", "</html>"):
        if lines[-1].strip() == "</html>":
            lines.pop()
            continue
        lines.pop()
    body = absolutise("\n".join(lines) + "\n")
    for line in body.split("\n"):
        if STRIP_LINE.match(line.strip()):
            raise SystemExit(
                f"{page.name}: {line.strip()} still present after stripping; check the header"
            )
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="where to write the artifact copies")
    ap.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = ap.parse_args()

    out = Path(args.out) if args.out else ROOT / "build" / "artifacts"
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)

    # Both loops below report success on an empty loop, so a run that found no
    # pages printed "artifact copies are current" and exited 0. The write mode
    # is CI's "artifact copies derive cleanly" gate, so that green meant
    # nothing was derived rather than everything derived cleanly. A check that
    # read nothing has not checked anything.
    found = pages()
    if not found:
        print(f"no pages found in {DOCS}", file=sys.stderr)
        print("nothing was derived, so nothing was checked", file=sys.stderr)
        return 2

    stale = []
    for src_name, dst_name in found.items():
        page = DOCS / src_name
        if not page.exists():
            print(f"missing {page}", file=sys.stderr)
            return 2
        body = derive(page)
        dst = out / dst_name
        if args.check:
            current = dst.read_text(encoding="utf-8") if dst.exists() else None
            if current != body:
                stale.append(dst_name)
                print(f"  STALE  {dst_name}  (from docs/{src_name})")
            else:
                print(f"  ok     {dst_name}")
        else:
            dst.write_text(body, encoding="utf-8")
            print(f"  wrote  {dst}  (from docs/{src_name})")

    # A copy for a page that no longer exists is not "current" either. The
    # loop only ever asked whether each page's copy matched, so a page deleted
    # from docs/ left its derived copy sitting in the output directory and the
    # check called the directory current with it there.
    orphans = []
    if args.check and out.is_dir():
        expected = set(found.values())
        orphans = sorted(p.name for p in out.glob("*.html") if p.name not in expected)
        for name in orphans:
            print(f"  ORPHAN {name}  (no page in docs/ derives this)")

    if args.check and (stale or orphans):
        if stale:
            print(f"\n{len(stale)} artifact copies are stale: {', '.join(stale)}")
        if orphans:
            print(f"{len(orphans)} copies have no page behind them: {', '.join(orphans)}")
        return 1
    print("\nartifact copies " + ("are current" if args.check else f"written to {out}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
