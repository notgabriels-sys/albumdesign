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
as the landing page and `404.html` catching everything else.

`docs/share*.png` are the link-preview images, one per page, drawn by
`tools/make_share_card.py`. `favicon.svg`, `favicon.ico` and
`apple-touch-icon.png` are drawn by `tools/make_favicon.py`. All of them are
committed rather than built in CI because they use a system font, and a build
step would produce slightly different files on every runner. `share.png` keeps
its bare name because it is in every link already shared; `impressum.html` and
`404.html` borrow it rather than having their own.

Adding a page means more than writing it: `consistency_check.py` requires the
Open Graph set on every page, requires `sitemap.xml` to list exactly the pages
that exist, requires a structured-data block that matches the page's own title,
description and canonical, requires a preview image that exists, is not shared
with another page and records that page in its own bytes, requires the three
icon links, and requires the README to link it. So a new page fails CI until
all of that is done. That is the point. `delivery.html` shipped unlisted for
three commits before the first of those checks existed.

`404.html` is the one page exempt from three of those, and each exemption is
named in the file with its reason rather than being a widened rule: no
structured data (an error state is not a thing, and describing it would assert
a page exists at whatever URL was mistyped), no card of its own, and out of the
sitemap plus a `noindex`, because an indexed error page competes in search with
the pages it exists to rescue people to. `sync_artifacts.py` skips it too: an
artifact is one page reached by its own URL, and nobody arrives at one by
mistyping.

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

  All seven pages were checked against this on 22 August 2026, so it does not
  need redoing. Only two put user text into markup: `delivery.html` (file names,
  fixed and tested) and `splits.html` (collaborator names, through `esc()` in the
  signature block and `textContent` in the row-problem line, both now tested).
  `cover.html` and `loudness.html` read files but never echo the name into
  markup: cover's `innerHTML` is fed only by its own literals plus a format
  string that is one of PNG/JPEG/WEBP/GIF/BMP/TIFF/unknown, and loudness prints
  the name through `textContent`. The other three take no input at all. Both
  splits tests were proved to bite by trimming `esc()` back to `&` alone, which
  injects a live `IMG[onerror]` and fires a real dialog.
- **Do not let a check pass on a measurement that did not happen.** The
  delivery page filtered its over-the-ceiling list on `isFinite` while scoring
  the check `pass`, so a release whose true peaks all failed to measure was told
  every track sat under its ceiling, with the column blank above the sentence.
  Same shape in three other checks. A result nobody measured is a warning that
  says so, never a pass.
- **A conversion that did not happen is not a conversion.** `imageops` swallows
  six exceptions, and two of them were reporting success over work that never
  ran. `_srgb_profile_bytes` returning None made `_encode_once` skip the
  `if SRGB_BYTES` embed, so every output shipped untagged with no warning at
  all, which also silently breaks the byte-reproducibility guarantee above.
  And `preflight` promised `will be converted to sRGB` for a profile
  `inspect()` had already recorded as unreadable, while `_to_srgb` failed on
  that same profile and plain-converted: `profileToProfile` was attempted zero
  times. Both now warn, and the build still delivers, because degraded colour
  is worse than converted colour rather than a reason to produce nothing.

  The other four swallows were checked on 22 August 2026 and are fine, so that
  does not need redoing. `_icc_description` reports what it could not read,
  `inspect` and `normalise` raise `ImageError` from typed excepts, and the EXIF
  default to upright is harmless because `short_edge` is orientation-invariant
  and the rotation is disclosed. `package.py` and `specs.py` are clean.
  One thing was deliberately left: `getattr(os, "O_NOFOLLOW", 0)` silently
  drops the symlink guard on a platform without that constant, while the
  comment claims the write will fail on a link. It is live on linux and a test
  proves it fires, so this is a note, not a bug to fix on a tool with no
  Windows story.
- **An eleven-bit MPEG sync word is not evidence of an MP3.** It turns up in
  arbitrary binary about every 2 KB, so a blind 200 KB scan claimed `.m4a` and
  `.ogg` files as MP3 with a sample rate read off a coincidence, in both
  `delivery.html` and `loudness.html`. Validating the header fields was not
  enough, and requiring a confirming frame chain was not enough either: a test
  buffer that plants a sync every seven bytes defeated both. What works is
  gating the scan on the file declaring itself, an ID3 tag or a real frame at
  offset 0, plus the field validation. Do not loosen that back to a bare scan.
