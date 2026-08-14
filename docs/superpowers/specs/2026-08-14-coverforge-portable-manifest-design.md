# Coverforge portable manifest capture

## Goal

Turn Coverforge's existing `manifest.json` into a portable, deterministic
delivery-capture record that can be safely shared with a label, designer,
artist, or later companion tool without exposing the operator's absolute paths.

## Problem

The current build manifest includes the absolute master path and output
directory, while its delivery entries contain no content hashes. That makes it
unsuitable as portable handoff evidence and unsafe to use as a future
Releaseforge companion input.

## Decision

Keep the filename `manifest.json`, but define its first explicit schema as a
new versioned capture format. This is a deliberate prototype-format change;
there is no promise of compatibility with the previous unversioned JSON.

The build command's `--json` stdout remains owner-local and keeps its current
`master` and `out_dir` fields. Only the written delivery manifest adopts the
portable schema. This preserves terminal ergonomics without placing paths into
the document likely to be shared.

## Manifest contract

Every non-dry build that produces at least one delivery output writes exactly
one `manifest.json` with these root fields:

- `schema_version`: integer `1`.
- `generated_by`: string `"coverforge"`.
- `boundary`: a fixed explanation that this is a local byte capture, not a
  signature, source-authentication claim, rights determination, approval,
  platform acceptance, or release-readiness verdict.
- `capture_id`: deterministic `cfp_` plus the first 20 hexadecimal characters
  of SHA-256 over canonical JSON content with `capture_id` excluded.
- `slug`: the existing output slug.
- `source`: only `sha256`, `bytes`, `dimensions`, `mode`, and `format` facts.
  It never contains a source name, input path, relative path, or output path.
- `outputs`: existing portable delivery facts plus a SHA-256 for every emitted
  delivery file.
- `skipped` and `findings`: the existing bounded build results.

The manifest does not contain `master`, `out_dir`, absolute paths, timestamps,
or source-media bytes. Source and output hashes identify the specific local
bytes captured by the build, but do not prove authorship, ownership, source
tool provenance, or that a recipient currently has the same files.

## Implementation shape

`coverforge.build` will retain its current owner-local `BuildResult.as_dict()`
for CLI JSON. It will add a dedicated portable manifest-payload function and a
canonical `manifest_capture_id` helper. `Output` gains a SHA-256 value computed
from the exact encoded bytes before they are written. Source hashing uses a
streaming standard-library helper while building the manifest, avoiding a
second in-memory copy of an image file.

No new runtime dependency, account, upload, network request, subprocess,
deletion, rename, or overwrite policy is introduced. Existing target selection,
dry-run behavior, exit codes, and delivery filenames stay unchanged.

## Testing and acceptance criteria

The build tests must prove that a real generated manifest:

1. has schema version `1` and a recomputable deterministic `capture_id`;
2. contains matching SHA-256 values for the source and every emitted file;
3. contains no temporary-directory, source, or output path string;
4. still describes existing outputs, skipped targets, and findings; and
5. leaves owner-local CLI JSON behavior intact.

The full suite must pass under Python 3.13, the declared support floor is
Python 3.11+, and a freshly built wheel must generate and validate a portable
manifest through the installed `coverforge` command.

## Documentation

Replace the empty repository README with concise, evidence-bounded install,
check, build, output, and manifest instructions. It must warn that delivery
requirements drift and should be checked against the real distributor or
destination; it must not promise platform compliance.
