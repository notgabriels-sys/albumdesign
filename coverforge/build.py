"""Turning one master into a full delivery pack."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from . import imageops
from .imageops import Encoded, SourceImage, human_bytes, slugify
from .preflight import ERROR, WARN, Finding, check, cover_scale, worst_level
from .specs import MAX_SELECTED_TARGETS, Target, validate_targets


MANIFEST_SCHEMA_VERSION = 1
MAX_MANIFEST_FILE_BYTES = 1_000_000
MAX_MANIFEST_FINDINGS = 256
MAX_MANIFEST_FINDING_CODE_LENGTH = 128
MAX_MANIFEST_FINDING_MESSAGE_LENGTH = 2_048
MAX_SLUG_LENGTH = 120
MAX_EXISTING_BUNDLE_ENTRIES = 4_096
MANIFEST_BOUNDARY = (
    "This capture records selected local source facts and emitted delivery-file bytes. "
    "Its SHA-256 values and capture ID identify bytes captured by this local run; "
    "they do not authenticate a creator or tool, establish ownership, rights, approval, "
    "platform acceptance, or release readiness."
)
_PORTABLE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def is_portable_slug(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_SLUG_LENGTH
        and _PORTABLE_SLUG.fullmatch(value) is not None
    )


def manifest_capture_id(payload: Mapping[str, object]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "capture_id"}
    encoded = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"cfp_{hashlib.sha256(encoded).hexdigest()[:20]}"


def _validate_manifest_findings(findings: list[Finding]) -> None:
    if len(findings) > MAX_MANIFEST_FINDINGS:
        raise ValueError(
            f"portable manifest findings exceed {MAX_MANIFEST_FINDINGS} entries"
        )
    for finding in findings:
        if not isinstance(finding.code, str) or not finding.code:
            raise ValueError("portable manifest finding code must be non-empty text")
        if len(finding.code) > MAX_MANIFEST_FINDING_CODE_LENGTH:
            raise ValueError("portable manifest finding code is too long")
        if not isinstance(finding.message, str) or not finding.message:
            raise ValueError("portable manifest finding message must be non-empty text")
        if len(finding.message) > MAX_MANIFEST_FINDING_MESSAGE_LENGTH:
            raise ValueError("portable manifest finding message is too long")


@dataclass
class Output:
    target: Target
    path: Path
    bytes_written: int
    quality: int
    over_cap: bool
    sha256: str

    def as_dict(self) -> dict:
        return {
            "target": self.target.key,
            "name": self.target.name,
            "file": self.path.name,
            "dimensions": self.target.dimensions,
            "format": self.target.format,
            "quality": self.quality,
            "bytes": self.bytes_written,
            "size": human_bytes(self.bytes_written),
            "over_size_cap": self.over_cap,
        }

    def as_manifest_dict(self) -> dict:
        return {**self.as_dict(), "sha256": self.sha256}


@dataclass
class BuildResult:
    source: SourceImage
    slug: str
    out_dir: Path
    outputs: list[Output] = field(default_factory=list)
    skipped: list[tuple[Target, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    source_sha256: str | None = None
    # What a build would write. Populated even on a dry run, which otherwise
    # had nothing to report despite --dry-run promising to report it.
    planned: list[Target] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.skipped and not any(o.over_cap for o in self.outputs)

    def as_dict(self) -> dict:
        return {
            "master": str(self.source.path),
            "master_dimensions": self.source.dimensions,
            "slug": self.slug,
            "out_dir": str(self.out_dir),
            "outputs": [o.as_dict() for o in self.outputs],
            "planned": [
                {
                    "target": target.key,
                    "name": target.name,
                    "file": output_name(self.slug, target),
                    "dimensions": target.dimensions,
                    "format": target.format,
                }
                for target in self.planned
            ],
            "skipped": [{"target": t.key, "reason": reason} for t, reason in self.skipped],
            "findings": [f.as_dict() for f in self.findings],
        }


def portable_manifest_payload(result: BuildResult) -> dict[str, object]:
    if result.source_sha256 is None:
        raise ValueError("portable manifest requires a captured source digest")
    if len(result.outputs) + len(result.skipped) > MAX_SELECTED_TARGETS:
        raise ValueError(
            "portable manifest target inventory exceeds "
            f"{MAX_SELECTED_TARGETS} entries"
        )
    _validate_manifest_findings(result.findings)

    payload: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_by": "coverforge",
        "boundary": MANIFEST_BOUNDARY,
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


def plan(
    src: SourceImage,
    targets: list[Target],
    findings: list[Finding],
    allow_upscale: bool = False,
) -> tuple[list[Target], list[tuple[Target, str]]]:
    """Split targets into what a build would render and what it would skip.

    Both `build` and the `check` report call this, so the two can never
    disagree about whether a target is reachable. They used to decide
    separately, and `check` counted upscale-skipped targets as clear while
    `build` skipped them.
    """
    blocking = {f.target for f in findings if f.level == ERROR and f.target}
    renderable: list[Target] = []
    skipped: list[tuple[Target, str]] = []
    for target in targets:
        if target.key in blocking:
            reason = next(
                f.message for f in findings if f.target == target.key and f.level == ERROR
            )
            skipped.append((target, reason))
            continue
        if not allow_upscale and cover_scale(src, target) > 1.0001:
            skipped.append((target, "would upscale the master; pass --allow-upscale to force"))
            continue
        renderable.append(target)
    return renderable, skipped


def output_name(slug: str, target: Target) -> str:
    return f"{slug}--{target.key}--{target.dimensions}.{target.extension}"


def write_new_bytes(path: Path, data: bytes) -> None:
    """Atomically replace one regular delivery file without following links.

    Building into an existing directory is a supported flow, so the directory
    can hold entries this build did not create. Writing through the destination
    directly follows symbolic links, mutates every name of a hard-linked file,
    and exposes a partial file if encoding or I/O fails. A same-directory,
    exclusively created temporary file followed by os.replace avoids all three.
    """
    existing_mode: int | None = None
    try:
        destination_stat = path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise imageops.ImageError(f"could not inspect {path}: {exc}") from None
    else:
        if stat.S_ISLNK(destination_stat.st_mode):
            raise imageops.ImageError(
                f"{path} is a symlink; refusing to write through it. "
                "Remove it or build into a clean directory."
            )
        if not stat.S_ISREG(destination_stat.st_mode):
            raise imageops.ImageError(
                f"{path} is not a regular file; refusing to replace it. "
                "Remove it or build into a clean directory."
            )
        existing_mode = stat.S_IMODE(destination_stat.st_mode)

    temporary: Path | None = None
    fd: int | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=".coverforge-", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(fd)
        completed_fd = fd
        fd = None
        os.close(completed_fd)
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise imageops.ImageError(f"could not write {path}: {exc}") from None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _check_existing_bundle_inventory(out_dir: Path, expected_names: set[str]) -> None:
    """Refuse a build that would leave its own resulting bundle unverifiable."""
    if out_dir.is_symlink():
        raise imageops.ImageError(
            f"output directory is a symlink: {out_dir}. Use its resolved path "
            "or a clean directory."
        )
    if not out_dir.exists():
        return
    if not out_dir.is_dir():
        raise imageops.ImageError(f"output path is not a directory: {out_dir}")

    children: list[Path] = []
    try:
        with os.scandir(out_dir) as iterator:
            for entry in iterator:
                if len(children) >= MAX_EXISTING_BUNDLE_ENTRIES:
                    raise imageops.ImageError(
                        f"{out_dir} contains more than "
                        f"{MAX_EXISTING_BUNDLE_ENTRIES} directory entries; "
                        "use a clean output directory"
                    )
                children.append(Path(entry.path))
    except OSError as exc:
        raise imageops.ImageError(f"could not inspect {out_dir}: {exc}") from None

    stale: list[str] = []
    for child in children:
        if child.is_symlink():
            if child.name in expected_names:
                raise imageops.ImageError(
                    f"{child} is a symlink; refusing to write through it. "
                    "Remove it or build into a clean directory."
                )
            continue
        try:
            child_stat = child.stat(follow_symlinks=False)
        except OSError as exc:
            raise imageops.ImageError(f"could not inspect {child}: {exc}") from None
        if child.name in expected_names:
            if not stat.S_ISREG(child_stat.st_mode):
                raise imageops.ImageError(
                    f"{child} is not a regular file; refusing to replace it. "
                    "Remove it or build into a clean directory."
                )
        elif stat.S_ISREG(child_stat.st_mode):
            stale.append(child.name)

    if stale:
        preview = ", ".join(sorted(stale)[:6])
        if len(stale) > 6:
            preview += " ..."
        raise imageops.ImageError(
            f"{out_dir} contains {len(stale)} regular file(s) the new manifest "
            f"would not declare: {preview}. Use a clean output directory."
        )


def _commit_staged_bundle(
    stage_dir: Path, out_dir: Path, names: list[str]
) -> None:
    """Publish every staged file, restoring the previous bundle on failure."""
    created_out_dir = not out_dir.exists()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise imageops.ImageError(f"could not create {out_dir}: {exc}") from None

    expected_names = set(names)
    _check_existing_bundle_inventory(out_dir, expected_names)
    backup_dir = stage_dir / ".backup"

    try:
        backup_dir.mkdir()
        for name in names:
            staged_path = stage_dir / name
            destination = out_dir / name
            try:
                destination_stat = destination.lstat()
            except FileNotFoundError:
                destination_stat = None
            if destination_stat is not None:
                if not stat.S_ISREG(destination_stat.st_mode):
                    raise imageops.ImageError(
                        f"{destination} is not a regular file; refusing to replace it"
                    )
                os.chmod(staged_path, stat.S_IMODE(destination_stat.st_mode))
                backup_path = backup_dir / name
                os.replace(destination, backup_path)
            os.replace(staged_path, destination)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for name in reversed(names):
            staged_path = stage_dir / name
            destination = out_dir / name
            backup_path = backup_dir / name
            try:
                if backup_path.exists() or backup_path.is_symlink():
                    os.replace(backup_path, destination)
                elif not staged_path.exists() and not staged_path.is_symlink():
                    destination.unlink()
            except FileNotFoundError:
                pass
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if created_out_dir:
            try:
                out_dir.rmdir()
            except OSError:
                pass
        if rollback_errors:
            raise imageops.ImageError(
                "bundle publication failed and rollback was incomplete: "
                + "; ".join(rollback_errors[:3])
            ) from exc
        if isinstance(exc, OSError):
            raise imageops.ImageError(
                f"could not publish complete bundle {out_dir}: {exc}"
            ) from None
        raise


def build(
    src: SourceImage,
    targets: list[Target],
    out_dir: Path,
    slug: str | None = None,
    flatten_colour: str = "#ffffff",
    allow_upscale: bool = False,
    dry_run: bool = False,
) -> BuildResult:
    """Render every target from one master, skipping the ones that can't be met."""
    slug = slug or slugify(src.path.stem)
    if not is_portable_slug(slug):
        raise ValueError(
            "slug must start with a letter or digit and use only letters, digits, '.', '_' or '-'"
        )
    validate_targets(targets)
    raw: bytes | None = None
    captured_src = src
    if not dry_run:
        # All source facts, the digest and rendered pixels must describe one
        # immutable read. The file may change after the caller inspected it.
        try:
            raw = src.path.read_bytes()
        except OSError as exc:
            raise imageops.ImageError(f"could not read {src.path}: {exc}") from None
        captured_src = imageops.inspect(src.path, data=raw)

    findings = check(captured_src, targets, flatten_colour, allow_upscale)
    # imageops builds the sRGB profile once at import and _encode_once embeds it
    # only `if SRGB_BYTES`. When ImageCms cannot create one, that test silently
    # skips, so every output shipped untagged and the build reported no warning
    # at all: a clean run whose files were not what the run implies. Untagged
    # artwork is interpreted differently from platform to platform, and this
    # repo's byte-reproducibility guarantee rests on that profile being present
    # with its timestamp zeroed. A conversion that did not happen is a warning
    # that says so, never a silent success.
    if imageops.SRGB_BYTES is None:
        findings.append(
            Finding(
                WARN,
                "srgb-profile-unavailable",
                "no sRGB profile could be built here, so these files ship untagged. "
                "Colour will drift between platforms and the output hashes will not "
                "match a tagged build. Check that Pillow has working ImageCms.",
            )
        )
    result = BuildResult(
        source=captured_src, slug=slug, out_dir=out_dir, findings=findings
    )

    renderable, skipped = plan(captured_src, targets, findings, allow_upscale)
    result.skipped.extend(skipped)
    result.planned = list(renderable)

    if not renderable or dry_run:
        return result

    assert raw is not None
    expected_names = {
        output_name(slug, target) for target in renderable
    } | {"manifest.json", "DELIVERY.md"}
    _check_existing_bundle_inventory(out_dir, expected_names)
    result.source_sha256 = hashlib.sha256(raw).hexdigest()

    # Decode and colour-manage once, then resize per target.
    colour_notes: list[str] = []
    normalised = imageops.normalise(
        captured_src.path, flatten_colour, data=raw, notes=colour_notes
    )
    for note in colour_notes:
        result.findings.append(Finding(WARN, "colour-transform-degraded", note))
    try:
        _validate_manifest_findings(result.findings)
    except ValueError as exc:
        raise imageops.ImageError(str(exc)) from None
    try:
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(
            tempfile.mkdtemp(prefix=".coverforge-build-", dir=out_dir.parent)
        )
    except OSError as exc:
        raise imageops.ImageError(f"could not stage build for {out_dir}: {exc}") from None

    try:
        for target in renderable:
            rendered = imageops.render(normalised, target)
            encoded: Encoded = imageops.encode(rendered, target)
            final_path = out_dir / output_name(slug, target)
            write_new_bytes(stage_dir / final_path.name, encoded.data)
            result.outputs.append(
                Output(
                    target=target,
                    path=final_path,
                    bytes_written=encoded.size,
                    quality=encoded.quality,
                    over_cap=encoded.over_cap,
                    sha256=hashlib.sha256(encoded.data).hexdigest(),
                )
            )
        _write_manifest(result, directory=stage_dir)
        _write_delivery_note(result, directory=stage_dir)
        commit_names = [output.path.name for output in result.outputs]
        commit_names.extend(["DELIVERY.md", "manifest.json"])
        _commit_staged_bundle(stage_dir, out_dir, commit_names)
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
    return result