- **A green suite is not evidence a guard is guarding.** Every verdict
  function here is a disjunction, and a term can be deleted without any test
  failing because a sibling term fires on the same fixture. Measured on 22
  August 2026 by deleting each term in turn and running the suite:

  | function | terms | survived before |
  |---|---|---|
  | `BundleAudit.ok` | 9 | 6 |
  | `compare_manifests` has_issues | 12 | 10 |
  | `verify` exit code | 2 | 1 |
  | `check` exit code | 3 | 0 |

  All are pinned now, each condition asserted alone against an otherwise clean
  input so no sibling can mask it. `check` was already fine, so nothing was
  added there. If you add a term to any of these, add the isolated test with
  it, and confirm it fails when the term is removed.

  Two ways the measurement lies, both hit here. A `-k` selector that matches
  nothing prints confident SURVIVED lines over zero tests, so assert the
  baseline ran something. And the first term in a disjunction has no leading
  `or`, so a regex written for the rest mutates nothing; assert the mutation
  changed the file. The driver in this repo's history did both.

  The same sweep run against the browser pages found the same shape, and the
  last two survivors were both in `loudness.html`'s platform table. Deleting
  `if(p.attenuateOnly&&gain>0) gain=0;` printed `+7.0 dB` in Apple Music's gain
  column beside the words `as-is, never boosted`, and every existing assertion
  passed, because the label is computed from the unclamped `p.t-LUFS` while only
  the number moves. Replacing the pill ternary with a flat `"pass"` showed six
  platforms a pass pill next to `turned down` on a -1.5 LUFS master, because
  nothing read the pill's class, only its text. Both are pinned now: the gain
  column and the pill state are asserted, not just the wording beside them.
  All six loudness mutations are caught. Where a page states a verdict in more
  than one place, assert every place, because a test reading only the friendly
  one passes while the number beside it says the opposite.

  `splits.html` was swept last and was the worst of the lot: 8 terms, 4
  survived. Two were the same hole, that every failing fixture in the suite
  totalled exactly 100, so nothing exercised the term that checks the shares
  add up, which is the page's whole job. One was a share with no name against
  it, never tested because the fixture helper always filled a name in. The
  fourth is `isFinite` in `problems()` and is left unpinned on purpose: the
  share box is `input[type=number]`, which sanitises anything it cannot parse
  to `""`, so the row arrives as missing and the branch above fires instead.
  Measured in Chromium on 23 August 2026, `"abc"`, `"Infinity"`, `"1/2"`,
  `"0x10"`, `" 7 "` and `"1e400"` all read back as `""`, while `"-50"` and
  `"1e5"` survive. Only Chromium was tested, so the guard stays rather than
  being deleted on one browser's behaviour, and the test that used to claim to
  cover it now says what it really proves.
- **The split sheet had one `parseFloat(x)||0` left, and it was the one that
  mattered.** `sum()` and `problems()` were fixed for it; `readRow()` was not,
  and `readRow` is what feeds `save()` and `asText()`. Three symptoms, all
  proved in Chromium before being fixed:

  A blank share was saved as `0`, so a **reload** turned "nobody entered this"
  into "this person gets nothing", the badge went fail to pass, and the warning
  naming the row vanished. The earlier badge fix was undone by pressing reload.

  `asText()` printed `0%` for that share, put a signature line under it, and
  totalled 100, so the copied document read complete and internally consistent.
  It also dropped a row that had a share but no name while `sum()` kept
  counting that share, so the listing did not add up to its own total.

  And `copy` said only "Copied to the clipboard." where `print` had always
  warned. Both hand out the same document, so they now share one
  `exportWarning()` and say the same thing about it.

  The rule this leaves: when a fix lands on the on-screen verdict, check every
  other thing that reads the same data. The document that leaves the browser is
  the one that reaches GEMA and GVL, and it was the copy nobody fixed.
