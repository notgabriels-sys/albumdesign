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

# A small release for the delivery check: two tracks that agree, and one that
# does not. The two matched tracks are 24-bit 44.1k, which is what a delivery
# actually looks like, and which also proves the tool reads bit depth from the
# file header: decodeAudioData never exposes it, and would resample the rate.
def _write_wav(path, rate, sampwidth, secs, amp, freq=1000.0):
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        peak = 2 ** (sampwidth * 8 - 1) - 1
        frames = bytearray()
        for i in range(int(rate * secs)):
            v = int(amp * math.sin(2 * math.pi * freq * i / rate) * peak)
            b = v.to_bytes(sampwidth, "little", signed=True)
            frames += b + b
        w.writeframes(bytes(frames))


_write_wav(d / "rel_track1_44100_24.wav", 44100, 3, 3, 10 ** (-14.0 / 20.0))
_write_wav(d / "rel_track2_44100_24.wav", 44100, 3, 3, 10 ** (-14.6 / 20.0))
# Wrong rate, wrong depth, and hot enough to break the ceiling that applies.
_write_wav(d / "rel_oddball_48000_16.wav", 48000, 2, 3, 10 ** (-0.4 / 20.0))


# Every sine fixture above reads the same number for loudness and for true peak,
# because at 1 kHz the K-weighting gain happens to cancel BS.1770's -0.691
# offset. That is correct, and it is also useless as a test: printing loudness
# into the true-peak column would pass every assertion. This file separates
# them. A quiet body sets the loudness, one short transient sets the peak, and
# nothing but a real peak meter can report the gap between the two.
def _write_transient(path, rate, sampwidth, secs, body_amp, hit_amp):
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        peak = 2 ** (sampwidth * 8 - 1) - 1
        hit_start, hit_len = int(rate * secs / 2), int(rate * 0.005)
        frames = bytearray()
        for i in range(int(rate * secs)):
            amp = hit_amp if hit_start <= i < hit_start + hit_len else body_amp
            v = int(amp * math.sin(2 * math.pi * 1000 * i / rate) * peak)
            b = v.to_bytes(sampwidth, "little", signed=True)
            frames += b + b
        w.writeframes(bytes(frames))


_write_transient(
    d / "rel_transient_44100_24.wav",
    44100,
    3,
    3,
    10 ** (-30.0 / 20.0),
    10 ** (-3.0 / 20.0),
)


# Clipping is judged against 32767/32768, full scale for a 16-bit file. The
# threshold used to be 0.99969, a digit short and ten times further out, which
# reported a master limited to -0.003 dBFS as pinned at full scale. These two
# straddle the corrected line: 32760 must not be called clipped, 32767 must.
def _write_clipped(path, rate, secs, clip_value):
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * secs)):
            v = int(1.2 * math.sin(2 * math.pi * 1000 * i / rate) * 32767)
            v = max(-clip_value, min(clip_value, v))
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


_write_clipped(d / "rel_near_fs_44100_16.wav", 44100, 3, 32760)
_write_clipped(d / "rel_at_fs_44100_16.wav", 44100, 3, 32767)


# WAVE_FORMAT_EXTENSIBLE is what most DAWs write for 24-bit and for anything
# above stereo. The clipping scanner only accepted format code 1, so a clipped
# 24-bit master, the ordinary delivery file, came back as "no runs of samples
# pinned at full scale". The wave module cannot write this header, so build it
# by hand: fmt of 40 bytes, code 0xFFFE, PCM in the SubFormat GUID.
def _write_extensible(path, rate, secs, clip_value, bits=24, channels=2):
    width = bits // 8
    frames = bytearray()
    peak = 2 ** (bits - 1) - 1
    for i in range(int(rate * secs)):
        v = int(1.2 * math.sin(2 * math.pi * 1000 * i / rate) * peak)
        v = max(-clip_value, min(clip_value, v))
        frames += v.to_bytes(width, "little", signed=True) * channels
    block = width * channels
    fmt = struct.pack(
        "<HHIIHHHHI",
        0xFFFE, channels, rate, rate * block, block, bits,
        22,      # cbSize
        bits,    # wValidBitsPerSample
        0x3,     # dwChannelMask, front left + front right
    ) + b"\x01\x00" + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(frames)) + bytes(frames)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


# A 32-bit float WAV, the other export a DAW hands you. Full scale is 1.0, so
# there is no integer limit to compare against and the old scanner skipped it.
def _write_float(path, rate, secs, amp, channels=2):
    frames = bytearray()
    for i in range(int(rate * secs)):
        v = max(-1.0, min(1.0, 1.2 * math.sin(2 * math.pi * 1000 * i / rate) * amp))
        frames += struct.pack("<f", v) * channels
    block = 4 * channels
    fmt = struct.pack("<HHIIHH", 3, channels, rate, rate * block, block, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(frames)) + bytes(frames)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


_write_extensible(d / "rel_ext24_clipped_44100.wav", 44100, 2, 8388607)
_write_extensible(d / "rel_ext24_clean_44100.wav", 44100, 2, 8000000)
_write_float(d / "rel_float32_clipped_44100.wav", 44100, 2, 1.0)


# BS.1770 defines channel weights for mono, stereo, quad and 5.1 only, so a
# 3-channel file cannot be measured for loudness. It used to sit inside a
# "Ready to deliver" verdict with a blank LUFS cell and nothing said.
with wave.open(str(d / "rel_3channel_44100_24.wav"), "w") as w:
    w.setnchannels(3)
    w.setsampwidth(3)
    w.setframerate(44100)
    frames = bytearray()
    for i in range(44100 * 2):
        v = int(10 ** (-18.0 / 20.0) * math.sin(2 * math.pi * 1000 * i / 44100) * 8388607)
        frames += v.to_bytes(3, "little", signed=True) * 3
    w.writeframes(bytes(frames))

# A file name is the one piece of attacker-shaped text these pages handle, and
# it goes into a single-quoted title attribute. With ' left out of the escape
# set this name closed the attribute and opened an event handler.
_write_wav(
    d / "a' onmouseover='alert(1)' x='.wav", 44100, 3, 1, 10 ** (-20.0 / 20.0)
)

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
