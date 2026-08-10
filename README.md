# coverforge

Validate album cover artwork against the requirements of the major digital
distributors and streaming platforms before you upload it.

`coverforge check` inspects an image and reports whether it is a square RGB
JPEG/PNG at a high enough resolution — the common denominator of Spotify,
Apple Music, DistroKid and CD Baby.

## Install

```sh
uv venv && uv pip install -e .
```

or with plain pip:

```sh
python -m pip install -e .
```

## Usage

```sh
coverforge check path/to/cover.png
```

Check several files at once:

```sh
coverforge check covers/*.jpg
```

Example output:

```
cover.png
  [PASS] format: PNG
  [PASS] square: 3000x3000
  [PASS] resolution: 3000x3000
  [PASS] color: RGB
  [PASS] filesize: 2.1 MB
  5 passed, 0 warning(s), 0 failed
```

The command exits `0` when nothing failed, `1` when any check failed (or when
`--strict` and there are warnings), so it drops into scripts and CI.

### Profiles

Target a specific platform's published floors with `--profile`:

```sh
coverforge check --profile apple cover.png
```

| Profile | Minimum | Recommended |
| --- | --- | --- |
| `default` | 1400px | 3000px |
| `apple` | 3000px | 3000px |
| `spotify` | 640px | 3000px |
| `distrokid` | 1400px | 3000px |
| `bandcamp` | 1400px | 3000px |

These are convenient starting points based on each platform's published
requirements, not a substitute for their current spec pages. Individual flags
override the chosen profile, so `--profile apple --min-size 1400` relaxes the
minimum back down.

### Options

| Flag | Description |
| --- | --- |
| `--profile NAME` | Distributor preset: `default`, `apple`, `spotify`, `distrokid`, `bandcamp`. |
| `--min-size PX` | Minimum width/height in pixels (default 1400). |
| `--recommended-size PX` | Recommended width/height in pixels (default 3000). |
| `--no-square` | Do not require a square (1:1) image. |
| `--strict` | Treat warnings as failures. |
| `--color` / `--no-color` | Force or disable coloured output. |

## What gets checked

| Check | Fails when | Warns when |
| --- | --- | --- |
| `format` | not JPEG/PNG, or unreadable | — |
| `square` | width ≠ height | — |
| `resolution` | below the minimum (1400px) | below recommended (3000px) or above 6000px |
| `color` | CMYK / other non-RGB colour space | RGBA, grayscale or palette |
| `filesize` | — | above 20 MB |

## Development

```sh
uv pip install -e ".[test]"
pytest
```