- **`sync_artifacts.py` reported success over pages it never read.** Both its
  modes loop over `pages()` and print their happy message after the loop, so an
  empty loop printed it too. With a `docs/` holding no pages, `--check` exited
  0 saying `artifact copies are current` and the write mode exited 0 saying
  `written to ...`. The write mode is CI's `artifact copies derive cleanly`
  step, so that green meant nothing had been derived rather than everything
  deriving cleanly. It now exits 2 and names the directory it looked in.

  `--check` also only ever asked whether each page's copy matched. Nothing
  asked the reverse, so a page deleted from `docs/` left its derived copy in
  the output directory and the check called the directory current with the
  orphan sitting in it. Orphans are now named and fail the check, with
  `RENAMED` accounted for so `preflight.html` and `coverforge.html` are not
  mistaken for orphans of pages that do not exist under those names.

  Both were proved by running them before the fix, and each new test was run
  against the old file to confirm it fails there: five do, and the five that
  guard the ordinary case pass either way, which is what they are for.
- **`packcheck.py` reported a clean pack it had never listened to.** It had no
  tests and no CI step of its own, which is how this lasted. `peak_dbfs`
  returns None for any width it cannot decode and on any read error, and the
  caller dropped that on the floor, so a 32-bit file clipping at 0 dBFS drew no
  comment while a 24-bit file at the identical amplitude was reported as
  clipped. And `--quick` skips the decode entirely while printing the same
  `N WAV files, 0 error(s), 0 warning(s)` summary a full run prints, so a pack
  holding that clipped file reported clean and then wrote its README.txt, which
  is the document that ships with the product.

  Both were proved on a pack built for the purpose. An unmeasured level is now
  a warning naming the file, the summary says what a run did not listen to, and
  a README written from a `--quick` run says so on stderr. The run still
  delivers, in the same spirit as the imageops fix: disclose rather than
  refuse. `tests/test_packcheck.py` is new, and runs under the existing pytest
  CI step, so the tool is no longer unguarded.
- **A check that has never fired is not a check.** `consistency_check.py`
  carries one written for the EUR 25 / EUR 1,200 wrong-checkout bug, comparing
  a button's promised price against the page's own rate table. Its pattern was
  `>\s*(Pay[^<]{0,40})<`, anchored to a capital `Pay` at the start of the
  text, and the shop's buttons read `Mastering, pay €45`. It matched only the
  two section labels, which name no amount, so the inner loop never ran.
  Counted directly: **0 firings across the whole site before, 6 after.** The
  suite had been reporting `all 129 consistency checks passed` with that family
  contributing nothing.

  The money path was never exposed, because the card-link scan beside it does
  fire on all six buttons. The defect was a dead net, not a hole. But a dead
  check in a 129-check suite is exactly what "a green suite is not evidence a
  guard is guarding" means, and the count is the only evidence any family ran.

  Its two sibling scans already name the case where a loop sees nothing; this
  one did not, which is why going dead was silent. It now does: a page carrying
  a payment link whose price-promise scan sees nothing at all fails, because
  that is the regex having drifted off the markup again. The scan is also
  deliberately wider than the payment-anchor one, since the original mismatch
  was a *label* problem and a label does not have to sit on a link to mislead.
- **A fact restated somewhere else is a fact that can drift.** Structured data
  and the preview cards both restate what a page already says, which is the
  same shape as the EUR 25 button over a EUR 1,200 charge. So neither is typed
  by hand: `make_share_card.py` and the JSON-LD both read the page's own
  `<title>`, `<h1>`, meta description and canonical, and the shop's prices come
  out of its rate table. `consistency_check.py` then asserts the two agree, in
  both directions for the prices. If you add a field, read it, do not retype it.

  Two things the shop's block deliberately does **not** carry. No VAT flag of
  any kind: under §19 no VAT is charged, so neither `included` nor `excluded`
  is true, and a tax treatment contradicting the Kleinunternehmer line sat on
  that page once already. And `impressum.html` carries no structured data at
  all, because it holds his residential address and a machine-readable graph is
  a different thing from a legal notice. A check asserts that stays absent, so
  the exemption cannot quietly become an oversight.

  The mutation sweep found one hole worth remembering: reordering only the
  `position` fields in the landing page's `ItemList` left every URL in place
  and passed, because that check reads URLs while a consumer of the graph reads
  `position`. Both are asserted now. The general form is the one already in
  this file: where a thing is stated in more than one place, assert every place.
