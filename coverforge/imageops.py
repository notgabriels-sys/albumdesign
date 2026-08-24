"""Reading, normalising, resizing and encoding artwork."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from .specs import Target

READABLE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".gif"}

# What _icc_description records when a profile will not parse. preflight has
# to recognise this exact value to warn instead of promising a transform that
# cannot happen, so it is named here rather than spelled twice.
UNREADABLE_ICC = "unreadable ICC profile"

ALPHA_MODES = {"RGBA", "LA", "PA"}
HIGH_DEPTH_MODES = {"I", "F", "I;16", "I;16B", "I;16L"}

# Below this, JPEG artefacts start showing on flat gradients, which is most
# techno artwork. If a size cap can't be met by here, say so rather than
# silently shipping mush.
MIN_QUALITY = 55

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class ImageError(Exception):
    """An image could not be read or processed."""


def slugify(value: str) -> str:
    """'Lack of Fate — Untitled #3' -> 'lack-of-fate-untitled-3'."""
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    return _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-") or "artwork"


def human_bytes(count: int | None) -> str:
    """Decimal units, because that is how platforms state their limits."""
    if count is None:
        return "-"
    if count < 1_000:
        return f"{count} B"
    if count < 1_000_000:
        return f"{count / 1_000:.0f} KB"
    return f"{count / 1_000_000:.1f} MB"


@dataclass
class SourceImage:
    """What we know about a master file before touching it."""

    path: Path
    width: int
    height: int
    mode: str
    file_format: str
    file_bytes: int
    has_alpha: bool
    icc_description: str | None
    exif_orientation: int
    is_animated: bool
    is_progressive: bool
    is_high_depth: bool

    @property
    def short_edge(self) -> int:
        return min(self.width, self.height)

    @property
    def is_square(self) -> bool:
        return self.width == self.height

    @property
    def dimensions(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0


def _icc_description(icc: bytes | None) -> str | None:
    if not icc:
        return None
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return (ImageCms.getProfileDescription(profile) or "").strip() or None
    except Exception:
        return UNREADABLE_ICC


# ICC header bytes 24..35 hold the profile's creation date and time. littlecms
# stamps that with the current clock, so a freshly built sRGB profile differs
# between runs by a byte or two. That profile is embedded in every file we
# write, which would make identical builds produce different bytes, different
# output hashes, and a different manifest capture_id one second apart. The
# field is informational, so zero it and keep builds reproducible.
_ICC_DATETIME = slice(24, 36)


# ICC header bytes 24..35 hold the profile's creation date and time. littlecms
# stamps that with the current clock, so a freshly built sRGB profile differs
# between runs by a byte or two. That profile is embedded in every file we
# write, which would make identical builds produce different bytes, different
# output hashes, and a different manifest capture_id one second apart. The
# field is informational, so zero it and keep builds reproducible.
_ICC_DATETIME = slice(24, 36)


def _srgb_profile_bytes() -> bytes | None:
    try:
        raw = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    except Exception:
        return None
    if len(raw) >= _ICC_DATETIME.stop:
        raw[_ICC_DATETIME] = b"\x00" * 12
    return bytes(raw)


SRGB_BYTES = _srgb_profile_bytes()


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in READABLE_SUFFIXES


def inspect(path: Path) -> SourceImage:
    """Read metadata, having confirmed there is an image behind it.

    Every frame after the first is still left alone, but frame zero is
    decoded, because `im.width` and `im.height` come out of the container's
    header and a header will state a size for a file that holds no pixels.
    Measured: a PNG whose IHDR was edited to claim 5000x5000, with the real
    3000x3000 image data left in place, opened cleanly and `coverforge check`
    reported `5000x5000 RGB PNG 33 KB` and `ok 10/10 targets clear`, exit 0,
    on a file no decoder can produce an image from. `im.verify()` is not
    enough: it returned ok on that same file. Only `im.load()` catches it,
    and it costs 40 to 90 ms on a 3000px master.
    """
    try:
        with Image.open(path) as im:
            im.load()
            info = im.info
            exif_orientation = 1
            try:
                exif_orientation = int(im.getexif().get(0x0112, 1) or 1)
            except Exception:
                exif_orientation = 1
            return SourceImage(
                path=path,
                width=im.width,
                height=im.height,
                mode=im.mode,
                file_format=(im.format or "?").lower(),
                file_bytes=path.stat().st_size,
                has_alpha=im.mode in ALPHA_MODES or "transparency" in info,
                icc_description=_icc_description(info.get("icc_profile")),
                exif_orientation=exif_orientation,
                is_animated=getattr(im, "n_frames", 1) > 1,
                is_progressive=bool(info.get("progressive") or info.get("progression")),
                is_high_depth=im.mode in HIGH_DEPTH_MODES,
            )
    except FileNotFoundError:
        raise ImageError(f"file not found: {path}") from None
    except UnidentifiedImageError:
        raise ImageError(f"not a readable image: {path}") from None
    except Image.DecompressionBombError:
        # A header can claim a pixel count far beyond what it could hold.
        # Pillow refuses, and that refusal is an answer about the file, not a
        # crash, so it exits like any other unreadable master.
        raise ImageError(f"image header declares an implausible size: {path}") from None
    except OSError as exc:
        raise ImageError(f"could not read {path}: {exc}") from None


def normalise(
    path: Path,
    flatten_colour: str = "#ffffff",
    *,
    data: bytes | None = None,
    notes: list[str] | None = None,
) -> Image.Image:
    """Open a master and return a flat 8-bit sRGB RGB image.

    Handles EXIF rotation, ICC conversion, CMYK, and alpha flattening, which
    are the four things that quietly change how art looks between your screen
    and a store page.

    Pass ``data`` to decode bytes already read from ``path``. The manifest
    hashes the master, and hashing one read while decoding a second would let
    the recorded digest describe bytes that were never rendered.

    Pass ``notes`` to hear about colour handling that degraded. The sRGB
    transform falls back to a plain convert when a profile will not load or the
    transform fails, which shifts colour, and until this existed the caller had
    no way to learn it had happened.
    """
    source = io.BytesIO(data) if data is not None else path
    try:
        with Image.open(source) as opened:
            # Mode P carries its transparency in info, not in the mode, so
            # testing the mode alone missed every transparent PNG-8 and GIF:
            # they skipped the flatten below and had convert("RGB") paint the
            # transparent pixels whatever colour sat at that palette index,
            # while preflight had already promised the user a flatten onto
            # their chosen background. inspect() reads transparency the same
            # way, so the warning and the render now agree.
            transparent = opened.mode in ALPHA_MODES or "transparency" in opened.info
            im = opened.convert("RGBA") if transparent else opened.copy()
            icc = opened.info.get("icc_profile")
    except UnidentifiedImageError:
        raise ImageError(f"not a readable image: {path}") from None
    except OSError as exc:
        raise ImageError(f"could not read {path}: {exc}") from None

    im = ImageOps.exif_transpose(im) or im
    im = _to_srgb(im, icc, notes)

    if im.mode in ALPHA_MODES:
        background = Image.new("RGB", im.size, flatten_colour)
        alpha = im.convert("RGBA").getchannel("A")
        background.paste(im.convert("RGB"), mask=alpha)
        im = background

    return im.convert("RGB")


def _to_srgb(
    im: Image.Image, icc: bytes | None, notes: list[str] | None = None
) -> Image.Image:
    """Convert into sRGB, preserving alpha across the transform."""
    if not icc:
        return im if im.mode in ALPHA_MODES else im.convert("RGB")

    description = (_icc_description(icc) or "").lower()
    if "srgb" in description:
        return im if im.mode in ALPHA_MODES else im.convert("RGB")

    alpha = im.getchannel("A") if im.mode in ALPHA_MODES else None
    body = im.convert("RGB") if im.mode != "CMYK" else im

    try:
        source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        destination_profile = ImageCms.createProfile("sRGB")
        converted = ImageCms.profileToProfile(
            body,
            source_profile,
            destination_profile,
            outputMode="RGB",
        )
        # profileToProfile returns None when it converts in place. It does not
        # with inPlace=False, so this is a guard rather than a live bug, but
        # without it a None would escape the try and reach .convert() below as
        # an AttributeError instead of taking the documented fallback.
        if converted is None:
            raise ValueError("colour conversion returned nothing")
        body = converted
    except Exception as exc:
        # A broken or exotic profile shouldn't stop the export; a plain
        # convert is a worse but working approximation. It is still an
        # approximation, so say so rather than letting the caller believe the
        # transform it was promised actually ran.
        if notes is not None:
            notes.append(
                f"the colour transform into sRGB failed ({exc.__class__.__name__}), "
                f"so the pixels were converted without it and the colours may shift"
            )
        body = body.convert("RGB")

    body = body.convert("RGB")
    if alpha is not None:
        body.putalpha(alpha)
    return body


def render(im: Image.Image, target: Target) -> Image.Image:
    """Resize a normalised image into a target's exact canvas."""
    size = (target.width, target.height)
    if target.fit == "cover":
        return ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return _pad(im, target)


