#!/usr/bin/env python3
"""Generate docs/specs.html from coverforge/targets.toml.

    python tools/make_specs_page.py

The page is committed rather than built at request time, because docs/ is a
static GitHub Pages root. A test asserts the committed file is what this
script produces, the same guard the share cards carry, because a generated
file that nobody re-checks is a copy that drifts.

Why generate it at all: the platform numbers already live in targets.toml with
their sources beside them. Re-typing them into a page would be the second copy
that this repo keeps learning about the hard way.

The one thing this script must not do is flatten two different numbers into
one. `min_source` is COVERFORGE'S floor, the point below which it refuses to
render a target rather than upscale. It is not the platform's published
minimum, and targets.toml says so in its own header. The platform's number
lives in the target's `notes` prose, with `source` pointing at the page it came
from. So the page prints the note as the platform's side, the render spec as
this project's side, and labels which is which.
"""

from __future__ import annotations

import html
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "coverforge" / "targets.toml"
OUT = ROOT / "docs" / "specs.html"

TITLE = "Cover Art Requirements by Platform"
DESCRIPTION = (
    "What Spotify, Apple Music, Bandcamp, Beatport, SoundCloud and Instagram "
    "ask for in release cover art, each with the page it came from and the "
    "date it was last read."
)
HEADLINE = "Every cover art spec, with its source"

GROUP_LABELS = {
    "dsp": "Stores and streaming",
    "social": "Social",
    "web": "Web",
    "archive": "Archive",
}


def human_bytes(n: int | None) -> str:
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} MB"
    return f"{n / 1_000:.0f} KB"


def load() -> tuple[dict, str]:
    raw = tomllib.loads(TARGETS.read_text(encoding="utf-8"))
    return raw.get("targets", {}), str(raw.get("meta", {}).get("reviewed", ""))


def review_line(reviewed: str) -> str:
    """State the review date. Deliberately not its age.

    The first version printed "9 months ago", computed against the clock at
    generation time and then frozen into a committed file. That is a sentence
    that starts true and quietly becomes false, in a file nobody regenerates,
    on the page whose entire promise is that its numbers are dated. It would
    also have failed its own drift test on the first of every month.

    An age is only honest where it is computed when it is read, so it lives in
    `coverforge targets`, which recomputes on every run. Here the page states
    the date and lets the reader do the subtraction.
    """
    parts = reviewed.split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts) or not 1 <= int(parts[1]) <= 12:
        return (
            "The review date recorded for these specs could not be read, so treat "
            "every number below as unverified."
        )
    return f"Last reviewed {html.escape(reviewed)}."


def rows(targets: dict) -> str:
    out: list[str] = []
    for group, label in GROUP_LABELS.items():
        members = [(k, v) for k, v in targets.items() if v.get("group") == group]
        if not members:
            continue
        out.append(f'\n      <h2 id="{group}">{html.escape(label)}</h2>')
        for key, t in members:
            name = html.escape(str(t.get("name", key)))
            w, h = t.get("width"), t.get("height")
            fmt = str(t.get("format", "")).upper()
            cap = human_bytes(t.get("max_bytes"))
            delivers = f"{w} &times; {h} px {html.escape(fmt)}"
            if cap:
                delivers += f", up to {cap}"
            note = html.escape(str(t.get("notes", ""))) or "No note recorded."
            source = str(t.get("source", ""))
            # A link when the file holds one, and an explicit sentence when it
            # does not. "No published source recorded" is a statement about
            # this repository, not about the number: Instagram's 1080 is
            # Instagram's own documented size, nobody wrote the link down.
            if source:
                cite = (
                    f'<a class="src" href="{html.escape(source)}" rel="nofollow noopener"'
                    f' target="_blank">Source</a>'
                )
            else:
                cite = '<span class="nosrc">No published source recorded</span>'
            out.append(
                f'''
      <article class="spec">
        <h3>{name}</h3>
        <dl>
          <div><dt>What this project delivers</dt><dd class="mono">{delivers}</dd></div>
          <div><dt>What the platform says</dt><dd>{note}</dd></div>
        </dl>
        {cite}
      </article>'''
            )
    return "".join(out)