- **A generator that crops rather than fails will ship the crop.** The first
  version of the per-page share cards wrapped the description to a guessed
  character count and then sliced the line list, so the loudness card read
  `Measure a master's integrated LUFS and true peak the way the` and stopped.
  It looked broken in the one place a reader decides whether to click. It now
  adds whole sentences, measures in pixels, and raises if not even the first
  sentence fits, because the fix belongs in the page's description and not in
  a slice.

  The same card had the meter bars drawn full height on the right and the text
  then measured as if they were not there, so the tallest bar ran straight
  through the headline. Decoration drawn first does not move text drawn second.

  Both were found by opening the PNG, not by reading the code, and both were in
  code written minutes earlier. Look at the output.
- **The README is a page too.** It is the front page of a public repository,
  so a stranger meets the project there, and it had no route to the rates while
  every tool page had one. It is also a hand-maintained list of URLs next to a
  directory of files, and nobody clicks their own README, so a page renamed in
  `docs/` would leave a dead link there silently. `consistency_check.py` now
  reads `README.md` and asserts every page it links to exists, that the five
  tools are all linked, and that the shop is.
- **The README was left out of the rename, and every README check passed.**
  The rule that a page's name is its `<title>` was applied to the tool pages
  and the landing cards, and the README is the same shape: a hand-typed list of
  names beside a directory of pages. It went on offering a `cover spec
  checker`, a `delivery check` and a `split sheet`, none of which is the name
  of anything on the site, on the front page of a public repository. The
  checks were green because they only ever asked whether the URLs resolved.
  The link text is now compared with each page's own title, and the scan
  counts itself so a drifted markdown pattern fails instead of matching
  nothing quietly. The shop link is deliberately exempt and the reason is in
  the file: it sits inside a sentence rather than in the list of names.

- **And every tool page was still signing itself with its old name.** The
  rename reached the navs, the landing cards, the structured data, the preview
  cards and their alt text, and stopped at the byline in each page's own
  footer. `Split Sheet: a free tool by Gabriel G Alonso` sat at the foot of
  Split Sheet Maker, and the same on all five, with 353 checks green and both
  browser suites passing. A page naming its siblings wrongly is bad; a page
  naming *itself* wrongly, in the last line a visitor reads, is worse, and it
  was the one place nothing looked.

  Found by rendering `docs/` in Chromium and reading the footer, not by
  running anything. Same as the crop and the bars through the headline: look
  at the output. Six checks added, 353 to 359, both failure modes proved.

- **Then the shop and the cover page were still doing it in prose.** Sweeping
  the rendered text rather than the links found two more: `shop.html` signed
  its footer `Studio Shop` while calling itself Mixing and Mastering Rates, on
  the one page money is spent on, and `cover.html`'s opening sentence read
  `Coverforge checks size, shape, format and colour`, which is the CLI's name
  and that page's own former title and appears nowhere else on the site.

  Links and bylines are checked against the title. Prose is neither, so the
  four retired names that are not substrings of a current one are now asserted
  to appear on no page: `Coverforge`, `Loudness Check`, `Release Preflight`,
  `Studio Shop`. Case-sensitive, because "the cover and loudness checkers" is
  ordinary English and not a name. Only four, because `Delivery Check` and
  `Split Sheet` are inside `Release Delivery Check` and `Split Sheet Maker`
  and a ban on them would fire on the correct text.

  The sweep that found them was a script stripping `<script>`, `<style>` and
  tags and printing the surrounding 80 characters of every hit. Most hits were
  those substrings and were false. Two were not, and neither sat in a link.

