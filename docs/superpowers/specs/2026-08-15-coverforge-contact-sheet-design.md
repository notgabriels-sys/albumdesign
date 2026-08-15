# Coverforge contact-sheet review packet

## Goal

Give an artist, designer, label, or release manager one local command that
turns a batch of artwork variants into a compact, shareable review packet
before a delivery export is chosen. The packet must be useful without a
server, account, upload, or source-media copy.

## Problem

`coverforge build` is deliberately delivery-oriented: it processes a master
into platform outputs. That is too late and too granular for the earlier
creative-review step, where a folder may contain dozens of artwork variants
that need to be compared at once. Manually assembling a contact sheet is slow,
error-prone, and makes it easy to lose the filename that identifies the
candidate being discussed.

## Decision

Add a `coverforge contact-sheet` command. It accepts one or more image paths
or directories using the same one-level image discovery behavior as the
existing `check` and `build` commands. It inspects every selected image and
writes a new, offline review packet containing exactly:

- `CONTACT_SHEET.jpg`: a deterministic-layout raster grid with numbered,
  letterboxed previews;
- `CONTACT_SHEET.html`: a self-contained offline index that embeds the sheet
  by relative filename and maps every number to a safely escaped source
  filename and captured image dimensions.

The default layout is four columns of 480-pixel preview cells. Operators can
choose a positive `--columns` value, a positive `--cell-size` in pixels, a
hex `--background`, and an optional `--title`. `--dry-run` inspects and plans
the packet but creates no output. `--json` preserves the existing CLI pattern
of returning an owner-local result with actual output locations.

## Safety and privacy boundary

The command is local-only. It neither uploads nor modifies source artwork,
contacts a service, copies original media into the output, determines rights,
or records an approval decision. It creates a derivative contact-sheet JPEG
and offline HTML index only.

The output directory must not exist and must be outside every selected image's
parent directory. This prevents an output sheet from being written into a
variant folder and accidentally becoming a later input. The command completes
all input inspection and in-memory composition before it creates the output
directory, so an unreadable image does not leave a partial review packet.

The HTML index contains only filenames, image dimensions, and the fixed
relative sheet filename; it never contains absolute source paths. All
source-derived text is HTML-escaped. The raster sheet uses ordinal labels and
dimensions, avoiding font-dependent rendering or unsafe source text in the
bitmap itself.

To keep local resource use bounded, the command refuses a planned contact
sheet whose canvas would exceed a documented pixel cap. This is an availability
guard, not a statement about image validity or destination suitability.

## Implementation shape

Create `coverforge/contactsheet.py` as a focused module that owns:

- layout validation and deterministic canvas dimensions;
- composition from already inspected `SourceImage` values using the existing
  normalisation and resize helpers;
- safe, fresh-output checks and packet writes;
- the result model used by the CLI and tests.

`coverforge.cli` will add a `contact-sheet` subcommand and reuse
`collect_masters()` plus `inspect()`. Existing `targets`, `check`, and `build`
semantics remain unchanged. New tests use generated Pillow artwork and verify
the exact output set, fresh-output boundary, dry-run behavior, no absolute-path
leakage, and hostile filename escaping in the HTML index.

## Acceptance criteria

1. A batch of synthetic artwork produces exactly the JPEG and offline HTML
   review files in a new outside-output directory.
2. The sheet has a deterministic grid geometry, while the HTML index maps each
   ordinal to its selected filename and dimensions without absolute paths.
3. An output inside any selected source directory is rejected before any
   directory or file is written.
4. `--dry-run` writes nothing, malformed images fail cleanly, and unsafe
   layout values are rejected.
5. The HTML index safely escapes a hostile filename instead of treating it as
   markup.
6. The complete suite, a fresh wheel build, and an installed-wheel smoke run
   pass without real artwork or network operations.
