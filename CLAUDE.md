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

- `coverforge/` — the Python CLI. `targets.toml` holds the platform specs and
  is meant to be edited; the numbers are a best-effort snapshot.
- `docs/` — **this is the GitHub Pages web root.** Anything committed here is
  published. Do not put planning notes, specs, or scratch files in it.
- `tools/` — the test suites. Fixtures are generated, not committed.

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
- GVL catalogue table and the Förderantrag both have blanks only he can fill:
  real release dates, ISRCs, which tracks were actually released, real bio
  facts and real costs. Do not guess any of them.
