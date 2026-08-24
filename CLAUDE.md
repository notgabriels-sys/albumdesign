# Working notes for this repo

## How Gabriel wants work done

Gabriel is a Berlin-based sound engineer, producer and live performer. Keep
the work direct, specific, evidence-based and useful. Do not invent facts,
credits, release dates, client names, rates, platform specifications or
commercial outcomes.

Treat people as people. Promotion must be contextual, permission-aware and
honest. Do not spam, manufacture urgency, claim approval that was not given or
present a technical check as proof of artistic quality.

## Hard rules on claims

- A file check proves only the properties actually inspected. It does not
  prove authorship, ownership, rights clearance, release acceptance or quality.
- Platform specifications change. Keep the source and retrieval date for any
  numeric requirement, and distinguish a platform minimum from this project's
  stricter recommendation.
- Never add a payment link because a URL looks plausible. Read the provider's
  actual object and verify name, amount, currency and tax treatment first.
- Never publish private correspondence, unreleased audio, credentials or
  payment-provider secrets.
- Keep Gabriel's identities separate: Lack of Fate, Fate Through and Hologram
  People are related, but their credits and release claims are not interchangeable.

## Current repository scope

This repository contains:

- `coverforge/`: the Python CLI for inspecting release artwork and building
  per-platform artwork packs.
- `coverforge/targets.toml`: built-in platform targets and their notes.
- `docs/cover.html`: the browser-based artwork checker.
- `docs/splits.html`: the split-sheet generator.
- `docs/shop.html`: the mixing and mastering rate surface.
- `docs/index.html`, `docs/404.html` and `docs/impressum.html`: site navigation,
  fallback and legal pages.
- `tools/packcheck.py`: sample-pack mechanical validation.
- `tools/sync_artifacts.py`: derives standalone browser artifacts.
- `tools/consistency_check.py`: cross-page, payment-link and metadata guards.

Coverforge and the artwork workflow must remain intact when site content is
changed. Do not remove or weaken artwork tests as collateral damage from an
unrelated takedown.

## Testing

From the repository root:

```bash
python -m pytest tests -q
python tools/consistency_check.py
python tools/sync_artifacts.py --out /tmp/albumdesign-artifacts
python tools/make_fixtures.py
node tools/browser_test.js
node tools/a11y_test.js
git diff --check
```

The browser checks require Playwright and the generated image fixtures. The
Python suite must remain useful without browser dependencies.

## Coverforge accuracy

- Do not upscale unless the caller explicitly chooses `--allow-upscale`.
- A target with a `min_source` floor remains blocked below that floor.
- Preserve EXIF orientation, colour conversion, alpha flattening, deterministic
  naming and manifest checksums.
- A generated manifest records the bytes seen and written by that run. It is
  not proof of rights, approval or platform acceptance.
- Build and package commands must fail clearly when the selected targets cannot
  be produced or the output does not validate.
- Source images are never uploaded by the local tools.

## Platform specifications

Use primary platform documentation where possible. Record whether a number is
published by the platform, supplied by a distributor, or chosen conservatively
by this project. Do not convert a recommendation into a hard requirement.

Relevant current sources include Spotify for Artists, Apple Music provider
guidance, Bandcamp help, SoundCloud help and the distributor documentation
named beside individual targets. Re-check them before material spec changes.

## Site and payment safety

The public site uses `https://gabs-utilities.com/`. The retained public tools
are the artwork checker and split-sheet generator. Mixing and mastering is a
human service and must not be conflated with automated file validation.

Payment buttons are a separate release gate. A label, toast, HTTP 200 or URL
shape is not evidence of the amount a provider will charge. Verify buyer-facing
totals after verifying the provider object, and preserve an enquiry path when a
service cannot be safely represented by a fixed checkout.

## Release discipline

Before claiming completion:

1. Inspect the exact diff and confirm no unrelated files moved.
2. Run the relevant tests from a clean checkout.
3. Push the intended branch and read the remote SHA back.
4. Verify each retired public URL independently returns 404.
5. Verify retained artwork and service surfaces still respond and contain the
   expected links.

Publication, payment, successful validation and customer delivery are separate
facts. Report them separately.
