"""Turning one master into a full delivery pack."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from . import imageops
from .imageops import Encoded, SourceImage, human_bytes, slugify
from .preflight import ERROR, WARN, Finding, check, cover_scale, worst_level
from .specs import Target


_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_BOUNDARY = (
    "This capture records selected local source facts and emitted delivery-file bytes. "
    "Its SHA-256 values and capture ID identify bytes captured by this local run; "
    "they do not authenticate a creator or tool, establish ownership, rights, approval, "
    "platform acceptance, or release readiness."
)


def manifest_capture_id(payload: Mapping[str, object]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "capture_id"}
    encoded = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"cfp_{hashlib.sha256(encoded).hexdigest()[:20]}"


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
            "skipped": [{"target": t.key, "reason": reason} for t, reason in self.skipped],
            "findings": [f.as_dict() for f in self.findings],
        }


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
    """Write a delivery file, refusing to follow a symlink that is already there.

    Building into an existing directory is a supported flow, so the directory
    can hold entries this build did not create. A plain write follows a symlink,
    which let a planted link redirect a delivery file anywhere the user could
    write, while the manifest still recorded it as part of the pack. O_NOFOLLOW
    fails on the link itself instead.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise imageops.ImageError(
                f"{path} is a symlink; refusing to write through it. "
                "Remove it or build into a clean directory."
            ) from None
        raise imageops.ImageError(f"could not write {path}: {exc}") from None
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        raise imageops.ImageError(f"could not write {path}: {exc}") from None


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
    if Path(slug).is_absolute() or "/" in slug or "\\" in slug:
        raise ValueError("slug must not be an absolute path or contain path separators")
    findings = check(src, targets, flatten_colour, allow_upscale)
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
    result = BuildResult(source=src, slug=slug, out_dir=out_dir, findings=findings)

    renderable, skipped = plan(src, targets, findings, allow_upscale)
    result.skipped.extend(skipped)
    result.planned = list(renderable)

    if not renderable or dry_run:
        return result

    # Read the master once, then hash and decode the same bytes. Hashing a
    # separate read would let source.sha256 describe a file that was never
    # rendered if the master changed underneath us mid-build.
    try:
        raw = src.path.read_bytes()
    except OSError as exc:
        raise imageops.ImageError(f"could not read {src.path}: {exc}") from None
    result.source_sha256 = hashlib.sha256(raw).hexdigest()

    # Decode and colour-manage once, then resize per target.
    colour_notes: list[str] = []
    normalised = imageops.normalise(
        src.path, flatten_colour, data=raw, notes=colour_notes
    )
    for note in colour_notes:
        result.findings.append(Finding(WARN, "colour-transform-degraded", note))
    out_dir.mkdir(parents=True, exist_ok=True)

    for target in renderable:
        rendered = imageops.render(normalised, target)
        encoded: Encoded = imageops.encode(rendered, target)
        path = out_dir / output_name(slug, target)
        write_new_bytes(path, encoded.data)
        result.outputs.append(
            Output(
                target=target,
                path=path,
                bytes_written=encoded.size,
                quality=encoded.quality,
                over_cap=encoded.over_cap,
                sha256=hashlib.sha256(encoded.data).hexdigest(),
            )
        )

    _write_manifest(result)
    _write_delivery_note(result)
    return result


def _write_manifest(result: BuildResult) -> None:
    payload = portable_manifest_payload(result)
    (result.out_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_delivery_note(result: BuildResult) -> None:
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
    (result.out_dir / "DELIVERY.md").write_text("\n".join(lines), encoding="utf-8")


def summarise(results: list[BuildResult]) -> str:
    written = sum(len(r.outputs) for r in results)
    skipped = sum(len(r.skipped) for r in results)
    worst = worst_level([f for r in results for f in r.findings])
    parts = [f"{written} file{'s' if written != 1 else ''} written"]
    if skipped:
        parts.append(f"{skipped} target{'s' if skipped != 1 else ''} skipped")
    parts.append(f"worst finding: {worst}")
    return ", ".join(parts)
