# coverforge

Preflight your release artwork, then export the whole per-platform delivery pack
in one command.

You finish a cover, and then comes the boring half: 3000×3000 for the
distributor, 1400×1400 for Beatport, something under 2 MB for SoundCloud, a 9:16
crop for stories, and every one of them flattened, sRGB, no alpha, baseline JPEG
— because one wrong file gets the release bounced a week before it drops.
`coverforge` does that pass for you and tells you up front which targets your
master can't legitimately reach.

```
$ coverforge check master.png
master.png
  3200x3200  RGBA  PNG  4.1 MB  vs 9 target(s)

  ! has transparency; it will be flattened onto #ffffff. Most stores reject alpha
    outright, so check the result looks right
  - no ICC profile embedded; assuming sRGB

  ok 9/9 targets clear: bandcamp, spotify, apple_music, beatport, soundcloud,
     instagram_post, instagram_story, web_thumb, archive

$ coverforge build master.png -o delivery/ --name "Lack of Fate - Drift Protocol"
master.png -> delivery
  bandcamp          3000x3000  jpeg q92   844 KB  lack-of-fate-drift-protocol--bandcamp--3000x3000.jpg
  spotify           3000x3000  jpeg q92   844 KB  lack-of-fate-drift-protocol--spotify--3000x3000.jpg
  apple_music       3000x3000  jpeg q95   994 KB  lack-of-fate-drift-protocol--apple_music--3000x3000.jpg
  beatport          1400x1400  jpeg q92   286 KB  lack-of-fate-drift-protocol--beatport--1400x1400.jpg
  soundcloud        1400x1400  jpeg q90   264 KB  lack-of-fate-drift-protocol--soundcloud--1400x1400.jpg
  instagram_post    1080x1080  jpeg q90   183 KB  lack-of-fate-drift-protocol--instagram_post--1080x1080.jpg
  instagram_story   1080x1920  jpeg q90   202 KB  lack-of-fate-drift-protocol--instagram_story--1080x1920.jpg
  web_thumb           600x600  jpeg q85    75 KB  lack-of-fate-drift-protocol--web_thumb--600x600.jpg
  archive           3000x3000  png        197 KB  lack-of-fate-drift-protocol--archive--3000x3000.png

9 files written, worst finding: info
```

## Install

Needs Python 3.11+ (it uses the stdlib TOML reader). Pillow is the only
dependency.

```bash
uv venv && uv pip install -e .
# or: python3 -m venv .venv && .venv/bin/pip install -e .
```

Then `coverforge ...`, or `python -m coverforge ...` without installing.

## What it actually does to your pixels

Every export goes through the same normalisation, once per master:

- **EXIF rotation is baked in**, so a phone-shot or scanned element can't flip
  later in someone else's renderer.
- **Converted to sRGB** through the embedded ICC profile if there is one. CMYK
  masters are converted too — with a warning, because the colour *will* shift and
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

Targets with a hard platform floor (`min_source`) are a harder no: below that, the
target is skipped even with `--allow-upscale`, because the store would reject it
anyway.

## Commands

```bash
coverforge targets                       # list targets, sizes, floors, notes
coverforge check ART... [--strict]       # report only, writes nothing
coverforge build ART... -o DIR           # write the delivery pack
```

`ART` can be files or a directory. Point it at a folder of variants and each one
gets its own output folder:

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
| `--dry-run` | build: report what would be written |
| `--strict` | check: exit non-zero on warnings, not just errors |
| `--json` | machine-readable output from any command |

Exit codes: `0` clean, `1` findings (errors, or warnings under `--strict`, or
skipped targets), `2` bad usage or unreadable input. So this drops into a
pre-delivery script:

```bash
coverforge check final-master.tif --strict || exit 1
```

Every build also drops a `manifest.json` and a `DELIVERY.md` table next to the
files — the second one is handy to paste into a mail to a label or distributor.

## The specs are yours to edit

`coverforge/targets.toml` holds every target. **The numbers in it are a best-effort
snapshot, and platforms change requirements without announcing it** — check them
against whatever your distributor currently demands before you rely on them.

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

The browser tools in `docs/` have their own checks. They need Playwright and
the image fixtures, which are generated rather than committed:

```bash
npm install playwright
python tools/make_fixtures.py     # writes tools/fixtures/
node tools/browser_test.js        # functional: parsing, loudness, checklist
node tools/a11y_test.js           # contrast, headings, landmarks, keyboard
```

`verify_lufs.py` and `verify_truepeak.py` check the loudness maths against
the EBU Tech 3341 test signals independently of the browser.
