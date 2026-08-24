"""Generate the test fixtures used by tools/browser_test.js.

    uv run --with pillow python tools/make_fixtures.py

Writes the image fixtures into tools/fixtures/.
"""
import io
import zlib
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

# A PNG signature and an IHDR and nothing else: 33 bytes claiming to be a
# 3000 x 3000 RGB cover, with no image data behind the claim. Cut from a real
# PNG rather than typed out, so the header is a header and not an
# approximation of one. It is what a half-finished export or an interrupted
# copy leaves on disk, and the cover page used to report it as a 3000 x 3000
# cover, "Good to go, with notes", with every platform tile reading Pass.
_real = io.BytesIO()
Image.new("RGB", (3000, 3000), (20, 140, 90)).save(_real, format="PNG")
_png = _real.getvalue()
assert _png[12:16] == b"IHDR" and len(_png) > 33, "PNG layout is not what this fixture cuts"
(d / "png_header_only.png").write_bytes(_png[:33])

# The same shape, but with the IHDR edited to claim a size the file could not
# possibly hold, and the chunk CRC recomputed so the header is internally
# valid. Nothing here is measured, so nothing here may be graded.
_bomb = bytearray(_png[:33])
_bomb[16:20] = (40000).to_bytes(4, "big")
_bomb[20:24] = (40000).to_bytes(4, "big")
_bomb[29:33] = zlib.crc32(bytes(_bomb[12:29])).to_bytes(4, "big")
(d / "png_claims_40000.png").write_bytes(bytes(_bomb) + _png[33:])

# A CMYK TIFF: the exact file the cover tool exists to catch, and the one
# Chromium cannot decode. Dimensions and colour never load, so the size, shape
# and colour checks skipped themselves and the verdict read "No blockers".
Image.new("CMYK", (2400, 1800)).save(d / "cmyk_nonsquare.tif")

# Greyscale with alpha matched the grayscale branch first and lost the flatten
# advice that an RGBA file gets.
Image.new("LA", (3000, 3000), (120, 128)).save(d / "gray_alpha_3000.png")
