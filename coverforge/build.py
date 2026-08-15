"""Turning one master into a full delivery pack."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from . import imageops
from .imageops import Encoded, SourceImage, human_bytes, slugify
from .preflight import ERROR, Finding, check, cover_scale, worst_level
from .specs import Target


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


def output_name(slug: str, target: Target) -> str:
    return f"{slug}--{target.key}--{target.dimensions}.{target.extension}"


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
    result = BuildResult(source=src, slug=slug, out_dir=out_dir, findings=findings)

    blocking = {f.target for f in findings if f.level == ERROR and f.target}
    renderable: list[Target] = []
    for target in targets:
        if target.key in blocking:
            reason = next(
                f.message for f in findings if f.target == target.key and f.level == ERROR
            )
            result.skipped.append((target, reason))
            continue
        if not allow_upscale and cover_scale(src, target) > 1.0001:
            result.skipped.append((target, "would upscale the master; pass --allow-upscale to force"))
            continue
        renderable.append(target)

    if not renderable or dry_run:
        return result

    result.source_sha256 = _sha256_file(src.path)

    # Decode and colour-manage once, then resize per target.
    normalised = imageops.normalise(src.path, flatten_colour)
    out_dir.mkdir(parents=True, exist_ok=True)

    for target in renderable:
        rendered = imageops.render(normalised, target)
        encoded: Encoded = imageops.encode(rendered, target)
        path = out_dir / output_name(slug, target)
        path.write_bytes(encoded.data)
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
