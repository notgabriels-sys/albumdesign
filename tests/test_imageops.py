import io
from pathlib import Path

import pytest
from PIL import Image

from coverforge import imageops
from coverforge.imageops import ImageError, encode, inspect, normalise, render, slugify
from coverforge.specs import Target

from conftest import make_art


def _target(**overrides) -> Target:
    base = dict(
        key="t", name="T", group="g", width=1000, height=1000, format="jpeg", quality=92
    )
    base.update(overrides)
    return Target(**base)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Lack of Fate - Untitled", "lack-of-fate-untitled"),
        ("Hologram People — Vörticity #3", "hologram-people-vorticity-3"),
        ("  spaced   out  ", "spaced-out"),
        ("!!!", "artwork"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_inspect_reads_geometry(master):
    src = inspect(master)
    assert (src.width, src.height) == (3000, 3000)
    assert src.is_square
    assert src.short_edge == 3000
    assert src.mode == "RGB"
    assert src.file_format == "png"
    assert not src.has_alpha


def test_inspect_detects_alpha(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (1200, 1200), (255, 0, 0, 128)).save(path)
    assert inspect(path).has_alpha


def test_inspect_detects_cmyk(tmp_path):
    path = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (1200, 1200), (0, 0, 0, 40)).save(path)
    assert inspect(path).mode == "CMYK"


def test_inspect_detects_progressive_jpeg(tmp_path):
    path = tmp_path / "prog.jpg"
    Image.new("RGB", (900, 900), "purple").save(path, progressive=True)
    assert inspect(path).is_progressive


def test_inspect_rejects_non_images(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("909 kick, 32 steps")
    with pytest.raises(ImageError, match="not a readable image"):
        inspect(path)


def test_inspect_missing_file(tmp_path):
    with pytest.raises(ImageError, match="file not found"):
        inspect(tmp_path / "ghost.png")


def test_normalise_flattens_alpha_onto_chosen_colour(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (200, 200), (0, 0, 0, 0)).save(path)
    flat = normalise(path, flatten_colour="#ff0000")
    assert flat.mode == "RGB"
    assert flat.getpixel((100, 100)) == (255, 0, 0)


def test_normalise_converts_cmyk_to_rgb(tmp_path):
    path = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (300, 300), (0, 0, 0, 0)).save(path)
    assert normalise(path).mode == "RGB"


def test_normalise_applies_exif_orientation(tmp_path):
    path = tmp_path / "rotated.jpg"
    im = Image.new("RGB", (400, 200), "blue")
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90
    im.save(path, exif=exif)
    assert normalise(path).size == (200, 400)


ICC_DIR = Path("/System/Library/ColorSync/Profiles")


def _icc(filename):
    path = ICC_DIR / filename
    if not path.exists():
        pytest.skip(f"{filename} not available on this machine")
    return path.read_bytes()


def _tagged(tmp_path, name, icc, mode="RGB", colour=(200, 30, 40)):
    path = tmp_path / name
    im = Image.new(mode, (600, 600), colour)
    im.save(path, icc_profile=icc, quality=95)
    return path


def test_inspect_names_a_wide_gamut_profile(tmp_path):
    path = _tagged(tmp_path, "wide.jpg", _icc("AdobeRGB1998.icc"))
    assert inspect(path).icc_description == "Adobe RGB (1998)"


def test_normalise_actually_converts_wide_gamut_to_srgb(tmp_path):
    path = _tagged(tmp_path, "wide.jpg", _icc("AdobeRGB1998.icc"))
    with Image.open(path) as raw:
        before = raw.convert("RGB").getpixel((300, 300))
    after = normalise(path).getpixel((300, 300))
    # Same numbers in a wider gamut mean a more saturated colour, so sRGB has
    # to push red up to represent it.
    assert after != before
    assert after[0] > before[0]


def test_normalise_converts_tagged_cmyk(tmp_path):
    path = _tagged(tmp_path, "cmyk.jpg", _icc("Generic CMYK Profile.icc"), mode="CMYK", colour=(0, 200, 180, 10))
    out = normalise(path)
    assert out.mode == "RGB"
    assert out.size == (600, 600)


def test_srgb_tagged_master_is_left_alone(tmp_path):
    from PIL import ImageCms

    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = _tagged(tmp_path, "srgb.jpg", srgb)
    with Image.open(path) as raw:
        before = raw.convert("RGB").getpixel((300, 300))
    assert normalise(path).getpixel((300, 300)) == before


def test_broken_icc_profile_does_not_break_the_export(tmp_path):
    path = _tagged(tmp_path, "junk.jpg", b"this is not an icc profile")
    assert inspect(path).icc_description == "unreadable ICC profile"
    assert normalise(path).mode == "RGB"


def test_render_cover_crops_to_square(art_factory):
    src = normalise(art_factory(size=(3000, 2000)))
    out = render(src, _target(width=1400, height=1400))
    assert out.size == (1400, 1400)


def test_render_pad_keeps_whole_image_and_fills(art_factory):
    src = normalise(art_factory(size=(2000, 2000)))
    out = render(src, _target(width=1080, height=1920, fit="pad", pad_style="blur"))
    assert out.size == (1080, 1920)
    # The padded strips must not be flat black - the blur backdrop is there.
    assert out.getpixel((540, 20)) != (0, 0, 0)


def test_render_pad_with_solid_colour(art_factory):
    src = normalise(art_factory(size=(2000, 2000)))
    out = render(src, _target(width=1080, height=1920, fit="pad", pad_style="#00ff00"))
    assert out.getpixel((5, 5)) == (0, 255, 0)


def test_encode_jpeg_is_baseline_and_srgb(master):
    src = normalise(master)
    result = encode(render(src, _target()), _target())
    with Image.open(io.BytesIO(result.data)) as im:
        assert im.format == "JPEG"
        assert not im.info.get("progressive")
        assert im.info.get("icc_profile")
    assert result.quality == 92
    assert not result.over_cap


def test_encode_respects_size_cap(master):
    src = normalise(master)
    # q95 lands near 310 KB for this image, so the cap forces a walk down.
    target = _target(width=1400, height=1400, quality=95, max_bytes=150_000)
    result = encode(render(src, target), target)
    assert result.size <= 150_000
    assert result.quality < 95
    assert not result.over_cap


def test_encode_flags_impossible_size_cap(master):
    src = normalise(master)
    target = _target(width=3000, height=3000, max_bytes=2_000)
    result = encode(render(src, target), target)
    assert result.over_cap
    assert result.quality == imageops.MIN_QUALITY


def test_encode_png_is_lossless_and_stable(master):
    src = normalise(master)
    target = _target(width=600, height=600, format="png")
    first = encode(render(src, target), target)
    second = encode(render(src, target), target)
    assert first.data == second.data
    with Image.open(io.BytesIO(first.data)) as im:
        assert im.format == "PNG"


def test_no_size_cap_keeps_requested_quality(master):
    src = normalise(master)
    target = _target(quality=88, max_bytes=None)
    assert encode(render(src, target), target).quality == 88