- **The header wordmark was the last place, and the most visible.** Every tool
  page carried its own wordmark, so after the rename the first thing on the
  page, above the headline, was a name the site had retired: `COVERFORGE` on
  Album Cover Size Checker, `LOUDNESS·CHECK` on LUFS and True Peak Meter,
  `STUDIO·SHOP` on Mixing and Mastering Rates. It survived four rounds of
  fixing names further down the same pages, because every one of those rounds
  read links and bylines and none of them read the header.

  The preview cards had already settled the pattern a year of this file keeps
  arriving at: the site's wordmark, then the page's own title beside it. The
  headers now match the cards. That is also the only shape that fits, since
  `ALBUM COVER SIZE CHECKER` set as a letterspaced monospace wordmark is wider
  than a 360px viewport, so the per-page wordmark could not have survived the
  new names even if nobody minded the old ones.

- **The a11y suite measured contrast on pages where nothing had happened.**
  Every page was loaded untouched, so the pass, warn and fail pills, the
  coloured verdict lines and the tinted cells did not exist when the contrast
  was computed, and the suite reported `all text meets WCAG AA contrast` for
  every page in both schemes over a palette it had never seen. The site's
  semantic colours are the ones a visitor is actually here to read.

  This repository's oldest defect, wearing accessibility clothes. The suite now
  drives loudness, delivery and cover with real fixtures in both schemes and
  asserts a verdict rendered *before* believing an empty failure list. Proved
  by pointing the loudness drive at a non-audio fixture: the contrast check
  passes, on nothing, while the new evidence check fails. Measured 23 August
  2026, the real colours all pass, so this closed a hole rather than fixing a
  visible defect.

- **`verify_truepeak.py` does gate, measured 23 August 2026.** Its sibling was
  recorded as swept and this one never was. Six mutations, all caught: each of
  the four expectations moved on its own, the oversampling dropped entirely,
  and `max` replaced by `mean`. Two of the first attempts were no-op
  mutations, caught by the md5-before-and-after guard rather than printed as
  confident SURVIVED lines, which is the third time that trap has been hit
  here.

- **The domain is written twice, and the second copy is the site's life.**
  `SITE` in `consistency_check.py` is what every canonical, sitemap entry and
  preview URL is compared against; `docs/CNAME` is the only thing that makes
  Pages answer on that host. Nothing tied them together. Every other instance
  of a restated fact in this repo makes one page wrong; this one takes the
  site down in either direction, and both directions would have passed all 386
  checks. Three checks now: the file exists, it names exactly the host the
  pages claim, and it is a bare hostname, because a scheme or a trailing slash
  makes Pages drop the custom domain with no symptom but a missing site.

- **The privacy notice named one payment processor and the shop had two.**
  The Datenschutzerklärung was written when Stripe was the only button. Three
  PayPal.Me buttons went on the shop on 22 August 2026 and PayPal appeared
  nowhere in it: a third party receiving the visitor's data, acting as its own
  controller, undisclosed under Art. 13 DSGVO, on the one page money is spent
  on. The same list also promised that the `Cover-, Loudness-, Checklisten-
  und Split-Sheet-Werkzeuge` run entirely in the browser, which is four of the
  five and omits the delivery check, the tool a whole unreleased release gets
  dropped into.

  Both were hand-written lists beside a site that grew. The tools sentence is
  now the invariant, `Alle Werkzeuge auf dieser Website`, which cannot go stale
  when a sixth is added, and a check derives the processor names from the
  payment links the pages actually carry rather than from a map someone has to
  remember to update: `buy.stripe.com` and `paypal.me` both yield their
  second-to-last label. Adding a processor without disclosing it now fails.

  The cited PayPal privacy policy is exempted as an exact URL, never by host.
  Exempting `paypal.com` wholesale would readmit the `paypal.com/ncp/` shape
  that hid the EUR 1,200 charge, and a test proves that link is still blocked.

- **The repository's About box and topics are not in the repo.** They are
  settings, so nothing in `docs/` or `tools/` can set them and no check can
  see them. As of 23 August 2026 both are empty, which is why the repo shows
  up in GitHub search as a bare name. Only Gabriel can fill them in; the text
  to paste is in the launch-kit artifact.
