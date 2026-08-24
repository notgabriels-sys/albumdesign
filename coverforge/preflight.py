"""Checks that run against a master before anything is exported."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

from .imageops import UNREADABLE_ICC, SourceImage
from .specs import Target

ERROR = "error"
WARN = "warn"
INFO = "info"

_RANK = {INFO: 0, WARN: 1, ERROR: 2}


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    target: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def worst_level(findings: Iterable[Finding]) -> str:
    return max((f.level for f in findings), key=lambda lvl: _RANK[lvl], default=INFO)


def cover_scale(src: SourceImage, target: Target) -> float:
    """Scale factor a cover-fit render applies. >1 means upscaling."""
    if not src.width or not src.height:
        return 0.0
    if target.fit == "pad":
        return min(target.width / src.width, target.height / src.height)
    return max(target.width / src.width, target.height / src.height)


def _retained_fraction(src: SourceImage, target: Target) -> float:
    """Fraction of the master's area that survives a centre crop."""
    if target.fit == "pad" or not src.width or not src.height:
        return 1.0
    scale = cover_scale(src, target)
    if scale <= 0:
        return 1.0
    keep_w = min(src.width, target.width / scale)
    keep_h = min(src.height, target.height / scale)
    return (keep_w * keep_h) / (src.width * src.height)


def check_source(src: SourceImage, targets: list[Target], flatten_colour: str) -> list[Finding]:
    """Checks about the master itself, independent of any one target."""
    findings: list[Finding] = []

    if not src.is_square and any(t.is_square for t in targets):
        findings.append(
            Finding(
                WARN,
                "not-square",
                f"master is {src.dimensions} (not square); square targets will be centre-cropped",
            )
        )

    if src.has_alpha:
        findings.append(
            Finding(
                WARN,
                "alpha",
                f"has transparency; it will be flattened onto {flatten_colour}. "
                "Most stores reject alpha outright, so check the result looks right",
            )
        )

    if src.mode == "CMYK":
        findings.append(
            Finding(
                WARN,
                "cmyk",
                "CMYK master; converting to sRGB will shift colours. Export sRGB from your design tool",
            )
        )
    elif src.mode not in {"RGB", "RGBA", "L", "LA", "P", "PA"}:
        findings.append(Finding(INFO, "mode", f"colour mode {src.mode} will be converted to RGB"))

    if src.is_high_depth:
        findings.append(Finding(INFO, "bit-depth", f"{src.mode} master will be reduced to 8-bit per channel"))

    if src.icc_description is None:
        findings.append(Finding(INFO, "no-icc", "no ICC profile embedded; assuming sRGB"))
    elif src.icc_description == UNREADABLE_ICC:
        # inspect() already failed to parse this profile, and _to_srgb fails on
        # it again for the same reason, falling back to a plain convert. Saying
        # "will be converted to sRGB" here promised a transform that had
        # already been established as impossible, and nothing later corrected
        # it. Colours are taken as they sit, which is worth knowing before a
        # cover goes out.
        findings.append(
            Finding(
                WARN,
                "icc-unreadable",
                "the embedded ICC profile could not be read, so no colour transform "
                "can be applied and the pixels are taken as they are. If this master "
                "is not already sRGB the colours will shift. Re-export it as sRGB.",
            )
        )
    elif "srgb" not in src.icc_description.lower():
        findings.append(
            Finding(INFO, "icc", f"tagged {src.icc_description!r}; will be converted to sRGB")
        )

    if src.exif_orientation != 1:
        findings.append(
            Finding(
                INFO,
                "exif-orientation",
                f"EXIF orientation {src.exif_orientation} will be baked into the pixels",
            )
        )

    if src.is_animated:
        findings.append(Finding(WARN, "animated", "animated source; only the first frame is exported"))

    if src.is_progressive:
        findings.append(
            Finding(INFO, "progressive", "source is a progressive JPEG; exports are written baseline")
        )

    return findings


def check_target(src: SourceImage, target: Target, allow_upscale: bool = False) -> list[Finding]:
    """Checks for one master against one delivery target."""
    if target.min_source and src.short_edge < target.min_source:
        # The target is unreachable, so crop and upscale detail would be noise.
        return [
            Finding(
                ERROR,
                "below-minimum",
                f"master short edge is {src.short_edge}px, under the {target.min_source}px minimum",
                target.key,
            )
        ]

    findings: list[Finding] = []
    scale = cover_scale(src, target)
    if scale > 1.0001:
        suffix = "" if allow_upscale else "; skipped unless --allow-upscale is passed"
        findings.append(
            Finding(
                WARN,
                "upscale",
                f"{src.dimensions} would be upscaled {scale:.2f}x to reach {target.dimensions}{suffix}",
                target.key,
            )
        )

    retained = _retained_fraction(src, target)
    if retained < 0.99:
        findings.append(
            Finding(
                INFO,
                "crop",
                f"centre crop keeps {retained * 100:.0f}% of the master's area",
                target.key,
            )
        )

    return findings


def check(
    src: SourceImage,
    targets: list[Target],
    flatten_colour: str = "#ffffff",
    allow_upscale: bool = False,
) -> list[Finding]:
    findings = check_source(src, targets, flatten_colour)
    for target in targets:
        findings.extend(check_target(src, target, allow_upscale))
    return findings
