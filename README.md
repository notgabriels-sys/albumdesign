# Coverforge

Local preflight and delivery-pack builder for release artwork.

## Install

Use Python 3.11 or newer. From the repository root, install Coverforge with
its development dependencies:

```bash
python3.11 -m pip install -e ".[dev]"
```

## Use

Inspect the configured target definitions:

```bash
coverforge targets
```

Run a report-only preflight for an image. `check` reads the supplied image and
prints findings; it writes no files:

```bash
coverforge check path/to/master.png
```

Write a delivery pack to an explicit output directory:

```bash
coverforge build path/to/master.png --name my-release -o build/my-release
```

Preview the build result without writing output:

```bash
coverforge build path/to/master.png --name my-release -o build/my-release --dry-run
```

The image argument can also be a directory. Use `--only` or `--group` to limit
the selected targets.

## Review a batch of variants

Turn a directory of cover variants into one offline review packet before
choosing which master to export:

```bash
coverforge contact-sheet /path/to/cover-variants \
  --title "FT011 visual review" \
  --columns 4 \
  -o /path/to/review-packets/ft011
```

It writes exactly two files in a **new output directory outside every selected
image directory**:

- `CONTACT_SHEET.jpg`: numbered, letterboxed preview grid;
- `CONTACT_SHEET.html`: an offline review index that maps the numbers to
  filenames, dimensions, and image modes.

Use `--dry-run` to validate the same images, layout, size guard, and output
location without creating files. `--cell-size`, `--columns`, and
`--background #rrggbb` tune the presentation; `--json` prints the owner-local
planned or written paths for scripts.

The review packet contains a derivative sheet and source filenames to make
discussion practical. It does not upload or alter source art, copy originals,
record approval, determine rights, or establish delivery or platform
acceptance.

## What a build writes

A non-dry-run build that can produce at least one selected target writes one
rendered delivery file per produced target in the output directory. It also
writes `DELIVERY.md`, a human-readable inventory, and `manifest.json`, the
machine-readable capture. Skipped targets have no rendered file.

`check` is report-only and writes nothing. `build --dry-run` reports the
planned result but writes no output directory, delivery files, `DELIVERY.md`,
or `manifest.json`.

## Portable manifest boundary

`manifest.json` uses schema version 1. For a valid slug it contains no local
paths. It records the source SHA-256, every emitted output SHA-256, and a
deterministic `capture_id`, with local byte counts and rendering facts. It is a
capture of local bytes selected and emitted by this run only.

Coverforge does not upload files, determine rights, validate external
acceptance, or guarantee destination compliance. The manifest is local
evidence only, not proof of authorship, ownership, rights, approval, or
release-readiness.

## Target definitions

The built-in definitions are in `coverforge/targets.toml` and are editable.
Use `--targets-file` to replace them or `--extra-targets` to merge changes.
Destination requirements drift, so verify current requirements before
delivery. These definitions configure a local workflow; they do not determine
an external outcome.