- **A picture of a claim needs the claim recorded in it.** The preview cards
  restate each page's headline and description, and the checks asserted the
  file existed, was unique, was referenced and had matching alt text. None of
  them asked whether it said what the page says. Editing `loudness.html`'s
  `<h1>` left its card showing the old headline and all 250 checks passed, plus
  the a11y suite. Each card now carries the strings it was drawn from in PNG
  iTXt chunks, and `consistency_check.py` parses them out of the raw bytes with
  `struct` and `zlib` rather than through Pillow, even though Pillow is
  installed in that job: a check that trusts the library the generator wrote
  with can only confirm that library round-trips. Same reason the preview
  checks do not import `make_share_card.py`.

  The source *page* is recorded as well as the text, because with only the text
  compared, swapping two cards is caught but copying one over another whose
  headline happens to match is not.

  **And then it failed on its own implementation the same day.** The card draws
  three strings and recorded two: the title is printed as the eyebrow and went
  unrecorded, so retitling a page left the old name on its card and all 318
  checks passed. Fixed hours after the rule above was written into this file,
  and the new check earned its keep immediately by firing on all seven cards
  the moment the titles moved. When you write the check, enumerate what the
  thing actually draws rather than what you were thinking about at the time.

  The eyebrow is measured too. It shares its line with the wordmark and the
  meter bars, so it has less room than anything else on the card, and a longer
  title runs into them rather than off the edge.
- **Then the same alt text went stale again, one field along.** The check
  above compares the alt against the headline the card records, and only that.
  Renaming the seven pages moved every eyebrow and left six alt texts naming a
  card that no longer exists: `Preflight Coverforge` describing a card that
  reads ALBUM COVER SIZE CHECKER, with all 340 checks green plus the a11y
  suite, because the headlines had not moved and the headline was the only
  thing anything read. Found by reading a republished artifact's `<head>`, not
  by running anything.

  This is the card that recorded two of the three strings it drew, in the
  checker instead of the generator: the fix enumerated what the *card* draws
  and stopped there, while the alt describes the same card and was still only
  half read. `make_share_card.py` now records `preflight:eyebrow`, the exact
  string it printed, present only on the cards that print one, and the alt
  check reads it. Whether a card has an eyebrow is therefore asked of the card
  rather than re-derived from `page != "index.html"`, because a condition
  restated in two files is a condition that can drift apart, which is this
  entry's other half. Six new checks fire, 340 to 346, and the old alt was put
  back on one page to prove it fails.

- **A containment test against a short common word cannot fail for the reason
  it exists.** The alt-text check asked whether the owning page's title
  appeared anywhere in the alt. "Preflight" is a substring of nearly any
  sentence about this site, so it passed `impressum.html` while that page's alt
  still described the card as it looked before the cards were redrawn: a screen
  reader there was handed a description of an image that was not on the page.
  It now compares against the headline the card itself records. When you write
  a containment check, ask what string would fail it, and if the answer is
  "almost nothing", it is not a check.
- **`cmd | tail -3; echo $?` reports tail's status, not cmd's.** Used exactly
  that to confirm `sync_artifacts.py --check` still exits non-zero on an orphan,
  read `exit=0`, and nearly recorded a working guard as broken. Capture it:
  `out=$(cmd 2>&1); rc=$?`. This is the same family as the two ways the mutation
  measurement lies, already above.
- **A generator that draws past the edge is the crop bug's twin.** `_wrap`
  breaks on spaces, so a word wider than the column comes out on a line of its
  own and stays too wide: measured, a 38-character word at 60px produced a
  1277px line in a 1056px column, drawn straight off the card. One version
  cropped the text and said it worked, this one overflowed it and said it
  worked. `_overflows()` now measures every line, the headline loop tries
  smaller sizes, and a sentence containing an unbreakable word is not a fit.
- **Pillow's ICO save will not upscale, and says nothing when it drops sizes.**
  `frames[0].save(path, sizes=[(16,16),(32,32),(48,48)], append_images=...)`
  with a 16px base wrote a single-size `.ico` and reported success. The largest
  frame has to be the base. Each entry is still drawn natively at its size
  rather than downsampled, which is what keeps 16px crisp: a 64px master
  resized to 16 put 2.5px bars across pixel boundaries and produced a pale
  smear. Found by opening it at 8x, which is the only way to see a favicon.
