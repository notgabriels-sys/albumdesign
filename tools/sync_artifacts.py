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


def pages() -> dict[str, str]:
    return {p.name: RENAMED.get(p.name, p.name) for p in sorted(DOCS.glob("*.html"))}

STRIP_PREFIXES = ("<!doctype html>", '<html lang="en">', '<meta charset="utf-8">')


def derive(page: Path) -> str:
    lines = page.read_text(encoding="utf-8").split("\n")
    while lines and lines[0].strip().lower() in [p.lower() for p in STRIP_PREFIXES]:
        lines.pop(0)
    while lines and lines[-1].strip() in ("", "</html>"):
        if lines[-1].strip() == "</html>":
            lines.pop()
            continue
        lines.pop()
    body = "\n".join(lines) + "\n"
    for bad in STRIP_PREFIXES:
        if bad.lower() in body.lower():
            raise SystemExit(f"{page.name}: {bad} still present after stripping; check the header")
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="where to write the artifact copies")
    ap.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = ap.parse_args()

    out = Path(args.out) if args.out else ROOT / "build" / "artifacts"
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)

    stale = []
    for src_name, dst_name in pages().items():
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

    if args.check and stale:
        print(f"\n{len(stale)} artifact copies are stale: {', '.join(stale)}")
        return 1
    print("\nartifact copies " + ("are current" if args.check else f"written to {out}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
