import pytest
from PIL import Image, ImageDraw


def make_art(path, size=(3000, 3000), mode="RGB", noise=True):
    """A stand-in for cover art: gradient plus shapes, so JPEG has real work to do."""
    width, height = size
    im = Image.new(mode, size, "black")
    draw = ImageDraw.Draw(im)
    for y in range(0, height, 4):
        shade = int(255 * y / max(height - 1, 1))
        draw.rectangle([0, y, width, y + 4], fill=(shade, 40, 255 - shade)[: len(im.getbands())])
    if noise:
        for i in range(24):
            offset = i * (width // 24)
            draw.ellipse(
                [offset, offset // 2, offset + width // 6, offset // 2 + height // 6],
                outline="white",
                width=7,
            )
    im.save(path)
    return path


@pytest.fixture
def master(tmp_path):
    return make_art(tmp_path / "master.png")


@pytest.fixture
def art_factory(tmp_path):
    counter = {"n": 0}

    def factory(name="art", **kwargs):
        counter["n"] += 1
        suffix = kwargs.pop("suffix", ".png")
        return make_art(tmp_path / f"{name}{counter['n']}{suffix}", **kwargs)

    return factory