- **Three things in `docs/` are committed rather than built, and each now has a
  test that they match their generator.** `share*.png` (system font),
  `favicon.svg`, `favicon.ico` and `apple-touch-icon.png` (same). Committing
  means the file that ships is the file someone looked at, which is only true
  while the committed bytes and the generator agree, and until 23 August 2026
  nothing said they did. `tests/test_make_share_card.py` and
  `tests/test_make_favicon.py` regenerate into a tmp dir and compare bytes. If
  you add another committed asset, add that test with it.
- **The icons are drawn from one 16-pixel grid, not from the SVG.** Deriving
  the raster sizes from the SVG's 32-unit grid rounded two bars into contact
  and the icon stopped being four bars. The grid in `make_favicon.py` is chosen
  by hand and every other size is a whole multiple of it, including the SVG.
  The home-screen icon keeps a 10 per cent margin because iOS masks its corners
  off; drawn full bleed first, and the outer bars ran into all four edges.
- **The two browser suites were swept on 23 August 2026 and do guard.** Every
  mutation below was caught, so this does not need redoing: contrast dropped
  below AA, an `h1` removed, the `main` landmark removed, a heading level
  skipped, K-weighting bypassed, the integrated gate removed, true peak
  replaced by sample peak, CMYK downgraded to a pass, an unrecognised file
  called a pass, the severity ranking flattened, and the square check forced
  true. `verify_lufs.py` was checked the same way and exits 1 when only the
  expectation moves.

  One gap was real and is now closed. `silence.wav` went to `loudness.html`
  and nowhere else, so the delivery page's "a track nobody could measure is a
  warning, never a pass" behaviour, the exact defect recorded further up this
  file as fixed, had no test on that page. A silent bounce is not hypothetical:
  a master fader left down and the release ships as silence. Two mutations now
  fail, downgrading the warning to a pass and dropping unmeasured tracks from
  the list.

  A live true peak cannot actually be non-finite, because both `log10` calls
  add `1e-12`, so a silent file reads -240 dBTP rather than -Infinity. The
  `isFinite(r.tp)` terms are therefore unreachable siblings of the `null`
  checks beside them, in the same position as the `isFinite` in `splits.html`:
  left in place, not pinned, and written down here so the next sweep does not
  mistake them for a hole.
- **Three ways a mutation measurement lied, all hit on one afternoon.** The two
  already above are a `-k` selector matching nothing and a regex that mutates
  nothing. Two more, both mine:

  A harness that counts `FAIL` lines reads a *crash* as a clean run. Forcing
  every `isFinite` in `delivery.html` to true printed "0 FAIL" because the
  suite had aborted. Require positive evidence the run finished.

  Then the fix for that was itself wrong: it grepped for `CHECKS FAILED` while
  `browser_test.js` prints `2 CHECK(S) FAILED`, so a genuine failure was read
  as a crash. Assert on the exit code, which is unambiguous, rather than on
  text you did not go and look at.

  And before any of it, two mutations targeted `kFilter` and `verdictFor`,
  neither of which exists: the real names are `kWeight` and an inline `sev`
  table. Both printed a confident SURVIVED over a file nothing had touched.
- **A name written twice drifts the moment you rename anything.** Retitling the
  seven pages left every tool page calling its four siblings by names none of
  them used any more, and left `index.html` naming the same five links one way
  in its structured data and another on its own visible cards. All 329 checks
  passed, because each check compared the copies with each other rather than
  with the page. The sibling-name check was itself part of the problem: it
  held a hardcoded label map, so the checker had retyped the names too.

  A page's name is its `<title>`. `TOOL_PAGES` now derives from that, the
  landing cards and the sibling navs use it, and three checks assert the card,
  the structured list and the title agree. Read it, do not retype it, applies
  to `consistency_check.py` as much as to the pages it checks.
- **Two single-check families were vacuously true.** `len(addrs) <= 1` for the
  contact address passes on an empty set: measured, stripping every `mailto:`
  from all nine pages left 325 checks green with no way to reach him anywhere
  on the site, and booking starts by email. The VAT check compared two sets
  that were both empty once `Kleinunternehmer`, `UStG` and `VAT` were stripped
  from the shop, so a page quoting prices as totals with the section 19 basis
  missing passed too.

  Both now assert the thing exists before comparing it, the address is checked
  against the business one, and `notgabriels@gmail.com` is asserted to appear
  on no page at all. Counting checks per family is what found these: no family
  fires zero times, but three fired exactly once, and two of those three were
  the dead-net shape wearing a passing result.
