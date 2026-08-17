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

Build a review sheet to compare multiple master variants quickly:

```bash
coverforge sheet path/to/variants -o review/lof-variants.jpg --columns 4 --title "Lack of Fate — Drift"
```

The command accepts a mix of image files and directories. It writes one JPEG
file by default and is intended to support batch feedback loops before delivery.

Validate completed delivery packs before sharing them with collaborators or labels:

```bash
coverforge audit build/my-release
```

If you generated only a subset (`--only` / `--group`), use the same flags in
`audit` to check that same subset only. The command validates expected files are
present, filenames are parseable, and file dimensions/formats match the selected
target definitions.

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
