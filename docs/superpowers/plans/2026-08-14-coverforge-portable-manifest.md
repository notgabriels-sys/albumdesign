# Coverforge Portable Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every non-dry Coverforge build emit a versioned, path-free,
hash-bound artwork-delivery manifest that is safe to share as local evidence.

**Architecture:** Keep `BuildResult.as_dict()` as the owner-local command-line
view, including its useful absolute input and output locations. Add a separate
portable-manifest payload in `coverforge.build`: it records only source facts,
delivery facts, SHA-256 digests, and a deterministic capture identifier. The
written `manifest.json` uses that payload, while terminal JSON remains unchanged.

**Tech Stack:** Python 3.11+, standard-library `hashlib` and `json`, Pillow,
pytest, Hatchling.

## Global Constraints

- The repository's supported Python floor remains exactly `>=3.11`.
- Add no runtime dependency, account, upload, network request, subprocess,
  deletion, rename, or overwrite policy.
- Preserve existing target selection, exit codes, dry-run behavior, delivery
  filenames, and owner-local `BuildResult.as_dict()` semantics.
- The written `manifest.json` must never contain the source path, source name,
  output directory, absolute path, timestamp, or source-media bytes.
- Every source/output SHA-256 identifies local bytes only; it is not a
  signature, source-authentication statement, ownership/rights decision,
  approval, platform-acceptance, or release-readiness verdict.
- Do not stage or alter the user's untracked `artwork/` directory.

---

## File structure

- `coverforge/build.py` owns rendering, output records, portable-manifest
  construction, SHA-256 calculation, and the file write.
- `tests/test_build_and_cli.py` owns integration coverage using actual Pillow
  fixture files and on-disk generated delivery files.
- `README.md` owns concise operator instructions and the evidence boundary.
- `docs/superpowers/specs/2026-08-14-coverforge-portable-manifest-design.md`
  records the stable product decision for future companion-tool work.

### Task 1: Record the approved capture contract

**Files:**
- Create: `docs/superpowers/specs/2026-08-14-coverforge-portable-manifest-design.md`
- Create: `docs/superpowers/plans/2026-08-14-coverforge-portable-manifest.md`

**Interfaces:**
- Consumes: existing Coverforge `build()` behavior and `manifest.json` output.
- Produces: the contract for `portable_manifest_payload()` and the exact test
  boundary used in Task 2.

- [ ] **Step 1: Review the design against the existing implementation**

Confirm `BuildResult.as_dict()` includes `master` and `out_dir`, and confirm
`_write_manifest()` currently serializes that owner-local structure. Confirm
that `Output.as_dict()` lacks a digest and that no existing manifest schema
version is promised.

- [ ] **Step 2: Check the design document for unbounded claims**

Run: `rg -n -i 'upload|network|platform compliance|approval|signature|rights|revenue' docs/superpowers/specs/2026-08-14-coverforge-portable-manifest-design.md`

Expected: any references to those concepts are explicit limitations, not a
claim that Coverforge performs them.

- [ ] **Step 3: Commit the design record before feature code**

Run:

```bash
git add docs/superpowers/specs/2026-08-14-coverforge-portable-manifest-design.md \
  docs/superpowers/plans/2026-08-14-coverforge-portable-manifest.md
git diff --cached --check
git commit -m "docs: define portable coverforge manifest"
```

Expected: one documentation-only commit; `artwork/` remains untracked and
unstaged.

### Task 2: Produce a path-free, hash-bound manifest

**Files:**
- Modify: `coverforge/build.py:1-131`
- Modify: `tests/test_build_and_cli.py:1-71`

**Interfaces:**
- Consumes: `BuildResult`, `Output`, `SourceImage`, and the real PNG fixture
  provided by `master`.
- Produces: `manifest_capture_id(payload: Mapping[str, object]) -> str`,
  `portable_manifest_payload(result: BuildResult) -> dict[str, object]`, an
  `Output.sha256: str` field, and a written `manifest.json` with schema version
  `1`.

- [ ] **Step 1: Write the failing integration test**

Add this test after `test_build_writes_manifest_and_delivery_note`; it exercises
the real build and real files, so no mock is required. The production break it
catches is a written manifest that leaks local paths, lacks byte hashes, or
uses a capture identifier not bound to its visible content.

