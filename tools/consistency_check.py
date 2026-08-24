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

import html
import json
import re
import struct
import sys
import zlib
from urllib.parse import urlsplit
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# The site's own address, in one place.
#
# It used to be a local in the share-metadata section while two README scans
# carried the path segment "albumdesign/" hardcoded in their regexes. Moving
# to gabs-utilities.com made both of those match nothing, and the second one
# said so: "matched link text for 0 of 5 tools". That is the counter earning
# its keep on the very next change after it was written, and it is the same
# lesson as everything else here: a fact written in two places drifts apart,
# so read it, do not retype it.
SITE = "https://gabs-utilities.com/"

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
# Who receives was the open question, and it was settled on 23 August 2026 by
# a live payment rather than by reading anything. Gabriel sent EUR 1 to
# paypal.me/gabrielgga00 from a logged-out browser and reported that the
# receipt did not arrive at notgabriels@gmail.com, his personal account. He has
# two accounts, so it landed on the business one, hologrampeoplemusic@gmail.com,
# which is also the address in the Impressum.
#
# That is an observation of where money actually went, which is what makes it
# worth more than the earlier position, where the handle rested on his memory
# of a dashboard. It is still his report rather than something read from here:
# paypal.me is blocked by the egress proxy and the PayPal MCP server has
# returned 401 on every attempt. If money ever lands in the wrong account, the
# handle is the thing to change.
#
# Do not extend this to paypal.com/ncp/ or any other PayPal link shape. Those
# put the amount back in a stored object nobody here can read.
#
# Adding a host here is a claim that someone read the objects. Do not add one
# because a link looks right.
# The contact address, which is also the one in the Impressum and the one his
# business PayPal sits on. notgabriels@gmail.com is his personal account and
# belongs on none of this: client mail and client money go to the business one.
CONTACT = "hologrampeoplemusic@gmail.com"
PERSONAL_ADDRESS = "notgabriels@gmail.com"

VERIFIED_PAYMENT_HOSTS: set[str] = {"buy.stripe.com", "paypal.me"}

# Some links name a payment provider without being able to take money: the
# privacy statement a data protection notice has to cite, for instance. Those
# are listed one exact URL at a time rather than by loosening the rule above,
# because "the host contains stripe" is exactly the sloppiness this check
# exists to prevent. A URL here must be a page that cannot charge anyone.
# Cited privacy policies, not payment links. Art. 13 DSGVO requires the notice
# to point at each processor's own policy, so these have to be linkable while
# the hosts around them stay unverified. Listed as exact URLs rather than by
# host on purpose: exempting paypal.com wholesale would let a paypal.com/ncp/
# button through, which is the shape that hid a EUR 1,200 charge.
NON_PAYMENT_PROVIDER_LINKS: set[str] = {
    "https://stripe.com/privacy",
    "https://www.paypal.com/de/legalhub/paypal/privacy-full",
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


def _host_is_verified(url: str) -> bool:
    """Is this URL's host one of the verified ones, exactly?

    The test used to be `host_string in url`, which is substring matching
    against the whole URL, and this file's own comment further up calls that
    out as the sloppiness the check exists to prevent. It let through
    paypal.me.attacker.example, notpaypal.men, buy.stripe.com.evil.example and
    any URL merely carrying "paypal.me" in a query string. Short entries make
    it worse: "paypal.me" sits inside "paypal.men".

    So parse the host and compare it whole, allowing only a leading "www.".
    """
    host = urlsplit(url).hostname or ""
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host in VERIFIED_PAYMENT_HOSTS


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
        and not _host_is_verified(u)
        and u not in NON_PAYMENT_PROVIDER_LINKS
    ]


def verified_payment_anchors(body: str) -> list[tuple[str, str]]:
    """Every (url, visible text) anchor pointing at a verified payment host.

    The href pattern deliberately matches `unverified_payment_links` rather
    than requiring a path after the host. The old one was
    `href="https?://([^"/]+)/[^"]*"`, which needs a slash, so a link with no
    path or only a query string was treated as verified by that function and
    then skipped here, reaching a page promising an amount that nothing had
    checked. That is the EUR 1,200 shape arrived at from a different direction.
    """
    return [
        (url, re.sub(r"<[^>]+>", "", text).strip())
        for url, text in re.findall(
            r'<a\b[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', body, re.S
        )
        if _host_is_verified(url)
    ]


def unchecked_payment_links(body: str) -> list[str]:
    """Verified payment links that the anchor scan never reached.

    Two regexes decide whether a payment link gets its price checked: the one
    that finds hrefs and the one that pairs an anchor with its text. If they
    ever disagree, a link is silently exempt and the run still prints all
    checks passed, because a loop over nothing emits nothing. That is the
    failure this repo keeps rediscovering, so compare them rather than trust
    that they agree.
    """
    hrefs = {
        u for u in re.findall(r'href="(https?://[^"]+)"', body) if _host_is_verified(u)
    }
    return sorted(hrefs - {url for url, _ in verified_payment_anchors(body)})


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


# Text that promises someone a payment of a named amount: a button, a link, a
# span, or a sentence. Deliberately wider than the payment-anchor scan above,
# because the EUR 25 / EUR 1,200 mismatch was a *label* problem, and a label
# does not have to sit on a link to mislead.
PRICE_PROMISE = re.compile(
    r">\s*([^<>]{0,60}?\bpay(?:s|ing)?\b[^<>]{0,60}?€\s?[\d.,]+[^<>]{0,20})<", re.I
)


