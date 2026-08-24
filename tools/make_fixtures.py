"""Generate the test fixtures used by tools/browser_test.js.

    uv run --with pillow python tools/make_fixtures.py

Writes the image fixtures into tools/fixtures/.
"""
from pathlib import Path

from PIL import Image

d = Path(__file__).parent / "fixtures"
d.mkdir(exist_ok=True)

Image.new("RGB", (3000, 3000), (20, 140, 90)).save(d / "good_3000.jpg", quality=90)
Image.new("RGB", (4000, 4000), (20, 140, 90)).save(d / "over_4000.jpg", quality=90)
Image.new("CMYK", (3000, 3000)).save(d / "cmyk_3000.jpg")
Image.new("RGB", (1200, 1600), (200, 50, 50)).save(d / "nonsquare.jpg", quality=90)

# Square but under the 1400px floor most distributors enforce. Nothing in the
# set was below it, so the resolution FAIL branch could be turned into a pass
# with no browser assertion noticing.
Image.new("RGB", (1000, 1000), (60, 90, 160)).save(d / "small_1000.jpg", quality=90)

# Not an image at all, under a name the picker accepts. The header sniffer
# reports "unknown" and the browser cannot decode it, so this drives both the
# format FAIL and readable FAIL branches, neither of which had a fixture.
(d / "notanimage.jpg").write_bytes(b"this is not an image, not even slightly" * 40)
Image.new("RGBA", (3000, 3000), (10, 10, 10, 128)).save(d / "alpha_3000.png")

# A CMYK TIFF: the exact file the cover tool exists to catch, and the one
# Chromium cannot decode. Dimensions and colour never load, so the size, shape
# and colour checks skipped themselves and the verdict read "No blockers".
Image.new("CMYK", (2400, 1800)).save(d / "cmyk_nonsquare.tif")

# Greyscale with alpha matched the grayscale branch first and lost the flatten
# advice that an RGBA file gets.
Image.new("LA", (3000, 3000), (120, 128)).save(d / "gray_alpha_3000.png")