```python
import hashlib


def test_written_manifest_is_portable_while_build_result_remains_owner_local(master, tmp_path):
    out = tmp_path / "delivery"
    source = inspect(master)
    result = build(source, ALL_TARGETS, out_dir=out, slug="lof001")

    raw = (out / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(raw)

    assert manifest.get("schema_version") == 1
    assert manifest["generated_by"] == "coverforge"
    assert manifest["slug"] == "lof001"
    assert str(tmp_path) not in raw
    assert str(master) not in raw
    assert master.name not in raw
    assert "master" not in manifest
    assert "out_dir" not in manifest
    assert set(manifest["source"]) == {"sha256", "bytes", "dimensions", "mode", "format"}
    assert manifest["source"] == {
        "sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "bytes": master.stat().st_size,
        "dimensions": source.dimensions,
        "mode": source.mode,
        "format": source.file_format,
    }
    for output in manifest["outputs"]:
        rendered = out / output["file"]
        assert output["sha256"] == hashlib.sha256(rendered.read_bytes()).hexdigest()

    capture_payload = {key: value for key, value in manifest.items() if key != "capture_id"}
    canonical = json.dumps(
        capture_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert manifest["capture_id"] == f"cfp_{hashlib.sha256(canonical).hexdigest()[:20]}"

    owner_local = result.as_dict()
    assert owner_local["master"] == str(master)
    assert owner_local["out_dir"] == str(out)
```

- [ ] **Step 2: Run the test to verify the expected red state**

Run:

```bash
/var/folders/pc/9qf6qbqx0931ywj0v8v4srf00000gn/T/coverforge-manifest-venv.XXXXXX.xbNw1uwUwf/bin/python \
  -m pytest tests/test_build_and_cli.py::test_written_manifest_is_portable_while_build_result_remains_owner_local -q
```

Expected: one assertion failure because the existing unversioned manifest has
no `schema_version` field. Do not write production code until this failure is
observed.

- [ ] **Step 3: Add the minimal portable-manifest implementation**

In `coverforge/build.py`, import `hashlib` and `Mapping`. Add these module
constants and helpers above `Output`:

```python
_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_BOUNDARY = (
    "This capture records selected local source facts and emitted delivery-file bytes. "
    "Its SHA-256 values and capture ID identify bytes captured by this local run; "
    "they do not authenticate a creator or tool, establish ownership, rights, approval, "
    "platform acceptance, or release readiness."
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_capture_id(payload: Mapping[str, object]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "capture_id"}
    encoded = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"cfp_{hashlib.sha256(encoded).hexdigest()[:20]}"
```

Extend `Output` with `sha256: str` and add `as_manifest_dict()` that returns
`{**self.as_dict(), "sha256": self.sha256}`. Extend `BuildResult` with
`source_sha256: str | None = None` and leave `as_dict()` unchanged.

Inside `build()`, after confirming the operation is neither dry nor entirely
skipped, set `result.source_sha256 = _sha256_file(src.path)`. For each target,
calculate `hashlib.sha256(encoded.data).hexdigest()` before writing the bytes
and store it in the new `Output.sha256` field.

Add this payload builder below `BuildResult`:

```python
def portable_manifest_payload(result: BuildResult) -> dict[str, object]:
    if result.source_sha256 is None:
        raise ValueError("portable manifest requires a captured source digest")

    payload: dict[str, object] = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "generated_by": "coverforge",
        "boundary": _MANIFEST_BOUNDARY,
        "slug": result.slug,
        "source": {
            "sha256": result.source_sha256,
            "bytes": result.source.file_bytes,
            "dimensions": result.source.dimensions,
            "mode": result.source.mode,
            "format": result.source.file_format,
        },
        "outputs": [output.as_manifest_dict() for output in result.outputs],
        "skipped": [{"target": target.key, "reason": reason} for target, reason in result.skipped],
        "findings": [finding.as_dict() for finding in result.findings],
    }
    payload["capture_id"] = manifest_capture_id(payload)
    return payload
```

Replace `_write_manifest()` so it serializes only
`portable_manifest_payload(result)` with `ensure_ascii=False`, `indent=2`, and
`sort_keys=True`. Do not alter `_write_delivery_note()` or `BuildResult.as_dict()`.

- [ ] **Step 4: Run the focused test to verify green**

Run:

```bash
/var/folders/pc/9qf6qbqx0931ywj0v8v4srf00000gn/T/coverforge-manifest-venv.XXXXXX.xbNw1uwUwf/bin/python \
  -m pytest tests/test_build_and_cli.py::test_written_manifest_is_portable_while_build_result_remains_owner_local -q
```

Expected: `1 passed`; the test verifies actual generated images and the
canonical ID independently, without using production helpers to calculate its
expectation.

- [ ] **Step 5: Run the full test suite before documentation changes**

Run:

