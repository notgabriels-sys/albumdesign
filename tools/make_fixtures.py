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

# A CMYK TIFF: the exact file the cover tool exists to catch, and the one
# Chromium cannot decode. Dimensions and colour never load, so the size, shape
# and colour checks skipped themselves and the verdict read "No blockers".
Image.new("CMYK", (2400, 1800)).save(d / "cmyk_nonsquare.tif")

# Greyscale with alpha matched the grayscale branch first and lost the flatten
# advice that an RGBA file gets.
Image.new("LA", (3000, 3000), (120, 128)).save(d / "gray_alpha_3000.png")

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

# A loud club master: about -1.5 LUFS with true peak about -1.5 dBTP. Spotify's
# stated rule is -1 dBTP, and -2 if the master is louder than -14 LUFS, so this
# file must trip the ceiling. The flag used to be a flat tp > -1, which let this
# exact case pass while both pages told the reader -2 applied. Written at 44.1k
# so it also proves the reported rate comes from the file, not the audio device.
loud_amp = 10 ** (-1.5 / 20.0)
with wave.open(str(d / "loud_44100.wav"), "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(44100)
    frames = bytearray()
    for i in range(44100 * 3):
        v = int(loud_amp * math.sin(2 * math.pi * 1000 * i / 44100) * 32767)
        frames += struct.pack("<hh", v, v)
    w.writeframes(bytes(frames))

# Edge cases: silence and a clip shorter than the 400 ms BS.1770 block. Both
# used to render "+Infinity dB" in the platform table.
for name, secs in (("silence.wav", 4), ("tiny_200ms.wav", 0.2)):
    with wave.open(str(d / name), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<hh", 0, 0) * int(rate * secs))

# Inter-sample peak case: sine at fs/4 phased so every sample lands at +-0.707.
# Sample peak reads -3.01 dBFS; a real true-peak meter must report about 0 dBTP.
with wave.open(str(d / "intersample_peak.wav"), "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(rate)
    fr = bytearray()
    for i in range(rate * 6):
        v = int(0.999 * math.sin(2 * math.pi * (rate / 4) * i / rate + math.pi / 4) * 32767)
        fr += struct.pack("<hh", v, v)
    w.writeframes(bytes(fr))

print("fixtures written to", d)
