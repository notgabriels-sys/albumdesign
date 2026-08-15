# Coverforge contact-sheet implementation plan

**Goal:** Add a local command that turns a set of design variants into a safe,
offline JPEG contact sheet and HTML review index.

**Architecture:** Keep variant discovery in `coverforge.cli`. Add one focused
`coverforge.contactsheet` module for layout, composition, output containment,
and rendering. It consumes existing `SourceImage` inspection and
normalisation, so the sheet sees the same EXIF, colour-management, and alpha
flattening behavior as delivery exports.

**Tech stack:** Python 3.11+, Pillow, standard-library dataclasses, hashlib,
and html escaping; no new dependency, server, account, upload, or subprocess.

## Constraints

- Preserve all current target, check, and build behavior.
- Never inspect, stage, or alter the owner-untracked `artwork/` folder in the
  primary checkout.
- Create exactly two files in a fresh output directory: `CONTACT_SHEET.jpg`
  and `CONTACT_SHEET.html`.
- Reject outputs inside every selected image's resolved parent; do this before
  output creation.
- The offline HTML may retain source filenames for review, but never an
  absolute source path. Escape all source-derived text.
- Compose the sheet in memory before output creation. A failed input must not
  leave a partial packet.
- Add a sensible maximum canvas-pixel guard and make the error actionable.
- State clearly that the packet is a local visual review aid, not an approval,
  rights, or delivery-compliance record.

## Task 1: Record the contract

- [x] Inspect Coverforge's CLI, image normalisation, output behavior, and test
  conventions.
- [x] Write the design and implementation-plan documents.
- [ ] Commit the documentation-only contract.

## Task 2: Establish the contact-sheet API with a red test

**Files:**

- Create: `tests/test_contactsheet.py`
- Create: `coverforge/contactsheet.py`

Write a direct integration test that imports the new module, creates three
synthetic source images, writes the packet, and asserts the exact two output
names, deterministic sheet geometry, HTML index content, and absence of the
temporary source path. Run it before production code so collection fails on
the missing module.

Implement only enough to make this test pass: typed result/entry objects,
positive layout validation, composition using `imageops.normalise()` and
`ImageOps.contain()`, a JPEG write, and an offline HTML index with escaped
filename/dimension rows.

## Task 3: Close the output-containment and dry-run gaps

**Files:**

- Modify: `tests/test_contactsheet.py`
- Modify: `coverforge/contactsheet.py`

First add a failing test that asks for an output inside a source-image parent.
Then add the parent-root containment check and assert that no output directory
appears. Add a second test for dry-run planning with no write. Keep all output
writes after successful image composition.

## Task 4: Wire the user-facing command

**Files:**

- Modify: `coverforge/cli.py`
- Modify: `tests/test_build_and_cli.py`

Add `coverforge contact-sheet INPUT... -o OUTPUT` with optional `--title`,
`--columns`, `--cell-size`, `--background`, `--dry-run`, and `--json`. The
command must reuse `collect_masters()` and inspect every image before calling
the new writer. Add CLI tests for ordinary packet output, dry-run, and invalid
option behavior.

## Task 5: Lock down renderer text and public documentation

**Files:**

- Modify: `tests/test_contactsheet.py`
- Modify: `README.md`

Add a hostile-filename test proving the HTML index contains escaped text rather
than active markup. Document the one-command batch-review workflow, exact two
outputs, fresh-directory rule, and local-review boundary. Review all language
for unsupported platform, rights, approval, or revenue claims.

## Task 6: Verify and publish a reviewable branch

Run the full test suite, compilation, whitespace check, and a fresh
source-distribution/wheel build. Install the wheel in a clean temporary
environment, generate only synthetic artwork, run its installed
`contact-sheet` command, and inspect the two written files. Perform a focused
security diff review for local path containment and HTML text rendering. Commit
in small logical units, push `codex/coverforge-contact-sheet`, and open a
draft PR based on `codex/coverforge-portable-manifest`. Do not merge either
Coverforge PR.
