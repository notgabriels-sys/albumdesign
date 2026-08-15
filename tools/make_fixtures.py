"""Generate the test fixtures used by tools/browser_test.js.

    uv run --with pillow python tools/make_fixtures.py

Writes into tools/fixtures/. The WAV is a stereo 1 kHz sine at exactly
-23.0 dBFS, which a correct BS.1770 meter must read as -23.0 LUFS.
"""
import math
import struct
import wave
from pathlib import Path

from PIL import Image

d = Path(__file__).parent / "fixtures"
d.mkdir(exist_ok=True)

Image.new("RGB", (3000, 3000), (20, 140, 90)).save(d / "good_3000.jpg", quality=90)
Image.new("RGB", (4000, 4000), (20, 140, 90)).save(d / "over_4000.jpg", quality=90)
Image.new("CMYK", (3000, 3000)).save(d / "cmyk_3000.jpg")
Image.new("RGB", (1200, 1600), (200, 50, 50)).save(d / "nonsquare.jpg", quality=90)
Image.new("RGBA", (3000, 3000), (10, 10, 10, 128)).save(d / "alpha_3000.png")

rate, secs, amp = 48000, 12, 10 ** (-23.0 / 20.0)
with wave.open(str(d / "sine_-23dBFS.wav"), "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(rate)
    frames = bytearray()
    for i in range(rate * secs):
        v = int(amp * math.sin(2 * math.pi * 1000 * i / rate) * 32767)
        frames += struct.pack("<hh", v, v)
    w.writeframes(bytes(frames))

print("fixtures written to", d)
