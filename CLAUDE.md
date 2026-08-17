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
- Legal name (Gabriel G Alonso) goes on invoices and formal documents.
  Public-facing artist identities are Hologram People, Lack of Fate,
  Fate Through. Contact address is hologrampeoplemusic@gmail.com.

## Repo layout

- `coverforge/`: the Python CLI. `targets.toml` holds the platform specs and
  is meant to be edited; the numbers are a best-effort snapshot.
- `docs/`: **this is the GitHub Pages web root.** Anything committed here is
  published. Do not put planning notes, specs, or scratch files in it.
- `tools/`: the test suites. Fixtures are generated, not committed.

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
  do need it.
- **Check `main` before building anything.** A whole CLI was once rebuilt from
  scratch when a better version was already merged.

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

- **There is no payment button on the shop, on purpose. Do not add one back
  from memory.** The link that used to be there was read through the Stripe MCP
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

  Read again in August 2026, and the answer got firmer. The only Stripe account
  reachable from here is **test mode**; there is no live account at all. All
  three links are test links, none is for mixing or mastering, and every one
  carries `blocked_on: steuernummer_not_yet_issued` with invoice footers still
  holding the placeholder `VOR LIVEBETRIEB EINTRAGEN: Name, Anschrift,
  Steuernummer`, which §14 UStG requires. So card is not merely unverified, it
  is not set up, and it cannot be until the Finanzamt issues the number.

  Gabriel has said card payment is fine by him. That is a decision about what he
  wants to accept, not evidence the mechanism exists, and the shop now says
  invoices are settled by bank transfer with card arranged on request.
- GVL catalogue table and the Förderantrag both have blanks only he can fill:
  real release dates, ISRCs, which tracks were actually released, real bio
  facts and real costs. Do not guess any of them.
