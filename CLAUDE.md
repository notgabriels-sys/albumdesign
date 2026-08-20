# Working notes for this repo

## How Gabriel wants work done

**Decide and act. Do not stop to ask for permission on ordinary work.**
When there is a judgement call with an obvious answer, make it, do the work,
and report the decision and its reasoning afterwards. Use parallel subagents
("with dispatch") for verification and review passes rather than serialising.

That means, by default and without asking first:

- branch, commit, push, open a draft PR, wait for CI, merge when green
- close superseded PRs with a comment saying what happened to their content
- fix problems found along the way instead of listing them for later

Only stop and ask when the answer genuinely changes the work and cannot be
inferred: money, publishing something under his name, deleting his data, or a
fact only he knows (real release dates, ISRCs, client names, rates).

**Report honestly.** Say what was verified and how, and say plainly what was
not. Never present an automated check as equivalent to a human one.

## Hard rules on claims

These come from his operating profile and apply to anything leaving this repo:

- Never invent audio parameters (sample rate, bit depth, loudness target,
  true-peak ceiling, format) or prices. Ask or leave a placeholder.
- Never inflate credits. A repost or a submission is not a release. No
  invented clients, credits, employment, or biography.
- Never claim a listen, a send, or a check that did not happen.
- Never put invented dates, ISRCs, or budget numbers into royalty claims
  (GVL) or funding applications.
- No em dashes in output written for him.
- Legal name is **Gabriel García Alonso**, with the accent, as it appears on his
  Spanish DNI and European passport. That exact form goes on invoices and formal
  documents, where §14 UStG wants the full legal name. German authorities drop
  the accent (the BZSt letter reads "Gabriel Garcia Alonso"), so a document
  spelling it that way is theirs, not an error to correct.
  The site bylines say "Gabriel G Alonso", which is a professional shortening
  and his to decide, so do not change them without asking.
  Public-facing artist identities are Hologram People, Lack of Fate,
  Fate Through. Contact address is hologrampeoplemusic@gmail.com.

## Repo layout

- `coverforge/`: the Python CLI. `targets.toml` holds the platform specs and
  is meant to be edited; the numbers are a best-effort snapshot.
- `docs/`: **this is the GitHub Pages web root.** Anything committed here is
  published. Do not put planning notes, specs, or scratch files in it.
- `tools/`: the test suites. Fixtures are generated, not committed.

The site is five tools plus the shop and the Impressum: `cover.html`,
`loudness.html`, `delivery.html` (a whole release at once, not one track),
`release.html`, `splits.html`, `shop.html`, `impressum.html`, with `index.html`
as the landing page. `docs/share.png` is the link-preview image, drawn by
`tools/make_share_card.py`. It is committed rather than built in CI because it
uses a system font and would come out slightly different on every runner.

Adding a page means more than writing it: `consistency_check.py` requires the
Open Graph set on every page and requires `sitemap.xml` to list exactly the
pages that exist, so a new page fails CI until both are done. That is the
point. `delivery.html` shipped unlisted for three commits before the check
existed.

## Testing

CI (`.github/workflows/tests.yml`) runs all of it on every push and PR:

```bash
pip install -e '.[dev]' && python -m pytest tests -q

npm install playwright
python tools/make_fixtures.py     # generates tools/fixtures/
node tools/browser_test.js        # functional: parsing, loudness, checklist
node tools/a11y_test.js           # contrast, headings, landmarks, keyboard
python tools/verify_lufs.py       # BS.1770 vs EBU Tech 3341 signals
python tools/verify_truepeak.py   # 4x-oversampled true peak
```

The two `verify_*` scripts assert and exit non-zero. They used to only print,
which made them useless as gates. Keep them asserting.

## Things that will bite you

- **Builds must stay byte-reproducible.** The sRGB ICC profile embedded in
  every output carries a creation timestamp in header bytes 24..35. It is
  zeroed in `imageops._srgb_profile_bytes()`. Undo that and every rebuild
  produces different files, different hashes, and a different manifest
  `capture_id`. Two tests guard it.
- **The artifact copies in the scratchpad must not have `<!doctype html>` or
  `<html lang>`.** The Artifact host supplies that wrapper. The `docs/` copies
  do need it. `sync_artifacts.py` also rewrites relative page links to the live
  site, because an artifact is one page with no siblings and `href="index.html"`
  resolved to nothing in every published copy.
- **Check `main` before building anything.** A whole CLI was once rebuilt from
  scratch when a better version was already merged.