- **The Chromium install step in CI hangs sometimes.**
  `npx playwright install --with-deps chromium` takes about 25 seconds
  normally and has twice sat for 5 to 20 minutes on a PR while `main` was
  fine. It is upstream, not the diff, and it runs before any repo code.
  Cancel the run and re-run it rather than debugging the change.

## The site is live

https://gabs-utilities.com/ serves `docs/` from `main`, through the `docs/CNAME`
file. Gabriel registered the domain on 24 August 2026 and set the DNS himself.
The old `notgabriels-sys.github.io/albumdesign/` address still redirects, so
links shared before the switch keep working, but nothing in the repo should
name it any more: `SITE` in `consistency_check.py` and `sync_artifacts.py` is
the domain, and every canonical, sitemap entry and README link is compared
against it.

Pages was switched on by hand, because it had to be: an Actions token is
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

**Publishing by bare file path only keeps the URL while this session still holds
that path's mapping, and it does not always.** Republishing
`arts/loudness.html` by path created a *second* artifact under the same title
instead of updating `d84def54`, in the same run where four sibling files
published by path kept their URLs. There is no delete action, so the duplicate
is permanent: `6a57bf35-bd5c-4ccf-83d6-5d8dac5ddabd`, private and orphaned.
Pass `url` explicitly for every republish unless this session published that
exact path itself and you can see it in the transcript. The refusal that
follows is the normal path, not a problem: read the live version, diff it
against the derived copy, confirm the only published-only lines are the ones
being replaced, then publish.
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

  The PayPal MCP server has returned `Unauthorized` on every attempt, and in
  several sessions it has not been connected at all. It has still never been
  read. Knowing the address an account sits under says nothing about what a
  button would charge, which is the whole lesson of the Stripe links below.

  Gabriel saying card payment is fine by him was a decision about what he wants
  to accept, never evidence the mechanism existed. Reading the objects is what
  found both the €1,200 link and the €160-plus-VAT pair.

  **Three PayPal buttons went on the shop on 22 August 2026 anyway, and the
  reason they could is worth understanding before touching them.** They are
  PayPal.Me links, `paypal.me/gabrielgga00/45EUR` and the other two rates. A
  PayPal.Me link states its amount and currency in the URL path, documented by
  PayPal, so there is no stored object holding a different number. That is the
  entire basis: not that the account was read, but that this link shape has
  nothing left to read. `paypal_amount_mismatches()` in `consistency_check.py`
  asserts each URL amount against the rate table on the same page, and fails on
  an amount the table does not quote, a missing currency, a non-euro currency,
  and a bare handle with no amount at all. All four were proved to fail before
  the buttons shipped.

  So `paypal.me` is on VERIFIED_PAYMENT_HOSTS and `paypal.com` deliberately is
  not. Do not add `paypal.com/ncp/` links, the current hosted-payment-link
  shape: those put the amount back in an object nobody here can read, which is
  exactly the setup that hid the €1,200 charge. A test asserts they still fail.

  **The handle was settled on 23 August 2026, by a payment rather than a read.**
  He sent EUR 1 to `paypal.me/gabrielgga00` from a logged-out browser and
  reported the receipt did not arrive at notgabriels@gmail.com. He has two
  accounts, so it landed on the business one, hologrampeoplemusic@gmail.com,
  which is also the Impressum address.

  That is an observation of where money actually went, which is worth more than
  the position it replaced, where the handle rested on his memory of a
  dashboard. It is still his report rather than something read from here:
  `paypal.me` is blocked by the egress proxy and the API still will not
  authorise. Who receives was always his to answer; how much is what the checks
  cover. If money ever lands in the wrong account, the handle is the thing to
  change.
- GVL catalogue table and the Förderantrag both have blanks only he can fill:
  real release dates, ISRCs, which tracks were actually released, real bio
  facts and real costs. Do not guess any of them.