```bash
/var/folders/pc/9qf6qbqx0931ywj0v8v4srf00000gn/T/coverforge-manifest-venv.XXXXXX.xbNw1uwUwf/bin/python \
  -m pytest -q
```

Expected: all existing tests plus the new integration test pass under Python
3.13.

### Task 3: Document the usable local workflow and evidence boundary

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `coverforge targets`, `coverforge check`, `coverforge build`,
  `manifest.json`, and `DELIVERY.md` as actually implemented in Task 2.
- Produces: a concise operator guide that does not make distributor,
  compliance, approval, or revenue claims.

- [ ] **Step 1: Replace the empty README with grounded instructions**

Write these sections in order:

```markdown
# Coverforge

Local preflight and delivery-pack builder for release artwork.

## Install

## Use

## What a build writes

## Portable manifest boundary

## Target definitions
```

Include Python `3.11+`, editable install with `.[dev]`, one `targets` command,
one report-only `check` command, one `build` command, and a `--dry-run` example.
Explain that a build writes delivery files, `DELIVERY.md`, and `manifest.json`;
the manifest has no local paths, provides source/output SHA-256 values and
`capture_id`, and is only a local byte capture. State clearly that the tool
does not upload files, determine rights, validate external acceptance, or
guarantee platform compliance. State that `targets.toml` is editable and the
operator must verify current destination requirements before delivery.

- [ ] **Step 2: Review public-facing language for overclaiming**

Run:

```bash
rg -n -i 'guarantee|compliant|approved|accepted|ready|revenue|upload' README.md
```

Expected: any matching wording is an explicit limitation, never a product
promise.

- [ ] **Step 3: Commit the feature and its documentation**

Run:

```bash
git add coverforge/build.py tests/test_build_and_cli.py README.md
git diff --cached --check
git commit -m "feat: add portable artwork manifest capture"
```

Expected: one focused feature commit; `artwork/` remains untracked and
unstaged.

### Task 4: Verify the distributable artifact and publish a reviewable branch

**Files:**
- Verify: the committed source tree and built wheel.

**Interfaces:**
- Consumes: the commit from Task 3 and the Hatchling build configuration.
- Produces: fresh test/build/smoke evidence and a draft GitHub pull request;
  it never merges the branch.

- [ ] **Step 1: Run source-level verification**

Run:

```bash
/var/folders/pc/9qf6qbqx0931ywj0v8v4srf00000gn/T/coverforge-manifest-venv.XXXXXX.xbNw1uwUwf/bin/python -m pytest -q
/var/folders/pc/9qf6qbqx0931ywj0v8v4srf00000gn/T/coverforge-manifest-venv.XXXXXX.xbNw1uwUwf/bin/python -m compileall -q coverforge
git diff --check
```

Expected: no test failures, no compilation errors, and no whitespace errors.

- [ ] **Step 2: Build and smoke-test an installed wheel**

Install the `build` package only in the disposable Python 3.13 environment,
then create an exact temporary destination and run:

```bash
BUILD_OUTPUT_DIR="$(mktemp -d /private/tmp/coverforge-wheel.XXXXXX)"
/var/folders/pc/9qf6qbqx0931ywj0v8v4srf00000gn/T/coverforge-manifest-venv.XXXXXX.xbNw1uwUwf/bin/python \
  -m build --outdir "$BUILD_OUTPUT_DIR"
```

Create a fresh temporary virtual environment, install the newly built wheel,
generate a synthetic 3000-by-3000 PNG using Pillow, and run its installed
`coverforge build` command with `--only web_thumb --json`. Inspect the emitted
`manifest.json` to prove it has schema version `1`, no temporary path, and
hashes matching the actual master/output bytes. Delete only the exact temporary
directories created for this smoke check after recording the command output.

- [ ] **Step 3: Inspect the final diff and Git state**

Run:

```bash
git status --short --branch
git log --oneline main..HEAD
git diff --check main...HEAD
```

Expected: only the two intended commits are ahead of `main`; any `artwork/`
line remains untracked and absent from both commits.

- [ ] **Step 4: Push and open a draft pull request**

Run:

```bash
git push -u origin codex/coverforge-portable-manifest
gh pr create --draft --base main --head codex/coverforge-portable-manifest \
  --title "feat: add portable Coverforge manifest capture" \
  --body-file /private/tmp/coverforge-portable-manifest-pr.md
```

The pull request body must state the portable schema behavior, tests/build
evidence, evidence boundary, and that merge remains Gabriel's decision. Verify
the resulting pull request is open, draft, and mergeable. Do not merge it.