def _write_manifest(result: BuildResult, *, directory: Path | None = None) -> None:
    payload = portable_manifest_payload(result)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_MANIFEST_FILE_BYTES:
        raise imageops.ImageError(
            f"manifest exceeds the {MAX_MANIFEST_FILE_BYTES}-byte safety limit"
        )
    write_new_bytes(
        (directory or result.out_dir) / "manifest.json",
        encoded,
    )


def _write_delivery_note(result: BuildResult, *, directory: Path | None = None) -> None:
    lines = [
        f"# {result.slug}",
        "",
        f"Master: `{result.source.path.name}` ({result.source.dimensions}, "
        f"{result.source.mode}, {human_bytes(result.source.file_bytes)})",
        "",
        "| Target | File | Size | Format | Weight |",
        "| --- | --- | --- | --- | --- |",
    ]
    for output in result.outputs:
        fmt = output.target.format.upper()
        if output.target.format == "jpeg":
            fmt += f" q{output.quality}"
        lines.append(
            f"| {output.target.name} | `{output.path.name}` | {output.target.dimensions} "
            f"| {fmt} | {human_bytes(output.bytes_written)} |"
        )

    if result.skipped:
        lines += ["", "## Not produced", ""]
        lines += [f"- **{t.name}** - {reason}" for t, reason in result.skipped]

    notes = [f for f in result.findings if f.level != "info"]
    if notes:
        lines += ["", "## Warnings", ""]
        lines += [f"- {f.message}" for f in notes]

    lines += [
        "",
        "---",
        "",
        "All files are flattened 8-bit sRGB with a baseline (non-progressive) JPEG encode.",
        "Platform requirements drift - check `coverforge/targets.toml` against your",
        "distributor before delivery.",
        "",
    ]
    write_new_bytes(
        (directory or result.out_dir) / "DELIVERY.md",
        "\n".join(lines).encode("utf-8"),
    )


def summarise(results: list[BuildResult]) -> str:
    written = sum(len(r.outputs) for r in results)
    skipped = sum(len(r.skipped) for r in results)
    worst = worst_level([f for r in results for f in r.findings])
    parts = [f"{written} file{'s' if written != 1 else ''} written"]
    if skipped:
        parts.append(f"{skipped} target{'s' if skipped != 1 else ''} skipped")
    parts.append(f"worst finding: {worst}")
    return ", ".join(parts)
