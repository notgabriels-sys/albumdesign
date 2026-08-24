# Coverforge

Preflight your release artwork, then export the whole per-platform delivery pack
in one command.

**Free browser tools, nothing to install:**
[Album Cover Size Checker](https://gabs-utilities.com/cover.html) ·
[Split Sheet Maker](https://gabs-utilities.com/splits.html)

They run entirely in your browser. Nothing is uploaded, so unreleased masters
stay on your machine.

If you would rather someone else finished the record, the
[rates are here](https://gabs-utilities.com/shop.html):
mixing and mastering by Gabriel G Alonso, Berlin.

You finish a cover, and then comes the boring half: 3000×3000 for the
distributor, 3000×3000 for Beatport, something under 2 MB for SoundCloud, a 9:16
crop for stories, and every one of them flattened, sRGB, no alpha, baseline JPEG,
because one wrong file gets the release bounced a week before it drops.
`coverforge` does that pass for you and tells you up front which targets your
master can't legitimately reach.

```
$ coverforge check master.png
master.png
  3200x3200  RGBA  PNG  4.1 MB  vs 10 target(s)

  ! has transparency; it will be flattened onto #ffffff. Most stores reject alpha
    outright, so check the result looks right
  - no ICC profile embedded; assuming sRGB

  ok 10/10 targets clear: bandcamp, spotify, apple_music, beatport, soundcloud,
     soundcloud_distro, instagram_post, instagram_story, web_thumb, archive

$ coverforge build master.png -o delivery/ --name "Lack of Fate - Drift Protocol"
master.png -> delivery
  bandcamp          3000x3000  jpeg q92   844 KB  lack-of-fate-drift-protocol--bandcamp--3000x3000.jpg
  spotify           3000x3000  jpeg q92   844 KB  lack-of-fate-drift-protocol--spotify--3000x3000.jpg
  apple_music       3000x3000  jpeg q95   994 KB  lack-of-fate-drift-protocol--apple_music--3000x3000.jpg
  beatport          3000x3000  jpeg q92   844 KB  lack-of-fate-drift-protocol--beatport--3000x3000.jpg
  soundcloud        1400x1400  jpeg q90   264 KB  lack-of-fate-drift-protocol--soundcloud--1400x1400.jpg
  soundcloud_distro 3000x3000  jpeg q92   844 KB  lack-of-fate-drift-protocol--soundcloud_distro--3000x3000.jpg
  instagram_post    1080x1080  jpeg q90   183 KB  lack-of-fate-drift-protocol--instagram_post--1080x1080.jpg
  instagram_story   1080x1920  jpeg q90   202 KB  lack-of-fate-drift-protocol--instagram_story--1080x1920.jpg
  web_thumb           600x600  jpeg q85    75 KB  lack-of-fate-drift-protocol--web_thumb--600x600.jpg
  archive           3000x3000  png        197 KB  lack-of-fate-drift-protocol--archive--3000x3000.png

9 files written, worst finding: info
```

## Shipping a sample pack

`tools/packcheck.py` is `coverforge check` for audio: the things a buyer judges
you on are mechanical and easy to get wrong across 130 files by hand.

```bash
python tools/packcheck.py path/to/Duress_Vol1
python tools/packcheck.py path/to/Duress_Vol1 --write-readme --title "Duress - Vol. 1"
```

It checks WAV 24-bit / 44.1 kHz, catches clipped and silent files, junk like
`.DS_Store`, untrimmed one-shots, tonal material missing its key, loops without
a BPM in the filename, and loops whose length is not a whole number of bars at
their stated BPM. `--write-readme` generates the pack README with real file
counts, and refuses while there are errors. `--quick` skips decoding audio.

Exit codes match the rest of the repo: `0` clean, `1` findings, `2` bad usage.

## Install

Coverforge needs Python 3.11+ and Pillow. From the repository root:

```bash
uv venv && uv pip install -e '.[dev]'
# or: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Then use `coverforge ...`, or `python -m coverforge ...` without installing the
console entry point.

## What it actually does to your pixels

Every export goes through the same normalisation, once per master:

- **EXIF rotation is baked in**, so a phone-shot or scanned element can't flip
  later in someone else's renderer.
- **Converted to sRGB** through the embedded ICC profile if there is one. CMYK
  masters are converted too, with a warning, because the colour *will* shift and
  you want to see that before a store does.
- **Alpha is flattened** onto a colour you choose (`--flatten '#000000'`), never
  silently dropped.
- **Resized with Lanczos**: centre-crop for square targets, scale-to-fit with a
  blurred backdrop for the 9:16 story.
- **Encoded baseline, 4:4:4, sRGB-tagged.** Progressive JPEGs get rejected by
  some delivery pipelines, and chroma subsampling smears exactly the hard-edged
  typography that cover art is made of.
- **Size caps are respected.** SoundCloud's 2 MB ceiling is enforced by bisecting
  JPEG quality down to the highest value that fits, and if even quality 55 won't
  fit you get told rather than shipped mush.

## What it refuses to do

It will not upscale your master to fake a spec. If a 1600px master is fed to a
3000px target, that target is **skipped** with the reason printed. `--allow-upscale`
overrides it when you've decided you don't care.

Targets with a floor (`min_source`) are a harder no: below that, the target is
skipped even with `--allow-upscale`, because the render would be upscaled or
soft. Some of those floors are stricter than what the store documents, and one
or two are ours entirely, so each target's note in `targets.toml` says whose
number it is and why. The web checker at `docs/cover.html` reports the
platform's published minimum instead, which is why the two do not always agree.

## Commands

```bash
coverforge targets                         # list target definitions
coverforge check ART... [--strict]         # preflight; writes nothing
coverforge build ART... -o DIR             # render a delivery pack
coverforge sheet ART... -o SHEET.jpg       # quick single-JPEG variant grid
coverforge contact-sheet ART... -o DIR     # JPEG + offline HTML review packet
coverforge audit DELIVERY...               # validate expected delivery files
coverforge verify DELIVERY...              # audit plus manifest checksums
coverforge package DELIVERY... -o DIR      # validated handoff ZIP files
coverforge manifest LEFT RIGHT             # compare two build captures
```

`contactsheet` is retained as an alias for `contact-sheet`.

`ART` can be files or a directory. Point `build` at a folder of variants and
each one gets its own output folder:

```bash
coverforge build ~/art/ft007-variants/ -o delivery/ --group dsp
# delivery/ft007-cover-v1/... delivery/ft007-cover-v2/... etc.
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--only spotify,bandcamp` | just these targets |
| `--group dsp` | groups are `dsp`, `social`, `web`, `archive` |
| `--name "Artist - Title"` | slugified into the output filenames |
| `--flatten '#000000'` | colour behind transparency (default white) |
| `--allow-upscale` | render targets larger than the master |
| `--dry-run` | build/review packet: report the plan without writing |
| `--strict` | check: exit non-zero on warnings, not just errors |
| `--json` | machine-readable output from supported commands |

Exit codes: `0` clean, `1` findings (errors, warnings under `--strict`, invalid
deliveries, differences, or skipped targets), `2` bad usage or unreadable input.
That makes pre-delivery automation straightforward:

```bash
coverforge check final-master.tif --strict || exit 1
```

## Picking between variants

For a quick visual pass, combine variants into one labelled JPEG:

```bash
coverforge sheet ~/art/ft011-variants/ \
  --title "FT011 visual review" --columns 4 -o review/ft011.jpg
```

For a review packet that keeps the filename mapping visible, use:

```bash
coverforge contact-sheet ~/art/ft011-variants/ \
  --title "FT011 visual review" --columns 4 -o review/ft011
```

It writes exactly two files into a **new** directory that must sit outside every
source image's own folder:

- `CONTACT_SHEET.jpg`: a numbered, letterboxed preview grid
- `CONTACT_SHEET.html`: an offline index mapping each number to its filename,
  dimensions, and colour mode

`--dry-run` validates the images, layout, and output location without writing
anything. `--cell-size`, `--columns`, and `--background '#rrggbb'` tune the
packet. Source art is never copied, altered, or uploaded.

## Validating and packaging a delivery

Validate expected files, filename structure, dimensions, and formats:

```bash
coverforge audit build/my-release
```

If the build used `--only` or `--group`, select the same subset during the
audit. To also compare byte counts and SHA-256 checksums against the manifest:

```bash
coverforge verify build/my-release
```

Create a shareable package only after the same validation passes:

```bash
coverforge package build/my-release -o release-packages
```

Each ZIP includes `COVERFORGE_PACKAGE.json`, with the audit summary and hashes
for the included files. `--force` can package a bundle with findings, but the
command still exits non-zero so automation cannot mistake it for a clean pack.

Compare two generated manifests or bundle folders when a revision arrives:

```bash
coverforge manifest build/my-release-v1 build/my-release-v2
coverforge manifest build/my-release-v1 build/my-release-v2 --json
```

## What a build writes

A non-dry-run build that can produce at least one selected target writes one
rendered delivery file per produced target. It also writes `DELIVERY.md`, a
human-readable inventory, and `manifest.json`, the machine-readable capture.
Skipped targets have no rendered file.

`check` is report-only and writes nothing. `build --dry-run` reports the planned
result but writes no output directory, delivery files, `DELIVERY.md`, or
`manifest.json`.

## What `manifest.json` is, and is not

The manifest uses schema version 1. For a valid name it contains no local paths,
so it is safe to hand to someone else. It records the SHA-256 of the source and
every emitted output, byte counts, rendering facts, and a deterministic
`capture_id` derived from the rest of the payload.

That is a record of **the bytes this run read and wrote on your machine**. It is
not proof of authorship, ownership, rights, approval, release-readiness, or
external platform acceptance. Coverforge does not upload files or make those
decisions for you.

## Picking between variants

Before you decide which master to export, turn a folder of variants into a
single sheet you can look at:

```bash
coverforge contact-sheet ~/art/ft011-variants/ \
  --title "FT011 visual review" --columns 4 -o review/ft011
```

It writes exactly two files, into a **new** directory that must sit outside
every source image's own folder:

- `CONTACT_SHEET.jpg` — a numbered, letterboxed preview grid
- `CONTACT_SHEET.html` — an offline index mapping each number to its filename,
  dimensions and colour mode

`--dry-run` validates the images, layout and output location without writing
anything. `--cell-size`, `--columns` and `--background '#rrggbb'` tune the
sheet. Source art is never copied, altered or uploaded.

## What manifest.json is, and is not

The manifest is schema version 1. For a valid name it contains no local paths,
so it is safe to hand to someone else. It records the SHA-256 of the source and
of every file written, plus a deterministic `capture_id` derived from the rest
of the payload.

That is a record of **the bytes this run read and wrote on your machine**. It is
not proof of authorship, ownership, rights, approval or release-readiness, and
it says nothing about whether a platform will accept the files.

## The specs are yours to edit

`coverforge/targets.toml` holds every built-in target. The numbers are a
best-effort snapshot, and platforms change requirements without announcing it,
so check them against what your distributor currently demands before relying on
them.

Adding a target is a few lines:

```toml
[targets.vinyl_sleeve]
name = "Vinyl sleeve proof"
group = "print"
width = 3500
height = 3500
format = "png"
min_source = 3500
fit = "cover"
notes = "Send to the pressing plant."
```

Keep your own set outside the repo and merge it on top of the built-ins:

```bash
coverforge build master.png -o out/ --extra-targets ~/.config/coverforge.toml
```

`--extra-targets` overrides matching keys and adds new ones; `--targets-file`
replaces the built-in set entirely.

## Development

```bash
uv pip install -e '.[dev]'
python -m pytest tests -q
```

The browser tools in `docs/` have their own checks. They need Playwright and the
image fixtures, which are generated rather than committed:

```bash
npm install playwright
python tools/make_fixtures.py     # writes tools/fixtures/
node tools/browser_test.js        # functional: cover and split-sheet tools
node tools/a11y_test.js           # contrast, headings, landmarks, keyboard
```

Two more run in CI and need nothing installed:

```bash
python tools/consistency_check.py       # cross-page invariants
python tools/sync_artifacts.py --check  # are the published copies stale?
```

`consistency_check.py` asserts the things that have actually gone wrong: the
rate table agreeing across every page that quotes it, no unverified payment link
reaching a page, and no page making a network call, which is what "nothing is
uploaded" means.
Each check is there because that exact thing broke once.

---

## Gabriel Tools + Code

Part of Gabriel García Alonso's public tool/product ecosystem. Browse the master catalog for related audio tools, repositories, Hologram People soundware, and services:

[Gabriel Tools + Code](https://gabriel-tools-and-code.notgabriels960914.chatgpt.site/)
