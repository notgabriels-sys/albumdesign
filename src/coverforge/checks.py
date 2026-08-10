"""Run the individual checks that make up a cover validation."""

from __future__ import annotations

import os

from PIL import Image, UnidentifiedImageError

from coverforge.report import Report, Status
from coverforge.spec import Spec


def _format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def check_cover(path: str, spec: Spec | None = None) -> Report:
    """Validate a single cover image and return a :class:`Report`.

    Opening the file is itself the first check: an unreadable or non-image file
    produces a single FAIL result and no further checks are attempted.
    """
    spec = spec or Spec()
    report = Report(path=path, profile=spec.name)

    if not os.path.exists(path):
        report.add("file", Status.FAIL, "no such file")
        return report
    if not os.path.isfile(path):
        report.add("file", Status.FAIL, "not a regular file")
        return report

    file_bytes = os.path.getsize(path)

    try:
        with Image.open(path) as img:
            img.load()
            image_format = img.format
            width, height = img.size
            mode = img.mode
    except UnidentifiedImageError:
        report.add("format", Status.FAIL, "not a recognisable image file")
        return report
    except OSError as exc:
        report.add("file", Status.FAIL, f"could not read image ({exc})")
        return report

    _check_format(report, spec, image_format)
    _check_dimensions(report, spec, width, height)
    _check_color_mode(report, spec, mode)
    _check_file_size(report, spec, file_bytes)

    return report


def _check_format(report: Report, spec: Spec, image_format: str | None) -> None:
    fmt = image_format or "unknown"
    if image_format in spec.allowed_formats:
        report.add("format", Status.PASS, fmt)
    else:
        allowed = ", ".join(spec.allowed_formats)
        report.add("format", Status.FAIL, f"{fmt} is not accepted (use {allowed})")


def _check_dimensions(report: Report, spec: Spec, width: int, height: int) -> None:
    size = f"{width}x{height}"

    if spec.require_square and width != height:
        report.add("square", Status.FAIL, f"{size} is not square")
    elif spec.require_square:
        report.add("square", Status.PASS, size)

    smallest = min(width, height)
    largest = max(width, height)

    if smallest < spec.min_pixels:
        report.add(
            "resolution",
            Status.FAIL,
            f"{size} is below the {spec.min_pixels}px minimum",
        )
    elif smallest < spec.recommended_pixels:
        report.add(
            "resolution",
            Status.WARN,
            f"{size} is below the recommended {spec.recommended_pixels}px",
        )
    elif largest > spec.max_pixels:
        report.add(
            "resolution",
            Status.WARN,
            f"{size} is larger than {spec.max_pixels}px; some platforms reject oversized art",
        )
    else:
        report.add("resolution", Status.PASS, size)


def _check_color_mode(report: Report, spec: Spec, mode: str) -> None:
    if not spec.require_rgb:
        report.add("color", Status.PASS, mode)
        return

    if mode == "RGB":
        report.add("color", Status.PASS, mode)
    elif mode in ("CMYK", "YCbCr", "LAB"):
        report.add("color", Status.FAIL, f"{mode} is not accepted; convert to RGB")
    elif mode == "RGBA":
        report.add("color", Status.WARN, "RGBA has an alpha channel; flatten to RGB")
    elif mode in ("L", "LA", "1"):
        report.add("color", Status.WARN, f"{mode} is grayscale; convert to RGB")
    elif mode == "P":
        report.add("color", Status.WARN, "palette (P) image; convert to RGB")
    else:
        report.add("color", Status.WARN, f"{mode} is not RGB; convert to RGB")


def _check_file_size(report: Report, spec: Spec, file_bytes: int) -> None:
    human = _format_bytes(file_bytes)
    if file_bytes > spec.max_file_bytes:
        report.add(
            "filesize",
            Status.WARN,
            f"{human} exceeds the {_format_bytes(spec.max_file_bytes)} upload limit of some platforms",
        )
    else:
        report.add("filesize", Status.PASS, human)