- **A file name is attacker-shaped text, and it lands in an attribute.**
  `delivery.html` put the dropped file's name in a single-quoted `title=` while
  its `esc()` escaped only `& < > "`. A file called
  `a' onmouseover='alert(1)' x='.wav` closed the attribute and added a live
  handler, proved in Chromium before it was fixed. `splits.html` had always
  escaped the apostrophe; the delivery copy had been trimmed. Any new page that
  echoes a file name escapes `'` too, and a browser test asserts the rendered
  cell carries no handler.
- **Do not let a check pass on a measurement that did not happen.** The
  delivery page filtered its over-the-ceiling list on `isFinite` while scoring
  the check `pass`, so a release whose true peaks all failed to measure was told
  every track sat under its ceiling, with the column blank above the sentence.
  Same shape in three other checks. A result nobody measured is a warning that
  says so, never a pass.
- **An eleven-bit MPEG sync word is not evidence of an MP3.** It turns up in
  arbitrary binary about every 2 KB, so a blind 200 KB scan claimed `.m4a` and
  `.ogg` files as MP3 with a sample rate read off a coincidence, in both
  `delivery.html` and `loudness.html`. Validating the header fields was not
  enough, and requiring a confirming frame chain was not enough either: a test
  buffer that plants a sync every seven bytes defeated both. What works is
  gating the scan on the file declaring itself, an ID3 tag or a real frame at
  offset 0, plus the field validation. Do not loosen that back to a bare scan.
- **The Chromium install step in CI hangs sometimes.**
  `npx playwright install --with-deps chromium` takes about 25 seconds
  normally and has twice sat for 5 to 20 minutes on a PR while `main` was
  fine. It is upstream, not the diff, and it runs before any repo code.
  Cancel the run and re-run it rather than debugging the change.

## The site is live

https://notgabriels-sys.github.io/albumdesign/ serves `docs/` from `main`.
Gabriel switched Pages on himself, because he had to: an Actions token is
refused with "Resource not accessible by integration" when it tries to *create*
a Pages site, and the Pages REST path is blocked by this environment's proxy.
Deploying to the existing site is fine, so pushes to `main` publish normally.

`*.github.io` is also blocked by the egress proxy, so the served page cannot be
fetched from here. To check a deploy, read the `pages build and deployment` run
and the `github-pages` deployment sha instead, and render `docs/` locally with
Playwright to check appearance.

The seven pages are also published as Artifacts on claude.ai, private until
Gabriel shares them. `Artifact` with `action: "list"` finds their URLs; publish
with the same URL to update one in place, and read it with WebFetch first,
because the tool refuses to overwrite a version this session has not seen.
They are copies, not the source: fix `docs/`, then rederive and republish.
Meta tags in the derived copies do nothing there, since the host supplies its
own document head, so a docs change that only touches `<head>` is not a reason
to republish all seven.

## Checking platform specs from here

WebFetch is blocked for every spec source worth reading: `support.spotify.com`,
`artists.spotify.com`, `help.bandcamp.com`, `tech.ebu.ch`. **WebSearch is not**,
and it does reach them. Use WebSearch, with `allowed_domains` set to the
platform's own help domain when the claim needs to come from the platform rather
than a blog.

What that confirmed in August 2026, so it does not need redoing:

- Spotify: -14 LUFS, true peak below -1 dBTP, and below -2 dBTP above -14 LUFS.
  Spotify does apply positive gain to quiet masters, so it is not attenuate-only.
- Apple (-16) and YouTube (-14) turn down only. Both corroborated by third
  parties, neither documented by the platform, which is what the page says.
- TuneCore: min 1600, max 3000. CD Baby: min 1400, max 3000. So the "CD Baby and
  TuneCore reject over 3000" line holds.
- 10 MB is documented by Ditto and DistroKid. CD Baby's own limit is 25 MB, and
  TuneCore does not publish one, so do not attribute 10 MB to TuneCore.
- Bandcamp: minimum 1400x1400, "bigger is better" with no stated ideal, jpg/gif
  /png, 10 MB max. That matches the Bandcamp row exactly, and its accepting GIF
  is part of why the format check warns rather than fails on GIF and TIFF.

Still unverified, and not for want of trying: Beatport's own numbers and
Spotify's cover-art dimensions. `labelsupport.beatport.com` is blocked by the
proxy like the rest, and the one relevant article's contents do not come back in
search. Both keep their hedged wording until someone can read the page.