def render(targets: dict, reviewed: str) -> str:
    canonical = "https://gabs-utilities.com/specs.html"
    return f'''<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{TITLE}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="favicon.ico" sizes="32x32">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="description" content="{DESCRIPTION}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Preflight">
<meta property="og:locale" content="en_GB">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:image" content="https://gabs-utilities.com/share-specs.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Link preview card. Preflight {TITLE}, headline &quot;{HEADLINE}&quot;, by Gabriel G Alonso, mixing and mastering, Berlin.">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "name": "{TITLE}",
  "description": "{DESCRIPTION}",
  "url": "{canonical}",
  "isAccessibleForFree": true,
  "offers": {{
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "EUR"
  }},
  "author": {{
    "@type": "Person",
    "name": "Gabriel G Alonso"
  }}
}}
</script>
<style>
  :root{{
    --ground:#f4f5f7; --surface:#ffffff; --surface-2:#f9fafb; --line:#e3e5ec;
    --ink:#14161c; --muted:#5c6270; --accent:#5a46e0;
    --shadow:0 1px 2px rgba(20,22,28,.06),0 8px 24px rgba(20,22,28,.06);
  }}
  @media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
    --ground:#0b0c10; --surface:#14161c; --surface-2:#181b22; --line:#272b34;
    --ink:#e7e9ee; --muted:#8a90a0; --accent:#8b7cff;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 30px rgba(0,0,0,.35);}}}}
  :root[data-theme="dark"]{{
    --ground:#0b0c10; --surface:#14161c; --surface-2:#181b22; --line:#272b34;
    --ink:#e7e9ee; --muted:#8a90a0; --accent:#8b7cff;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 30px rgba(0,0,0,.35);}}
  *{{box-sizing:border-box}} html,body{{margin:0}}
  body{{background:var(--ground);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.55;-webkit-font-smoothing:antialiased}}
  .mono{{font-family:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace}}
  /* Every link, not just the ones in the nav and footer. The note's prose
     links were unstyled and inherited the browser default blue, which the
     contrast check measured at 1.83:1 against the dark ground. */
  a{{color:var(--accent)}}
  .wrap{{max-width:880px;margin:0 auto;padding:28px 20px 64px}}
  header{{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 16px;margin-bottom:22px}}
  .brand{{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:700;
    letter-spacing:.3em;font-size:15px;text-transform:uppercase}}
  .brand b{{color:var(--accent)}}
  .page{{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-weight:700;
    letter-spacing:.16em;font-size:12px;text-transform:uppercase;color:var(--accent)}}
  h1{{font-size:29px;line-height:1.2;margin:0 0 10px;text-wrap:balance}}
  .lede{{color:var(--muted);margin:0 0 6px;max-width:62ch}}
  .reviewed{{color:var(--muted);font-size:13.5px;margin:0 0 26px}}
  h2{{font-size:13px;text-transform:uppercase;letter-spacing:.14em;color:var(--accent);
    margin:34px 0 12px}}
  .spec{{background:var(--surface);border:1px solid var(--line);border-radius:12px;
    padding:16px 18px;margin-bottom:12px;box-shadow:var(--shadow)}}
  .spec h3{{margin:0 0 10px;font-size:17px}}
  .spec dl{{margin:0}}
  .spec dl div{{display:grid;grid-template-columns:200px 1fr;gap:6px 18px;
    padding:7px 0;border-top:1px solid var(--line)}}
  .spec dl div:first-child{{border-top:0}}
  dt{{color:var(--muted);font-size:13px}}
  dd{{margin:0}}
  .src,.nosrc{{display:inline-block;margin-top:10px;font-size:13px}}
  .src{{color:var(--accent)}}
  .nosrc{{color:var(--muted)}}
  .note{{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
    padding:14px 16px;margin:0 0 8px;color:var(--muted);font-size:14px}}
  nav.tools{{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);
    display:flex;flex-wrap:wrap;gap:10px 18px;font-size:14px}}
  nav.tools a{{color:var(--accent)}}
  footer{{margin-top:26px;color:var(--muted);font-size:13px;
    display:flex;flex-direction:column;gap:6px;align-items:flex-start}}
  footer a{{color:var(--accent)}}
  footer .cta{{margin-top:2px}}
  @media (max-width:560px){{.spec dl div{{grid-template-columns:1fr}}}}
</style>

<main class="wrap">
  <header>
    <span class="brand">PRE<b>FLIGHT</b></span>
    <span class="page">{TITLE}</span>
    <span class="tag">the numbers, and where each one came from</span>
  </header>

  <h1>{HEADLINE}</h1>
  <p class="lede">{DESCRIPTION}</p>
  <p class="reviewed">{review_line(reviewed)} Platforms change these without
    much warning, so treat every number here as a starting point and check it
    against whatever your distributor currently demands.</p>

  <p class="note"><b>Two different numbers, kept apart.</b> "What the platform
    says" is the store's own published requirement, quoted from the page linked
    beneath it. "What this project delivers" is the file the
    <a href="https://github.com/notgabriels-sys/albumdesign">command line tool</a>
    renders for that target, which is sometimes deliberately stricter. Where a
    row carries no source link, nobody recorded one; that is a statement about
    this repository, not a claim that the number was invented.</p>
{rows(targets)}

  <nav class="tools">
    <b>Check a file:</b>
    <a href="cover.html">Album Cover Size Checker</a>
    <a href="splits.html">Split Sheet Maker</a>
    <a href="shop.html">Mixing and mastering</a>
  </nav>

  <footer>
    <a href="index.html">&larr; all tools</a>
    <a href="impressum.html">Impressum</a>
    <span>Generated from
      <a href="https://github.com/notgabriels-sys/albumdesign/blob/main/coverforge/targets.toml">targets.toml</a>,
      the same file the command line tool reads, so this page and the tool
      cannot disagree.</span>
    <span>{TITLE}: a free tool by <b>Gabriel G Alonso</b>, mixing &amp; mastering, Berlin.</span>
    <span class="cta">Need the record finished? <a href="shop.html">See rates and book</a>,
      or email <a href="mailto:hologrampeoplemusic@gmail.com">hologrampeoplemusic@gmail.com</a></span>
  </footer>
</main>
</html>
'''


def main() -> int:
    targets, reviewed = load()
    if not targets:
        print("no targets found in targets.toml", file=sys.stderr)
        return 2
    OUT.write_text(render(targets, reviewed), encoding="utf-8")
    print(f"wrote {OUT} ({len(targets)} targets, reviewed {reviewed or 'unknown'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
