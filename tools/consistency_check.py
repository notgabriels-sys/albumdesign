#!/usr/bin/env python3
"""Assert the invariants that broke on the live site, so they cannot break again.

Every check here exists because the thing it checks actually went wrong once.
Nothing is hypothetical:

- the rate table lives on two pages and they disagreed after a reprice
- a payment button advertised EUR 25 and charged EUR 1,200 for another service
- one page said PNG was fine while the other warned against it
- two pages disagreed about whether Spotify asks you to target -14 LUFS
- a claim quoted a number from the Python verifier as if the browser produced it

Run:  python tools/consistency_check.py
Exits non-zero on any failure, so CI gates on it.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# A card button may only point at a payment host whose amount and product have
# been read through the provider's API.
#
# buy.stripe.com went on this list on 17 August 2026, after the three links now
# on the shop were created and then read back with GetPaymentLinks and
# GetPaymentLinksPaymentLinkLineItems: EUR 45, 160 and 190, every one
# tax_behavior "inclusive" with automatic_tax off and amount_tax 0. The two
# links that were there before, both EUR 160 tax-exclusive at URLs that were
# the test slugs with test_ removed, are deactivated.
#
# paypal.me went on this list on 22 August 2026, on a different basis, and the
# difference is the whole reason it is allowed. A PayPal.Me link carries its
# amount and currency in the URL path (paypal.me/<handle>/45EUR requests EUR
# 45.00), documented by PayPal itself. There is no stored object holding a
# second, different amount, so the failure that put a live EUR 1,200 charge
# behind a EUR 25 label cannot take this shape: the amount is on the face of
# the link, and paypal_amount_mismatches() below asserts it against the rate
# table on the same page.
#
# What is NOT established here: which of Gabriel's two PayPal accounts the
# handle sits on. paypal.me is blocked by the egress proxy and the PayPal MCP
# server has returned 401 on every attempt, so the handle rests on his
# statement that he read it out of the merchant dashboard while signed in to
# the business account. That is a recipient question, not an amount question.
#
# Do not extend this to paypal.com/ncp/ or any other PayPal link shape. Those
# put the amount back in a stored object nobody here can read.
#
# Adding a host here is a claim that someone read the objects. Do not add one
# because a link looks right.
VERIFIED_PAYMENT_HOSTS: set[str] = {"buy.stripe.com", "paypal.me"}

# Some links name a payment provider without being able to take money: the
# privacy statement a data protection notice has to cite, for instance. Those
# are listed one exact URL at a time rather than by loosening the rule above,
# because "the host contains stripe" is exactly the sloppiness this check
# exists to prevent. A URL here must be a page that cannot charge anyone.
NON_PAYMENT_PROVIDER_LINKS: set[str] = {
    "https://stripe.com/privacy",
}

# Providers whose links must be read before they can ship. paypal stays in this
# pattern even though paypal.me is now verified: the pattern is what drags a
# link into the check at all, and VERIFIED_PAYMENT_HOSTS is what lets one
# through. Keeping paypal here is what makes a paypal.com/ncp/ link fail.
PAYMENT_PROVIDERS = r"(stripe|paypal|gumroad|lemonsqueezy|ko-fi|buymeacoffee)"

# Every PayPal.Me href on a page, with whatever follows the handle. Matching
# the bare handle too is deliberate: paypal.me/<handle> with no amount opens a
# box the payer types into, so a button labelled "Mastering, pay EUR 45"
# pointing at one promises a price it does not request.
_PAYPAL_ME_HREF = re.compile(
    r'href="https?://(?:www\.)?paypal\.me/([^"/]+)(/[^"]*)?"', re.I
)
_PAYPAL_ME_PATH = re.compile(r"^/([\d.,]+)([A-Za-z]{3})?/?$")


def unverified_payment_links(body: str) -> list[str]:
    """Payment links in `body` that nobody has read the objects behind.

    Pulled out of main() so it can be tested against pages that do not exist.
    Running the check over the real pages only ever proves the pages are clean,
    which is not the same as proving the check would catch a dirty one.
    """
    return [
        u
        for u in re.findall(r'href="(https?://[^"]+)"', body)
        if re.search(PAYMENT_PROVIDERS, u, re.I)
        and not any(h in u for h in VERIFIED_PAYMENT_HOSTS)
        and u not in NON_PAYMENT_PROVIDER_LINKS
    ]


def paypal_amount_mismatches(body: str, table_text: str) -> list[str]:
    """PayPal.Me links whose URL amount is not a price the page charges.

    The amount sits in the path rather than in a stored object, so unlike a
    Stripe link this one can be checked from here. Three ways it can be wrong,
    and all three have to fail: an amount the rate table never quotes, a
    missing currency so the charge depends on an account setting nobody on the
    page can see, and a currency that is not the one the prices are written in.

    Takes the table text rather than reading it, so a test can hand it a page
    that does not exist. Checking only the real shop proves the shop is clean,
    never that the check would catch a dirty one.
    """
    problems: list[str] = []
    for handle, path in _PAYPAL_ME_HREF.findall(body):
        matched = _PAYPAL_ME_PATH.match(path or "")
        if not matched:
            problems.append(
                f"paypal.me/{handle}{path or ''} requests no fixed amount, so the payer "
                f"types their own while the button names a price"
            )
            continue
        amount, currency = matched.group(1), matched.group(2)
        if not currency:
            problems.append(
                f"paypal.me/{handle}/{amount} names no currency, so what it charges "
                f"depends on the account's default rather than on this page"
            )
        elif currency.upper() != "EUR":
            problems.append(
                f"paypal.me/{handle} link charges {amount} {currency.upper()} "
                f"while the page quotes euros"
            )
        elif f"€{amount}" not in table_text:
            problems.append(
                f"paypal.me/{handle} link charges €{amount}, which the rate table does not quote"
            )
    return problems

# An em dash is never used in prose written for Gabriel. A few uses are not
# prose and stay: the glyph alone as a string, standing in for a value that has
# not been measured yet; a release title that genuinely contains one; and the
# verbatim quote of a Stripe product name, which would stop being a quote if it
# were edited. Anything else is a typo against the house style, so name the
# exceptions rather than allow the glyph.
#
# Blank each exception out and see what is left, rather than counting. Counting
# made two mistakes: it accepted any em dash that merely shared a line with an
# allowed literal, and it reported a false failure whenever two exceptions
# overlapped, because the same dash was then counted twice.
_EM_DASH_OK = (
    '"—"',  # placeholder for a value not measured yet
    "'—'",  # the same, single-quoted
    "Duress — Vol. 1",  # a release title, not our prose
    'Speech Audio QC — Full Audit',  # quoted Stripe product name
    "'Lack of Fate — Untitled #3'",  # slugify example: the point is the dash
)


# The placeholder always sits in a fallback position (`?"—":x`, `m[0]||"—"`),
# never glued to a neighbouring string. Writing the glyph back as a separator,
# `"<b>"+word+"</b>"+"—"+label`, is prose wearing the placeholder's clothes, so
# reject a quoted dash adjacent to a concatenation operator before anything else.
_EM_DASH_SMUGGLED = re.compile(r'\+\s*["\']—["\']|["\']—["\']\s*\+')


def _em_dash_allowed(line: str) -> bool:
    if _EM_DASH_SMUGGLED.search(line):
        return False
    rest = line
    for ok in _EM_DASH_OK:
        rest = rest.replace(ok, "")
    return "—" not in rest


failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if not ok and detail else ""))
    if not ok:
        failures.append(f"{name}: {detail}" if detail else name)


def pages() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(DOCS.glob("*.html"))}


def main() -> int:
    src = pages()
    if not src:
        print(f"no pages found in {DOCS}", file=sys.stderr)
        return 2

    print("=== prices agree across every page that quotes them ===")
    tables = {
        name: re.findall(r'<td class="n">(€[\d.,]+)</td>', body)
        for name, body in src.items()
    }
    quoting = {n: v for n, v in tables.items() if v}
    check(
        "at least one page quotes a rate table",
        bool(quoting),
        "no rate table found; if rates moved off the site, delete this check",
    )
    if quoting:
        distinct = {tuple(v) for v in quoting.values()}
        check(
            f"rate tables identical across {', '.join(quoting)}",
            len(distinct) == 1,
            f"{ {n: v for n, v in quoting.items()} }",
        )

    print("\n=== no unverified payment link can reach a page ===")
    for name, body in src.items():
        pay = unverified_payment_links(body)
        check(
            f"{name} has no unverified payment link",
            not pay,
            f"{pay} - read the amount and product through the provider API, then add its host "
            f"to VERIFIED_PAYMENT_HOSTS in this file",
        )

    print("\n=== a page naming a price must not contradict the rate table ===")
    # A button saying "Pay X" while the table says something else is the exact
    # shape of the EUR 25 / EUR 1,200 mismatch.
    for name, body in src.items():
        buttons = re.findall(r">\s*(Pay[^<]{0,40})<", body)
        for label in buttons:
            amounts = re.findall(r"€\s?([\d.,]+)", label)
            for amount in amounts:
                in_table = f"€{amount}" in "".join(tables.get(name, []))
                check(
                    f"{name} button '{label.strip()}' quotes a price that appears in its table",
                    in_table,
                    "a button naming an amount the page does not otherwise quote is how the "
                    "wrong-checkout bug looked",
                )

    print("\n=== every card link quotes a price the page actually charges ===")
    # The failure this exists for: a button reading "Pay EUR 25" that charged
    # EUR 1,200 for a different service. The amount a customer is promised has
    # to be one the rate table on the same page states.
    for name, body in src.items():
        anchors = re.findall(
            r'<a\b[^>]*href="https?://([^"/]+)/[^"]*"[^>]*>(.*?)</a>', body, re.S
        )
        for host, text in anchors:
            if not any(h in host for h in VERIFIED_PAYMENT_HOSTS):
                continue
            quoted = re.findall(r"€\s?([\d.,]+)", re.sub(r"<[^>]+>", "", text))
            check(
                f"{name} card link '{re.sub(r'<[^>]+>', '', text).strip()}' quotes an amount from its table",
                bool(quoted) and all(f"€{a}" in "".join(tables.get(name, [])) for a in quoted),
                f"quoted {quoted}, table has {tables.get(name, [])}. A card link must name a price "
                f"the page charges, or name none at all",
            )

    print("\n=== every PayPal.Me link charges what the URL says and the table quotes ===")
    # The one payment link whose amount can be read from here without the
    # provider's API, because PayPal.Me puts it in the path. Nothing else on
    # this page can be verified that directly, so verify it.
    for name, body in src.items():
        mismatches = paypal_amount_mismatches(body, "".join(tables.get(name, [])))
        check(
            f"{name} PayPal links charge amounts the page quotes in euros",
            not mismatches,
            f"{mismatches}",
        )

    print("\n=== tax position stated the same way wherever it appears ===")
    vat_pages = {n: b for n, b in src.items() if re.search(r"VAT|UStG", b)}
    adds_vat = {n for n, b in vat_pages.items() if re.search(r"add(s)? no VAT|no VAT added", b)}
    plus_vat = {n for n, b in vat_pages.items() if re.search(r"plus (VAT|tax)|excl\. VAT", b, re.I)}
    check(
        "no page claims VAT is added while another says it is not",
        not (adds_vat and plus_vat),
        f"no-VAT: {sorted(adds_vat)}  plus-VAT: {sorted(plus_vat)}",
    )

    print("\n=== the tools do not contradict each other on delivery advice ===")
    cover, release = src.get("cover.html", ""), src.get("release.html", "")
    if cover and release:
        cover_warns_png = "DistroKid documents JPG only" in cover
        release_says_png_fine = re.search(r"JPG or PNG", release) is not None
        check(
            "cover.html and release.html agree about PNG",
            not (cover_warns_png and release_says_png_fine),
            "cover warns on PNG while release says PNG is fine",
        )

    loud, rel = src.get("loudness.html", ""), src.get("release.html", "")
    for name, body in (("loudness.html", loud), ("release.html", rel)):
        if body:
            check(
                f"{name} does not claim Spotify never asks for -14 LUFS",
                "not a target Spotify asks you to hit" not in body
                and "not a mastering target they" not in body,
                "Spotify's own page says to target -14 LUFS; the advice can stand, the "
                "attribution cannot",
            )

    print("\n=== measured figures are attributed to the thing that measured them ===")
    if loud:
        # -22.99 is the Python verifier's result. The browser computes -23.01.
        # Quoting the former as what the page produces was wrong.
        check(
            "loudness.html does not quote the Python verifier's figure as its own",
            "-22.99" not in loud,
            "-22.99 comes from tools/verify_lufs.py; this page computes -23.01",
        )

    print("\n=== nothing is uploaded, which every page promises ===")
    for name, body in src.items():
        script = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", body, re.S))
        calls = re.findall(r"\b(fetch|XMLHttpRequest|sendBeacon|WebSocket|EventSource)\b", script)
        check(f"{name} makes no network call", not calls, f"found {sorted(set(calls))}")

    print("\n=== one contact address, spelled one way ===")
    addrs = Counter(a for b in src.values() for a in re.findall(r"mailto:([^\"?]+)", b))
    check("a single contact address is used everywhere", len(addrs) <= 1, f"{dict(addrs)}")

    print("\n=== no em dashes in prose, which is a house rule ===")
    # Everything written for him, not only the pages. The first version of this
    # check looked at docs/ alone, which left the README, the working notes and
    # the Python that generates HTML free to reintroduce the character.
    prose = dict(src)
    for extra in ("README.md", "CLAUDE.md", *sorted(p.name for p in ROOT.glob("coverforge/*.py"))):
        path = ROOT / extra if (ROOT / extra).exists() else ROOT / "coverforge" / extra
        if path.exists():
            prose[extra] = path.read_text(encoding="utf-8")
    for name, body in prose.items():
        stray = [
            line.strip()
            for line in body.split("\n")
            if "—" in line and not _em_dash_allowed(line)
        ]
        check(f"{name} has no em dash in prose", not stray, f"{stray[:2]}")

    print("\n=== internal links resolve ===")
    for name, body in src.items():
        broken = [
            h for h in re.findall(r'href="([^"#:]+\.html)[^"]*"', body) if not (DOCS / h).exists()
        ]
        check(f"{name} internal links resolve", not broken, f"{broken}")

    # Share metadata. A page with none of this still works, it just arrives
    # anywhere it is posted as a bare URL with no title and no description,
    # which is how three tool pages had been shipping. These checks exist so a
    # sixth tool cannot be added and quietly miss the whole set.
    print("\n=== share metadata ===")
    SITE = "https://notgabriels-sys.github.io/albumdesign/"
    for name, body in src.items():
        url = SITE + name
        want = {
            "description": r'<meta name="description" content="([^"]+)">',
            "canonical": r'<link rel="canonical" href="([^"]+)">',
            "og:url": r'<meta property="og:url" content="([^"]+)">',
            "og:title": r'<meta property="og:title" content="([^"]+)">',
            "og:description": r'<meta property="og:description" content="([^"]+)">',
            "og:image": r'<meta property="og:image" content="([^"]+)">',
            "twitter:card": r'<meta name="twitter:card" content="([^"]+)">',
        }
        found = {k: re.search(v, body) for k, v in want.items()}
        missing = [k for k, m in found.items() if not m]
        check(f"{name} has the share tags", not missing, f"missing {missing}")
        if missing:
            continue
        # A canonical or og:url pointing at another page is worse than none:
        # it tells a crawler this page is a copy of that one.
        check(f"{name} canonical points at itself", found["canonical"].group(1) == url,
              found["canonical"].group(1))
        check(f"{name} og:url points at itself", found["og:url"].group(1) == url,
              found["og:url"].group(1))
        title = re.search(r"<title>(.*?)</title>", body, re.S).group(1).strip()
        check(f"{name} og:title matches its title", found["og:title"].group(1) == title,
              f"{found['og:title'].group(1)!r} vs {title!r}")
        check(f"{name} og:description matches its description",
              found["og:description"].group(1) == found["description"].group(1))
        img = found["og:image"].group(1)
        check(f"{name} og:image is absolute and present",
              img.startswith(SITE) and (DOCS / img[len(SITE):]).exists(), img)

    listed = re.findall(r"<loc>([^<]+)</loc>", (DOCS / "sitemap.xml").read_text(encoding="utf-8"))
    check("the sitemap lists every page and no others",
          sorted(listed) == sorted(SITE + n for n in src),
          f"{sorted(set(listed) ^ {SITE + n for n in src})}")
    check("robots.txt points at the sitemap",
          SITE + "sitemap.xml" in (DOCS / "robots.txt").read_text(encoding="utf-8"))

    # docs/ is the web root: every file in it is served to the public. A plan
    # and a design spec were once committed to docs/superpowers/ and published,
    # agent instructions and all, and nothing failed because the sitemap check
    # only looks at .html. Name what belongs here and reject the rest, so the
    # next stray directory is a red CI run rather than a live page.
    PUBLISHABLE = {".html", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".xml", ".txt", ".webmanifest"}
    # .nojekyll is a GitHub Pages control file, not content: it stops Jekyll
    # processing the directory. Named here rather than allowing every
    # extensionless file, which would let a README back in.
    ALLOWED_BY_NAME = {".nojekyll"}
    strays = sorted(
        str(p.relative_to(DOCS))
        for p in DOCS.rglob("*")
        if p.is_file()
        and p.suffix.lower() not in PUBLISHABLE
        and p.name not in ALLOWED_BY_NAME
    )
    check("docs/ holds nothing but publishable assets", not strays,
          f"{strays} - docs/ is the public web root; notes and specs belong outside it")
    nested = sorted(str(p.relative_to(DOCS)) for p in DOCS.iterdir() if p.is_dir())
    check("docs/ has no subdirectories", not nested,
          f"{nested} - the site is flat; a directory here publishes whatever is inside it")

    print()
    if failures:
        print(f"{len(failures)} of {checks} checks FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {checks} consistency checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