def price_promises(body: str) -> list[str]:
    return PRICE_PROMISE.findall(body)


def promised_amounts(body: str) -> list[str]:
    return [a for label in price_promises(body) for a in re.findall(r"€\s?([\d.,]+)", label)]


# Pages that deliberately carry no structured data, and why. This used to be a
# bare set holding one name, with the reason in a comment above it. A set with
# no reasons attached is how a deliberate exemption becomes an oversight nobody
# can tell apart from a mistake, so each one now carries its own, and the check
# prints it when it fires.
NO_STRUCTURED_DATA = {
    "impressum.html": "it holds a residential address, and a machine-readable "
    "graph is a different thing from a legal notice",
    "404.html": "it is an error state, not a thing; describing it in the graph "
    "would assert that a page exists at whatever URL was mistyped",
}

# Pages that borrow the site card rather than having their own. Neither is a
# page anyone links to on purpose, so a card built from its own headline would
# be a card nobody ever sees.
BORROWS_SITE_CARD = {"impressum.html", "404.html"}

# Pages kept out of sitemap.xml on purpose. The sitemap is a list of pages
# worth indexing, and an error page is the one page that must never be one:
# indexed, it competes in search with the pages it exists to rescue people to.
NOT_IN_SITEMAP = {"404.html"}

_JSON_LD = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S
)


def structured_data(body: str) -> list[dict]:
    """Every JSON-LD block on a page, parsed.

    Raises on malformed JSON rather than returning nothing, because a block
    that fails to parse is invisible to a search engine and would otherwise
    look identical to a page that simply has none.
    """
    return [json.loads(b) for b in _JSON_LD.findall(body)]


def _meta(body: str, pattern: str) -> str:
    m = re.search(pattern, body)
    return html.unescape(m.group(1)) if m else ""


def png_text(path: Path) -> dict[str, str]:
    """The text chunks in a PNG, read out of the raw bytes.

    Deliberately not Pillow, even though Pillow is installed here. The point of
    this check is that make_share_card.py and this file agree by both being
    right rather than by sharing code, and a check that trusts the same library
    the generator wrote with can only confirm that library round-trips.

    Handles tEXt and iTXt, compressed or not. zTXt is not emitted by the
    generator, so a card carrying one is a card something else wrote.
    """
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return {}
    found: dict[str, str] = {}
    i = 8
    while i + 8 <= len(raw):
        (length,) = struct.unpack(">I", raw[i : i + 4])
        kind = raw[i + 4 : i + 8]
        data = raw[i + 8 : i + 8 + length]
        i += 12 + length
        if kind == b"IEND":
            break
        if kind == b"tEXt" and b"\x00" in data:
            keyword, text = data.split(b"\x00", 1)
            found[keyword.decode("latin-1")] = text.decode("latin-1")
        elif kind == b"iTXt" and b"\x00" in data:
            keyword, rest = data.split(b"\x00", 1)
            if len(rest) < 2:
                continue
            compressed, rest = rest[0], rest[2:]
            if rest.count(b"\x00") < 2:
                continue
            _lang, rest = rest.split(b"\x00", 1)
            _translated, text = rest.split(b"\x00", 1)
            if compressed:
                try:
                    text = zlib.decompress(text)
                except zlib.error:
                    continue
            found[keyword.decode("latin-1")] = text.decode("utf-8", "replace")
    return found