def _pad(im: Image.Image, target: Target) -> Image.Image:
    size = (target.width, target.height)
    fitted = ImageOps.contain(im.copy(), size, method=Image.Resampling.LANCZOS)

    if target.pad_style == "blur":
        canvas = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        radius = max(size) / 22
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius))
        canvas = ImageEnhance.Brightness(canvas).enhance(0.55)
    else:
        canvas = Image.new("RGB", size, target.pad_style)

    offset = ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2)
    canvas.paste(fitted, offset)
    return canvas


@dataclass
class Encoded:
    data: bytes
    quality: int
    over_cap: bool

    @property
    def size(self) -> int:
        return len(self.data)


def encode(im: Image.Image, target: Target) -> Encoded:
    """Encode to bytes, walking JPEG quality down if a size cap demands it."""
    if target.format == "png":
        data = _encode_once(im, target, target.quality)
        over = target.max_bytes is not None and len(data) > target.max_bytes
        return Encoded(data=data, quality=target.quality, over_cap=over)

    data = _encode_once(im, target, target.quality)
    if target.max_bytes is None or len(data) <= target.max_bytes:
        return Encoded(data=data, quality=target.quality, over_cap=False)

    # Highest quality that fits under the cap, by bisection.
    low, high = MIN_QUALITY, target.quality - 1
    best: tuple[bytes, int] | None = None
    while low <= high:
        mid = (low + high) // 2
        candidate = _encode_once(im, target, mid)
        if len(candidate) <= target.max_bytes:
            best = (candidate, mid)
            low = mid + 1
        else:
            high = mid - 1

    if best is not None:
        return Encoded(data=best[0], quality=best[1], over_cap=False)

    floor = _encode_once(im, target, MIN_QUALITY)
    return Encoded(data=floor, quality=MIN_QUALITY, over_cap=True)


def _encode_once(im: Image.Image, target: Target, quality: int) -> bytes:
    buffer = io.BytesIO()
    params: dict = {"optimize": True}
    if SRGB_BYTES:
        params["icc_profile"] = SRGB_BYTES

    if target.format == "png":
        params["compress_level"] = 9
        im.save(buffer, format="PNG", **params)
    else:
        # Baseline, 4:4:4. Progressive JPEG is rejected by some delivery
        # pipelines, and chroma subsampling smears hard-edged cover typography.
        params.update(quality=quality, progressive=False, subsampling=0)
        im.save(buffer, format="JPEG", **params)

    return buffer.getvalue()
