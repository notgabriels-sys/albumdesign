"""The requirements an album cover is checked against.

Defaults follow the common denominator of the major digital distributors and
streaming platforms (Spotify, Apple Music, DistroKid, CD Baby): a perfectly
square RGB JPEG/PNG, at least 1400x1400 px, ideally 3000x3000 px.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Container formats accepted by essentially every distributor. Pillow reports
# these via ``Image.format``.
DEFAULT_ALLOWED_FORMATS: tuple[str, ...] = ("JPEG", "PNG")


@dataclass(frozen=True)
class Spec:
    """A profile of album-cover requirements.

    Sizes are in pixels, ``max_file_bytes`` in bytes. A dimension below
    ``min_pixels`` is a hard failure; one below ``recommended_pixels`` (but at
    or above the minimum) is a warning.
    """

    min_pixels: int = 1400
    recommended_pixels: int = 3000
    max_pixels: int = 6000
    require_square: bool = True
    allowed_formats: tuple[str, ...] = DEFAULT_ALLOWED_FORMATS
    # Distributors reject CMYK outright; RGB is the safe target. Alpha channels
    # and non-RGB modes (grayscale, palette) are flagged as warnings.
    require_rgb: bool = True
    max_file_bytes: int = 20 * 1024 * 1024  # 20 MB

    #: Human-facing name for the profile, shown in reports.
    name: str = field(default="default")
