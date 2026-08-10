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


# Named presets for specific distributors/platforms. The ``default`` profile is
# the safe common denominator; the others encode a platform's own published
# floors (e.g. Apple Music treats 3000x3000 as a hard minimum, Spotify accepts
# down to 640x640). Sources drift over time, so these are convenient starting
# points, not a substitute for a platform's current spec page.
PROFILES: dict[str, Spec] = {
    "default": Spec(name="default"),
    "apple": Spec(name="apple", min_pixels=3000, recommended_pixels=3000),
    "spotify": Spec(name="spotify", min_pixels=640, recommended_pixels=3000),
    "distrokid": Spec(name="distrokid", min_pixels=1400, recommended_pixels=3000),
    "bandcamp": Spec(name="bandcamp", min_pixels=1400, recommended_pixels=3000),
}

#: The default profile name used when none is requested.
DEFAULT_PROFILE = "default"


def get_profile(name: str) -> Spec:
    """Return the :class:`Spec` for a named profile.

    Raises :class:`KeyError` with a helpful message for an unknown name.
    """
    try:
        return PROFILES[name]
    except KeyError:
        available = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown profile {name!r}; choose from: {available}") from None