Search results are a summary of a page, not the page. Treat them as good enough
to correct a wrong attribution, not as grounds for a new hard claim.

## Open, needs Gabriel

- **The shop's card buttons must never point at a link nobody read. Do not add
  one from memory.** The link that used to be there was read through the Stripe MCP
  and turned out to be a €1,200 "Speech Audio QC — Full Audit (50% deposit)",
  `tax_behavior: exclusive`, with another €1,200 invoiced on delivery. It sat on
  the mixing and mastering page labelled "Pay €25 deposit". Wrong service, wrong
  amount, and a tax treatment that contradicted the Kleinunternehmer line right
  above it.

  The URL on the page was the test link's slug with `test_` deleted, so it
  either charged that audit or resolved to nothing. Booking starts by email and
  the invoice follows, which is what the copy always said anyway.

  Before any card button goes back: get a **live-mode** payment link for mixing
  and mastering and **read it** with the Stripe MCP (`GetPaymentLinks`, then
  `GetPaymentLinksPaymentLinkLineItems` for `unit_amount` and `tax_behavior`).
  `buy.stripe.com` is blocked by the egress gateway, so a browser cannot check
  it and neither can curl. Reading the API object is the only verification that
  works. Do not accept a remembered figure as confirmation, including his: that
  is how this one survived two rounds of review.

  **Resolved on the Stripe side, 17 August 2026.** He activated live mode and
  reconnected the connector, and the live account was then readable. What it
  held: two live links, both €160 for a product called "Engineering", both
  `tax_behavior: exclusive` with automatic tax on, and their URLs were the test
  slugs with `test_` removed. One of them was character-for-character the URL
  that had been on the shop. It had gone from resolving to nothing to being
  live and chargeable. Both are now deactivated
  (`plink_1U4bZUBKk5iV3TpTBUBzG6CX`, `plink_1U4bZHBKk5iV3TpTrwxQz0m8`).

  Three correct links replaced them, created and then read back through the API:

  | service | amount | tax_behavior | automatic_tax |
  |---|---|---|---|
  | Mastering, one track | €45.00 | inclusive | off |
  | Mixing, one track | €160.00 | inclusive | off |
  | Mix + master, one track | €190.00 | inclusive | off |

  All three report `amount_tax: 0`, matching the rate card and the "prices on
  this page are the total" line. Account tax settings are now head office
  Germany, prices tax-inclusive, tax collection not started, which is right for
  a §19 Kleinunternehmer.

  **The three buttons went on the shop the same day, at his instruction.** They
  had been held back on the reasoning that taking card money obliges him to
  issue an invoice he cannot yet make compliant. That reasoning was wrong: he
  already invoices for bank transfers, so §14 applies today either way. A button
  changes the sequence, not the law, and which sequence he wants is his call.

  `buy.stripe.com` is on VERIFIED_PAYMENT_HOSTS in tools/consistency_check.py,
  and a check asserts every card link quotes an amount its own rate table
  charges. Both were proved to fail before being trusted. Adding a host to that
  set is a claim that someone read the provider's objects, so do not add one
  because a link looks right.

  Still open: the Steuernummer. What he holds is the 11-digit
  Identifikationsnummer from the BZSt, which §14 UStG does not accept on an
  invoice. It is needed for the invoices he already sends, not for the buttons.
  When it arrives it goes in the Stripe invoice template, replacing the
  `VOR LIVEBETRIEB EINTRAGEN` placeholder.

  PayPal: he has two accounts, and told us which is which on 18 August 2026.
  The **business** account is hologrampeoplemusic@gmail.com, which is also the
  site's contact address and the one in the Impressum, so it is the only one
  client money should reach. notgabriels@gmail.com is his personal account and
  does not belong on the shop. Both are his statement, not something read here.

  Nothing about either has been verified. The PayPal MCP server has returned
  `Unauthorized` on every attempt, and in later sessions it has not been
  connected at all, so no PayPal button goes on the page. Knowing the address
  an account sits under says nothing about what a button would charge, which is
  the whole lesson of the Stripe links below.

  Gabriel saying card payment is fine by him was a decision about what he wants
  to accept, never evidence the mechanism existed. Reading the objects is what
  found both the €1,200 link and the €160-plus-VAT pair.
- GVL catalogue table and the Förderantrag both have blanks only he can fill:
  real release dates, ISRCs, which tracks were actually released, real bio
  facts and real costs. Do not guess any of them.