def page_identity(body: str) -> dict[str, str]:
    """What the page says it is, in its own markup."""
    return {
        "name": _meta(body, r"<title>([^<]*)</title>"),
        "description": _meta(body, r'<meta name="description" content="([^"]*)"'),
        "url": _meta(body, r'<link rel="canonical" href="([^"]*)"'),
    }


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
    #
    # This fired zero times across the whole site. The pattern was
    # `>\s*(Pay[^<]{0,40})<`, anchored to a capital Pay at the start of the
    # text, and the shop's buttons read "Mastering, pay EUR 45". It matched
    # only the two section labels, which name no amount, so the inner loop
    # never ran and a check written for the wrong-checkout bug had never once
    # executed. Counted before fixing: 0 firings, 6 after.
    for name, body in src.items():
        promises = price_promises(body)
        for label in promises:
            amounts = re.findall(r"€\s?([\d.,]+)", label)
            for amount in amounts:
                in_table = f"€{amount}" in "".join(tables.get(name, []))
                check(
                    f"{name} button '{label.strip()}' quotes a price that appears in its table",
                    in_table,
                    "a button naming an amount the page does not otherwise quote is how the "
                    "wrong-checkout bug looked",
                )
        # The sibling scans below already name the case where a loop sees
        # nothing. This one did not, which is why its going dead was silent.
        # A page that carries a payment link but promises no price in words is
        # possible; a page that carries one and whose scan sees nothing at all
        # is the regex having drifted off the markup again.
        if verified_payment_anchors(body):
            check(
                f"{name} price-promise scan reaches its payment buttons",
                bool(promises),
                "the page has payment links but no button text naming a price was "
                "seen, so nothing compared a promise against the table",
            )

    print("\n=== every tool offers a way to buy the paid work ===")
    # The five free tools are the funnel, and none of them linked to the shop.
    # Their only conversion path was a bare mailto, which asks a stranger to
    # compose an email with no idea what it costs. Nobody arrives on the
    # landing page: a search result or a forum link lands them straight on a
    # tool, so that was where the paid work had to be reachable and was not.
    #
    # shop.html is the destination and impressum.html is a legal page, so
    # neither needs to link to the shop. Everything else does.
    for name, body in src.items():
        if name in ("shop.html", "impressum.html"):
            continue
        check(
            f"{name} links to the shop",
            'href="shop.html"' in body,
            "a page with no route to the rates converts nobody who lands on it "
            "from search or a link",
        )

    print("\n=== every tool page names its siblings ===")
    # The internal link graph was a star: every tool linked home, none linked
    # to another tool. Nobody arrives on the landing page, so a visitor who
    # found the loudness tool in a search result never learned the other four
    # existed, and every page's authority had to travel through index.html.
    # Read, never retyped. These labels were hardcoded here, which is the same
    # rule this file enforces on the pages being broken one level down inside
    # the checker: a name written twice can drift, and it did. Retitling the
    # pages left every page calling its siblings by names none of them used any
    # more, and the landing page naming the same five links one way in its
    # structured data and another on its own cards, with 329 checks green.
    #
    # A page's name is its title. Everything else reads that.
    TOOL_PAGES = {
        page: page_identity(src[page])["name"]
        for page in ("cover.html", "loudness.html", "release.html",
                     "delivery.html", "splits.html")
    }
    bylines = 0
    for name in TOOL_PAGES:
        body = src[name]
        missing = [
            other
            for other in TOOL_PAGES
            if other != name and f'href="{other}"' not in body
        ]
        check(
            f"{name} links to the other four tools",
            not missing,
            "reachable only through the landing page nobody lands on: "
            + ", ".join(missing),
        )
        # A link with the wrong words on it is a link nobody clicks, and the
        # names have to match the landing page's cards or the same tool reads
        # as two different tools.
        wrong = [
            label
            for other, label in TOOL_PAGES.items()
            if other != name and f'href="{other}">{label}</a>' not in body
        ]
        check(
            f"{name} calls each sibling by its landing-page name",
            not wrong,
            "named differently here than on index.html: " + ", ".join(wrong),
        )
        # And signs itself with that name too.
        #
        # The rename reached the navs, the cards and the structured data, and
        # stopped at the byline in each page's own footer, so every tool page
        # ended with a line calling itself something the site no longer calls
        # anything: "Split Sheet: a free tool by Gabriel G Alonso" at the foot
        # of Split Sheet Maker. Found by rendering the page and looking at it,
        # with 353 checks green.
        #
        # A page naming its four siblings wrongly is bad. A page naming itself
        # wrongly, in the last line a visitor reads, is worse, and it was the
        # one place nothing looked.
        signed = re.search(r"<span>([^<]*): a free tool by", body)
        if signed:
            bylines += 1
        check(
            f"{name} signs its footer with its own name",
            signed is not None and signed.group(1) == TOOL_PAGES[name],
            f"the page is called {TOOL_PAGES[name]!r}, its footer byline reads "
            f"{signed.group(1)!r}" if signed else
            "no byline found at all, so the footer markup has drifted",
        )

    # The shop signs itself the same way, in a slightly different sentence, and
    # was signing itself "Studio Shop" while calling itself Mixing and
    # Mastering Rates. It is the page money is spent on, so it is the last one
    # that should introduce itself under a name found nowhere else.
    shop_name = page_identity(src["shop.html"])["name"]
    shop_signed = re.search(r"<span>([^<]*): Gabriel G Alonso", src["shop.html"])
    if shop_signed:
        bylines += 1
    check(
        "shop.html signs its footer with its own name",
        shop_signed is not None and shop_signed.group(1) == shop_name,
        f"the page is called {shop_name!r}, its footer byline reads "
        f"{shop_signed.group(1)!r}" if shop_signed else
        "no byline found at all, so the footer markup has drifted",
    )

    # One wordmark for one site, and the page's own name beside it.
    #
    # Every tool page carried its own wordmark, and after the rename each one
    # was a name the site had retired: COVERFORGE at the top of Album Cover
    # Size Checker, LOUDNESS·CHECK at the top of LUFS and True Peak Meter. That
    # is the first thing on the page, above the headline, and it survived four
    # rounds of fixing the names further down because nothing read it.
    #
    # The preview cards had already settled the pattern: the site's wordmark,
    # then the page's title beside it. The headers now match the cards, which
    # is also the only shape that fits: "ALBUM COVER SIZE CHECKER" set as a
    # letterspaced monospace wordmark is wider than a 360px viewport.
    wordmarks = 0
    for page, body in src.items():
        if '<span class="brand">PRE<b>FLIGHT</b></span>' in body:
            wordmarks += 1
        check(
            f"{page} carries the site wordmark",
            '<span class="brand">PRE<b>FLIGHT</b></span>' in body,
            "the header wordmark is not the site's, so this page presents "
            "itself as a separate product",
        )

    check(
        "the wordmark scan fired at all",
        wordmarks == len(src),
        f"{wordmarks} of {len(src)} pages, so the brand markup has drifted",
    )

    named_in_header = 0
    for page in list(TOOL_PAGES) + ["shop.html"]:
        title = page_identity(src[page])["name"]
        if '<span class="page">' in src[page]:
            named_in_header += 1
        check(
            f"{page} names itself in its header",
            f'<span class="page">{title}</span>' in src[page],
            f"the header does not carry {title!r}, so nothing above the "
            f"headline says which of the tools this is",
        )

    check(
        "the header-name scan fired at all",
        named_in_header == len(TOOL_PAGES) + 1,
        f"{named_in_header} of {len(TOOL_PAGES) + 1} pages carry a header "
        f"name span, so the markup this reads has drifted",
    )

    check(
        "the footer-byline scan fired at all",
        bylines == len(TOOL_PAGES) + 1,
        f"found a byline on {bylines} of {len(TOOL_PAGES) + 1} pages, so the "
        f"markup this reads has drifted and the check is comparing nothing",
    )

    # No page calls anything by a name the rename retired.
    #
    # The checks above compare a name against a page's title wherever a name
    # sits in a link or a byline. Prose is not either of those: cover.html's
    # opening sentence read "Coverforge checks size, shape, format and colour",
    # which is the CLI's name and the page's own former title, and nothing on
    # the site says it any more. A visitor met a product name in the first
    # sentence that appears nowhere else on the page they are reading.
    #
    # Only the four retired names that are not substrings of a current title
    # are listed, so this cannot fire on "Release Delivery Check" containing
    # "Delivery Check". The comparison is case-sensitive on purpose: prose
    # like "the cover and loudness checkers" is ordinary English, not a name.
    RETIRED_NAMES = ("Coverforge", "Loudness Check", "Release Preflight",
                     "Studio Shop")
    for page, body in src.items():
        prose = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S | re.I)
        prose = re.sub(r"<[^>]+>", " ", prose)
        found = sorted({n for n in RETIRED_NAMES if n in prose})
        check(
            f"{page} uses no name the site has retired",
            not found,
            f"{found}; the rename left these behind, and a page that calls "
            f"itself or a sibling by one is offering a name a reader will not "
            f"find anywhere else",
        )

    print("\n=== structured data says what the page itself says ===")
    # No page carried any. Five distinct free tools and a rate card were being
    # read as undifferentiated text, so nothing told a search engine that
    # loudness.html is an application, that it costs nothing, or that the shop
    # charges EUR 45 for a master.
    #
    # Structured data restates facts the page already states, and a fact
    # written twice is a fact that can drift apart. That is not hypothetical
    # here: this site shipped a button promising EUR 25 over a EUR 1,200
    # charge. So every field below is asserted against the page's own markup
    # rather than merely being present, and the shop's prices are asserted
    # against its rate table in both directions.
    ld_firings = 0
    for name, body in src.items():
        if name in NO_STRUCTURED_DATA:
            check(
                f"{name} deliberately carries no structured data",
                not _JSON_LD.search(body),
                NO_STRUCTURED_DATA[name],
            )
            continue

        try:
            blocks = structured_data(body)
        except json.JSONDecodeError as exc:
            check(f"{name} structured data parses", False, str(exc))
            continue

        check(
            f"{name} carries exactly one structured-data block",
            len(blocks) == 1,
            f"found {len(blocks)}; a block that does not parse is invisible to "
            f"a search engine and looks identical to a page with none",
        )
        if len(blocks) != 1:
            continue

        ld = blocks[0]
        says = page_identity(body)
        for key in ("name", "description", "url"):
            ld_firings += 1
            check(
                f"{name} structured-data {key} matches the page",
                ld.get(key) == says[key],
                f"markup says {says[key]!r}, structured data says {ld.get(key)!r}",
            )

    # Every family in this file has to be able to say it ran. The price-promise
    # check sat at zero firings inside a suite reporting all checks passed,
    # because a loop over nothing prints nothing.
    check(
        "the structured-data field scan fired at all",
        ld_firings > 0,
        "zero fields compared, so the block regex has drifted off the markup",
    )

    print("\n=== a free tool says free, and the shop says its own prices ===")
    for name in TOOL_PAGES:
        ld = structured_data(src[name])[0]
        offer = ld.get("offers") or {}
        # Both places, not just the friendly one. A page whose footer reads
        # "a free tool by" while its structured data quotes a price tells a
        # search engine the opposite of what it tells a reader.
        check(
            f"{name} is free in its markup and in its structured data",
            "a free tool by" in src[name]
            and offer.get("price") == "0"
            and ld.get("isAccessibleForFree") is True,
            f"footer says free, structured data offers {offer.get('price')!r} "
            f"and isAccessibleForFree {ld.get('isAccessibleForFree')!r}",
        )

    shop = src["shop.html"]
    catalog = structured_data(shop)[0].get("hasOfferCatalog", {})
    ld_prices = sorted(o.get("price", "") for o in catalog.get("itemListElement", []))
    table_prices = sorted(re.findall(r'<td class="n">€([\d.,]+)</td>', shop))
    check(
        "the shop's structured data quotes its rate table exactly",
        ld_prices == table_prices and bool(table_prices),
        f"structured data {ld_prices}, rate table {table_prices}",
    )
    check(
        "every shop offer states a currency",
        bool(catalog.get("itemListElement"))
        and all(
            o.get("priceCurrency") == "EUR" for o in catalog.get("itemListElement", [])
        ),
        "an amount with no currency is an amount decided by an account setting "
        "nobody reading the page can see",
    )
    # He is a Kleinunternehmer under section 19 UStG and charges no VAT, so
    # neither "included" nor "excluded" is true. A tax treatment contradicting
    # the Kleinunternehmer line sat on this page once already.
    check(
        "the shop's structured data claims no VAT treatment",
        "valueAddedTaxIncluded" not in json.dumps(catalog),
        "section 19 means no VAT is charged at all, so any VAT flag is a claim "
        "nobody here can support",
    )

    items = (
        structured_data(src["index.html"])[0]
        .get("mainEntity", {})
        .get("itemListElement", [])
    )
    listed = [item.get("url") for item in items]
    expected = [page_identity(src[t])["url"] for t in TOOL_PAGES]
    check(
        "the landing page's structured list holds the five tools, in order",
        listed == expected,
        f"listed {listed}, expected {expected}",
    )
    # The URLs being in the right order is not the same as the list saying so.
    # A reader of the graph goes by "position", and a mutation that reordered
    # only the numbers passed the check above without moving a single URL.
    positions = [item.get("position") for item in items]
    check(
        "the landing page's list numbers its items 1 to 5",
        positions == list(range(1, len(items) + 1)) and bool(items),
        f"positions {positions}; the order a consumer reads is this field, "
        f"not the order the entries happen to sit in",
    )


    print("\n=== one name per page, on the page and everywhere pointing at it ===")
    # The landing page names each tool twice, in a visible card and in its
    # structured data, and the sibling navs name them a third time. Retitling
    # moved the titles and left all three behind. Nothing noticed, because each
    # check compared the copies with each other rather than with the page.
    index = src["index.html"]
    listed = {
        item["url"].rsplit("/", 1)[-1]: item.get("name")
        for item in structured_data(index)[0]
        .get("mainEntity", {})
        .get("itemListElement", [])
    }
    cards = dict(
        re.findall(
            r'href="([a-z]+\.html)">\s*<span class="ic"[^>]*>[^<]*</span>\s*<h3>([^<]+)</h3>',
            index,
        )
    )
    check(
        "the landing page has a visible card for every tool",
        set(cards) == set(TOOL_PAGES),
        f"cards for {sorted(cards)}, tools are {sorted(TOOL_PAGES)}",
    )
    for page, name in TOOL_PAGES.items():
        check(
            f"the landing page's card for {page} uses the page's own name",
            cards.get(page) == name,
            f"card says {cards.get(page)!r}, the page calls itself {name!r}",
        )
        check(
            f"the landing page's structured list names {page} the same way",
            listed.get(page) == name,
            f"structured data says {listed.get(page)!r}, card says {cards.get(page)!r}",
        )

    print("\n=== every page carries an icon, and the icons exist ===")
    # There was no favicon at all: nine pages, no icon file, so every tab
    # showed the browser's blank document glyph and every page load fired a
    # 404 for /favicon.ico. Someone who leaves the loudness tool open in a
    # crowded tab strip could not find it again, which is the whole job of the
    # thing.
    #
    # Three files, because one format does not cover it: SVG for anything
    # current, .ico for Windows shell icons and old Safari, and a 180px PNG
    # for an iOS home screen.
    ICONS = {
        'rel="icon" href="favicon.svg"': "favicon.svg",
        'rel="icon" href="favicon.ico"': "favicon.ico",
        'rel="apple-touch-icon" href="apple-touch-icon.png"': "apple-touch-icon.png",
    }
    icon_firings = 0
    for name, body in src.items():
        for marker, filename in ICONS.items():
            icon_firings += 1
            check(
                f"{name} links {filename}",
                marker in body,
                "a page with no icon is a tab nobody can find again",
            )
    check(
        "the icon scan fired at all",
        icon_firings > 0,
        "zero pages examined, so the markers have drifted off the markup",
    )
    for filename in ICONS.values():
        check(
            f"{filename} is in docs/",
            (DOCS / filename).is_file(),
            "every page asks for it, so its absence is a 404 on every page load",
        )

    print("\n=== the Preflight wordmark is one wordmark ===")
    # Each tool page has its own wordmark (LOUDNESS-CHECK and so on), but the
    # pages that carry the site's own name have to spell it the same way. The
    # 404 page was written with a third variant, PRE<b>.</b>FLIGHT, next to the
    # PRE<b>FLIGHT</b> that index.html and impressum.html already used. Nothing
    # caught it, because a wordmark is markup rather than a claim.
    marks = {
        name: m.group(0)
        for name, body in src.items()
        if (m := re.search(r'<span class="brand">PRE.{0,12}FLIGHT.{0,12}</span>', body))
    }
    check(
        "at least one page carries the Preflight wordmark",
        bool(marks),
        "none found, so the pattern has drifted off the markup",
    )
    check(
        "every page spelling out Preflight spells it the same way",
        len(set(marks.values())) <= 1,
        f"{ {n: m for n, m in marks.items()} }",
    )

    print("\n=== every page previews as itself ===")
    # All eight pages pointed at one share.png. A link to the split sheet
    # posted anywhere previewed as "Free tools for releasing music", which
    # describes the site rather than the page, so the preview did none of the
    # work a preview exists to do on the one screen where someone decides
    # whether to click.
    #
    # This checks the published state rather than the generator's intent: that
    # the file a page names is really in docs/, that its alt text describes
    # that page's card, and that no card is sitting there unreferenced.
    # make_share_card.py is not imported, so the two have to agree by both
    # being right rather than by sharing a variable.
    referenced: dict[str, str] = {}
    for name, body in src.items():
        card = re.search(r'<meta property="og:image" content="([^"]*)"', body)
        check(f"{name} names a preview image", bool(card), "no og:image")
        if not card:
            continue
        filename = card.group(1).rsplit("/", 1)[-1]
        referenced[name] = filename
        check(
            f"{name}'s preview image exists in docs/",
            (DOCS / filename).is_file(),
            f"points at {filename}, which is not there, so the preview is blank",
        )

    own_card = {n: c for n, c in referenced.items() if n not in BORROWS_SITE_CARD}
    for name in BORROWS_SITE_CARD:
        check(
            f"{name} borrows the site card rather than having its own",
            referenced.get(name) == "share.png",
            f"points at {referenced.get(name)!r}; if it has earned its own card, "
            f"take it out of BORROWS_SITE_CARD rather than leaving both true",
        )
    check(
        "no two pages share a preview image",
        len(set(own_card.values())) == len(own_card),
        f"{sorted(Counter(own_card.values()).items())}",
    )
    check(
        "the preview-image scan fired at all",
        bool(referenced),
        "zero pages examined, so the og:image regex has drifted off the markup",
    )

    orphans = sorted(
        p.name
        for p in DOCS.glob("share*.png")
        if p.name not in set(referenced.values())
    )
    check(
        "no preview image is sitting unreferenced in docs/",
        not orphans,
        f"{orphans}; a card nothing points at is a card nobody will ever see, "
        f"and it publishes at a URL anyway",
    )

    # A card is a picture of what a page says, and nothing tied the picture to
    # the page. Editing loudness.html's h1 left its card showing the old
    # headline and all 250 checks passed, because they asserted the file
    # existed and was unique, never that it said what the page says. That is
    # the drift this file exists to catch, one level down, in the checks this
    # file added an hour earlier.
    #
    # Each card now carries the exact strings it was drawn from, and those are
    # read back out of the raw PNG bytes rather than through Pillow.
    for name, filename in own_card.items():
        text = png_text(DOCS / filename)
        drawn_from = text.get("preflight:page")
        check(
            f"{filename} records the page it was drawn from",
            drawn_from is not None,
            "no source recorded; rerun tools/make_share_card.py, because a card "
            "with nothing tying it to a page can go stale invisibly",
        )
        if drawn_from is None:
            continue
        check(
            f"{filename} was drawn from {name}",
            drawn_from == name,
            f"records {drawn_from!r}",
        )
        says = page_identity(src[name])
        # The card draws three strings and recorded two. Changing a title left
        # the eyebrow showing the old one and all 318 checks passed, which is
        # the defect these very checks were added to prevent, failing on its
        # own implementation. Where a thing is stated in more than one place,
        # assert every place, including the places you added yourself.
        check(
            f"{filename} shows {name}'s current title",
            text.get("preflight:title") == says["name"],
            f"card was drawn from {text.get('preflight:title')!r}, page now "
            f"says {says['name']!r}; rerun tools/make_share_card.py",
        )
        head = _meta(src[name], r"<h1[^>]*>(.*?)</h1>")
        head = html.unescape(re.sub(r"<[^>]+>", "", head)).strip()
        check(
            f"{filename} shows {name}'s current headline",
            text.get("preflight:headline") == head,
            f"card was drawn from {text.get('preflight:headline')!r}, page now "
            f"says {head!r}; rerun tools/make_share_card.py",
        )
        check(
            f"{filename} shows {name}'s current description",
            text.get("preflight:description") == says["description"],
            f"card was drawn from {text.get('preflight:description')!r}, page "
            f"now says {says['description']!r}; rerun tools/make_share_card.py",
        )

    # The alt describes the card, not the page, and those differ for the pages
    # that borrow another's card. Checking it against its own title failed the
    # Impressum for correctly describing the site card it points at.
    #
    # The first version compared the alt against the owner page's title, which
    # is far too weak a test: "Preflight" is a substring of almost any sentence
    # about this site. It passed impressum.html while that page's alt still
    # described the card as it looked before the cards were redrawn, so a
    # screen reader there was given an image that no longer existed.
    #
    # So compare against what the card itself records it was drawn with. The
    # headline is compared with any trailing full stop removed, because that is
    # what the generator draws.
    eyebrows = 0
    for name, filename in referenced.items():
        alt = html.unescape(
            _meta(src[name], r'<meta property="og:image:alt" content="([^"]*)"')
        )
        drawn = png_text(DOCS / filename)
        headline = drawn.get("preflight:headline")
        check(
            f"{name}'s preview alt text quotes the headline on the card",
            headline is not None and headline.rstrip(".") in alt,
            f"the card reads {headline!r}, the alt reads {alt!r}; the alt is "
            f"what a screen reader gets instead of the image, so it has to "
            f"describe the image that is actually there",
        )
        # And the eyebrow, which is the other thing the card prints in words.
        #
        # Comparing only the headline was not enough. Renaming the pages moved
        # every eyebrow and left six alt texts naming a card that no longer
        # exists: "Preflight Coverforge" over a card reading ALBUM COVER SIZE
        # CHECKER, with all 340 checks green, because the headlines had not
        # moved and the headline was the only thing anything read. That is the
        # impressum alt-text defect again, one field along, and it is the same
        # lesson as the card that recorded two of the three strings it drew:
        # enumerate what the thing actually draws.
        #
        # Whether an eyebrow was drawn is read off the card, not re-derived
        # from the page's name, so this cannot disagree with the generator
        # about which cards have one.
        eyebrow = drawn.get("preflight:eyebrow")
        if eyebrow is not None:
            eyebrows += 1
            check(
                f"{name}'s preview alt text names the card's eyebrow",
                eyebrow.lower() in alt.lower(),
                f"the card prints {eyebrow!r} beside the wordmark, the alt "
                f"reads {alt!r}; a reader who cannot see the card is being "
                f"given the name of a different one",
            )

        check(
            f"{name}'s preview alt text names who made it",
            "Gabriel G Alonso" in alt,
            f"alt {alt!r}",
        )

    # Skipping on a missing key means the generator dropping the key takes the
    # whole family with it and nothing says so, which is how the price-promise
    # scan sat dead through 129 green checks. Only the landing card has no
    # eyebrow, so zero of them means the recording stopped, not that the cards
    # stopped having one.
    check(
        "the eyebrow scan fired at all",
        eyebrows > 0,
        "no card records the eyebrow it drew, so nothing compared any alt text "
        "against it; rerun tools/make_share_card.py",
    )


    print("\n=== the README advertises the site that actually exists ===")
    # The repository is public and its README is a discovery surface in its own
    # right, so the same rule applies to it as to a tool page: someone reading
    # it who wants their record finished needs a route to the rates.
    #
    # It is also a list of URLs maintained by hand next to a directory of
    # files, which is the shape that goes stale silently. A tool renamed in
    # docs/ leaves a dead link here and nothing notices, because nobody clicks
    # their own README.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    linked = set(re.findall(rf"{re.escape(SITE)}([a-z0-9]+\.html)", readme))
    check(
        "the README links to at least one page",
        bool(linked),
        "no site links found at all, so the URL pattern has drifted",
    )

    dead = sorted(page for page in linked if page not in src)
    check(
        "every page the README links to exists",
        not dead,
        f"{dead}; a dead link in the README is a dead link on the repository's "
        f"front page, which is where a stranger meets this project",
    )

    check(
        "the README links to the shop",
        "shop.html" in linked,
        "the repository front page is a route in, and it had no route to the "
        "rates, which is the same gap the tool pages had",
    )

    for page in TOOL_PAGES:
        check(
            f"the README links to {page}",
            page in linked,
            "a tool nobody can find from the front page of its own repository",
        )

    # And calls it what it is called.
    #
    # "A name written twice drifts the moment you rename anything" was written
    # about the tool pages naming each other, and the README was left out of
    # that fix while being exactly the same shape: a hand-typed list of names
    # beside a directory of pages. Renaming the pages left the front page of a
    # public repository offering a "cover spec checker", a "delivery check" and
    # a "split sheet", none of which is the name of anything on the site, and
    # every README check passed because they only ever asked whether the URLs
    # resolved.
    #
    # The link text is compared with the page's own <title>, the same source
    # the landing cards and the sibling navs read.
    #
    # The shop is deliberately not held to this. Its link sits inside a
    # sentence rather than in the list of names, and a sentence reading "the
    # Mixing and Mastering Rates" to keep a check happy would be worse writing
    # for no gain. That it is linked at all is checked above.
    named = 0
    for page, title in TOOL_PAGES.items():
        texts = re.findall(
            rf"\[([^\]]+)\]\({re.escape(SITE + page)}\)", readme
        )
        if texts:
            named += 1
        check(
            f"the README calls {page} by its own name",
            title in texts,
            f"the README calls it {texts!r}; the page calls itself {title!r}, "
            f"and a stranger meeting this project on its front page should be "
            f"given the name they will see when they arrive",
        )

    check(
        "the README's link-text scan fired at all",
        named == len(TOOL_PAGES),
        f"matched link text for {named} of {len(TOOL_PAGES)} tools, so the "
        f"markdown-link pattern has drifted off the README",
    )


    print("\n=== every card link quotes a price the page actually charges ===")
    # The failure this exists for: a button reading "Pay EUR 25" that charged
    # EUR 1,200 for a different service. The amount a customer is promised has
    # to be one the rate table on the same page states.
    for name, body in src.items():
        # A loop over nothing emits nothing, so a page whose links this scan
        # cannot see would report no failures rather than reporting that it saw
        # no links. Name that case before iterating.
        missed = unchecked_payment_links(body)
        check(
            f"{name} has no payment link the price check cannot reach",
            not missed,
            f"{missed} matched the href scan but not the anchor scan, so nothing "
            f"checked what they promise",
        )
        for _url, text in verified_payment_anchors(body):
            quoted = re.findall(r"€\s?([\d.,]+)", text)
            check(
                f"{name} card link '{text}' quotes an amount from its table",
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

    print("\n=== every payment processor the site links to is disclosed ===")
    # A payment button sends the visitor, and their data, to a third party
    # acting as its own controller. Art. 13 DSGVO says the privacy notice has
    # to name it. So the set of processors the shop links to and the set the
    # Impressum discloses are the same fact in two files, and the shop is the
    # one that changes.
    #
    # It had already drifted. The notice was written when Stripe was the only
    # button, three PayPal.Me buttons went on the shop on 22 August 2026, and
    # PayPal appeared nowhere in it: a processor receiving personal data,
    # undisclosed, on the page money is spent on.
    #
    # The provider's name is derived from the host rather than retyped, so a
    # fourth processor cannot be added to a hardcoded map that nobody updates.
    # buy.stripe.com and paypal.me both yield their second-to-last label.
    impressum_text = re.sub(r"<[^>]+>", " ", src["impressum.html"]).lower()
    linked_processors = {
        (urlsplit(u).hostname or "").lower().split(".")[-2]
        for body in src.values()
        for u, _text in verified_payment_anchors(body)
        if len((urlsplit(u).hostname or "").split(".")) >= 2
    }
    check(
        "the payment-processor scan found processors to check",
        bool(linked_processors),
        "no payment links found on any page at all, so the disclosure check "
        "below compared nothing; either the shop lost its buttons or the "
        "anchor scan has drifted off the markup",
    )
    for provider in sorted(linked_processors):
        check(
            f"the Impressum discloses {provider} as a payment processor",
            provider in impressum_text,
            f"the shop links to {provider}, and the Datenschutzerklärung never "
            f"names it. A third party that receives the visitor's data has to "
            f"be named under Art. 13 DSGVO",
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
    # That comparison passes on two empty sets, so it says nothing about the
    # statement being there. Measured: stripping Kleinunternehmer, UStG and VAT
    # from the shop left every check green. He is a Kleinunternehmer under
    # section 19, the page's "prices on this page are the total" line rests on
    # exactly that, and a page quoting prices with the basis missing is the
    # wrong-tax-treatment failure arriving by omission instead.
    shop_body = src.get("shop.html", "")
    check(
        "the shop states the section 19 position its prices rest on",
        "Kleinunternehmer" in shop_body and "19" in shop_body,
        "the page quotes prices as totals without saying why no VAT is added",
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
    # `len(addrs) <= 1` was the whole check, and it passes on an empty set.
    # Measured: stripping every mailto from all nine pages left 325 checks
    # green, with the site carrying no way to reach him at all. Booking starts
    # by email, so that is the business disappearing quietly.
    addrs = Counter(a for b in src.values() for a in re.findall(r'mailto:([^"?]+)', b))
    check(
        "the site carries a contact address at all",
        bool(addrs),
        "no mailto found anywhere; either they are gone or the pattern drifted",
    )
    check("a single contact address is used everywhere", len(addrs) <= 1, f"{dict(addrs)}")
    check(
        "the contact address is the business one",
        set(addrs) <= {CONTACT},
        f"found {sorted(addrs)}, expected {CONTACT}",
    )
    # notgabriels@gmail.com is his personal PayPal and personal mail. Client
    # money and client mail go to the business address, which is also the one
    # in the Impressum. This asserts the personal one never appears anywhere,
    # in a mailto or otherwise.
    personal = sorted(n for n, b in src.items() if PERSONAL_ADDRESS in b)
    check(
        "the personal address appears on no page",
        not personal,
        f"{personal} carry {PERSONAL_ADDRESS}, which is not the business address",
    )

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
    indexable = {n for n in src if n not in NOT_IN_SITEMAP}
    check("the sitemap lists every indexable page and no others",
          sorted(listed) == sorted(SITE + n for n in indexable),
          f"{sorted(set(listed) ^ {SITE + n for n in indexable})}")
    # Excluding a page from the sitemap is not the same as asking not to be
    # indexed, and a crawler that reaches the error page by following a broken
    # link never consults the sitemap at all. Both have to be true.
    for name in NOT_IN_SITEMAP:
        check(f"{name} is kept out of the sitemap on purpose",
              SITE + name not in listed,
              "an indexed error page competes in search with the pages it "
              "exists to rescue people to")
        check(f"{name} also asks crawlers not to index it",
              '<meta name="robots" content="noindex">' in src[name],
              "out of the sitemap is not the same as out of the index")
    check("robots.txt points at the sitemap",
          SITE + "sitemap.xml" in (DOCS / "robots.txt").read_text(encoding="utf-8"))

    # The domain is written twice: once as SITE, which every canonical, sitemap
    # entry and preview URL above is compared against, and once in docs/CNAME,
    # which is the only thing that makes GitHub Pages answer on that host at
    # all. Nothing tied them together.
    #
    # That is "a fact restated somewhere else is a fact that can drift" with
    # the worst blast radius in the repo. Every other instance of it makes one
    # page say the wrong thing. This one takes the site down: change SITE alone
    # and every URL points at a host Pages does not serve, change CNAME alone
    # and Pages serves a host every URL disclaims. Both are a dead site, and
    # both would have passed all 386 checks.
    #
    # The format matters as much as the value. Pages wants a bare hostname, so
    # a scheme, a trailing slash or a path in this file silently stops the
    # custom domain working, and the only symptom is the site being gone.
    cname_path = DOCS / "CNAME"
    check(
        "docs/CNAME exists",
        cname_path.is_file(),
        "without it GitHub Pages serves the github.io address and the custom "
        "domain 404s, however correct the DNS is",
    )
    if cname_path.is_file():
        raw = cname_path.read_text(encoding="utf-8")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        host = SITE.split("//", 1)[-1].rstrip("/")
        check(
            "docs/CNAME names exactly the host the pages claim",
            lines == [host],
            f"CNAME says {lines!r}, every URL on the site says {host!r}; these "
            f"are the same fact in two files and they have drifted apart",
        )
        check(
            "docs/CNAME is a bare hostname",
            lines and "/" not in lines[0] and ":" not in lines[0],
            f"{lines[:1]!r}; Pages wants a hostname with no scheme, no path "
            f"and no trailing slash, and rejects anything else by quietly "
            f"dropping the custom domain",
        )

    # docs/ is the web root: every file in it is served to the public. A plan
    # and a design spec were once committed to docs/superpowers/ and published,
    # agent instructions and all, and nothing failed because the sitemap check
    # only looks at .html. Name what belongs here and reject the rest, so the
    # next stray directory is a red CI run rather than a live page.
    PUBLISHABLE = {".html", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".xml", ".txt", ".webmanifest"}
    # .nojekyll and CNAME are GitHub Pages control files, not content: the
    # first stops Jekyll processing the directory, the second is what makes
    # Pages serve the custom domain at all. Named here rather than allowing
    # every extensionless file, which would let a README back in.
    ALLOWED_BY_NAME = {".nojekyll", "CNAME"}
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
