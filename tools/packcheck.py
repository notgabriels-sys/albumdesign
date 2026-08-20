#!/usr/bin/env python3
"""Preflight a sample pack before it goes on sale, and write its README.

Same idea as `coverforge check` for artwork: the things a buyer judges you on
are mechanical and easy to get wrong across 130 files by hand. Wrong bit depth
in four files, a stray .DS_Store, one clipped kick, loops whose filename BPM
does not match their actual length, and the pack looks careless.

    python tools/packcheck.py path/to/Duress_Vol1 --title "Duress - Vol. 1"
    python tools/packcheck.py path/to/pack --write-readme

Checks are against the pack spec: WAV, 24-bit, 44.1 kHz, no clipping, trimmed,
loops named with their BPM, tonal material key-labelled. Nothing here invents
a requirement; edit SPEC below if the spec changes.

Exit codes: 0 clean, 1 findings, 2 bad usage.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path

SPEC = {
    "bit_depth": 24,
    "sample_rate": 44100,
    "loop_bpms": (130, 134),
    # A one-shot longer than this is probably an untrimmed export.
    "oneshot_max_seconds": 12.0,
    # Peaks this close to full scale usually mean a clipped or brickwalled file.
    "peak_ceiling_dbfs": -0.1,
}

FOLDERS = [
    "01_Kicks",
    "02_Percussion",
    "03_Hats",
    "04_Bass",
    "05_Synths_Stabs",
    "06_FX_Textures",
    "07_Loops",
    "08_MIDI",
]

TONAL_FOLDERS = {"04_Bass", "05_Synths_Stabs"}
KEY_RE = re.compile(r"_([A-G](?:#|b)?m?)(?:_|\.)")
BPM_RE = re.compile(r"_(\d{2,3})bpm", re.I)
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}


@dataclass
class Finding:
    level: str  # "error" | "warn" | "info"
    where: str
    message: str


@dataclass
class Pack:
    root: Path
    wavs: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, where: str, message: str) -> None:
        self.findings.append(Finding(level, where, message))


def read_wav(path: Path) -> tuple[dict, str | None]:
    """Return (facts, error). Facts are read from the header, cheaply."""
    try:
        with wave.open(str(path), "rb") as w:
            return (
                {
                    "channels": w.getnchannels(),
                    "sampwidth": w.getsampwidth(),
                    "rate": w.getframerate(),
                    "frames": w.getnframes(),
                    "seconds": w.getnframes() / float(w.getframerate() or 1),
                },
                None,
            )
    except wave.Error as exc:
        return {}, f"not a readable WAV ({exc})"
    except OSError as exc:
        return {}, f"could not read ({exc})"


def peak_dbfs(path: Path, facts: dict) -> float | None:
    """Peak level. Only 16- and 24-bit PCM are decoded; others return None."""
    width = facts.get("sampwidth")
    if width not in (2, 3):
        return None
    try:
        with wave.open(str(path), "rb") as w:
            raw = w.readframes(w.getnframes())
    except (wave.Error, OSError, MemoryError):
        return None
    if not raw:
        return None

    peak = 0
    if width == 2:
        full = 32768.0
        for (v,) in struct.iter_unpack("<h", raw[: len(raw) // 2 * 2]):
            peak = max(peak, abs(v))
    else:
        full = 8388608.0
        for i in range(0, len(raw) - 2, 3):
            v = int.from_bytes(raw[i : i + 3], "little", signed=True)
            peak = max(peak, abs(v))
    if peak == 0:
        return float("-inf")
    import math

    return 20 * math.log10(peak / full)


def check_pack(root: Path, deep: bool) -> Pack:
    pack = Pack(root=root)

    present = {p.name for p in root.iterdir() if p.is_dir()}
    for folder in FOLDERS:
        if folder not in present:
            level = "info" if folder == "08_MIDI" else "warn"
            pack.add(level, folder, "folder missing from the pack structure")
    for extra in sorted(present - set(FOLDERS) - {"07_Loops"}):
        pack.add("info", extra, "folder is not in the documented structure")

    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if path.name in JUNK or path.name.startswith("._"):
            pack.add("error", rel, "junk file; delete before shipping")
            continue
        if path.suffix.lower() == ".mid":
            continue
        if path.suffix.lower() in (".txt", ".md", ".pdf"):
            continue
        if path.suffix.lower() != ".wav":
            pack.add("warn", rel, f"{path.suffix or 'no extension'} is not WAV")
            continue

        pack.wavs.append(path)
        facts, err = read_wav(path)
        if err:
            pack.add("error", rel, err)
            continue

        if facts["sampwidth"] * 8 != SPEC["bit_depth"]:
            pack.add(
                "error",
                rel,
                f"{facts['sampwidth'] * 8}-bit, the pack is documented as "
                f"{SPEC['bit_depth']}-bit",
            )
        if facts["rate"] != SPEC["sample_rate"]:
            pack.add(
                "error",
                rel,
                f"{facts['rate']} Hz, the pack is documented as {SPEC['sample_rate']} Hz",
            )
        if facts["frames"] == 0:
            pack.add("error", rel, "empty file")

        top = path.relative_to(root).parts[0]
        is_loop = "07_Loops" in path.parts or "loop" in path.name.lower()

        if is_loop:
            m = BPM_RE.search(path.name)
            if not m:
                pack.add("warn", rel, "loop has no _<bpm>bpm in its filename")
            elif int(m.group(1)) not in SPEC["loop_bpms"]:
                pack.add(
                    "info",
                    rel,
                    f"{m.group(1)} bpm is outside the documented "
                    f"{'/'.join(str(b) for b in SPEC['loop_bpms'])} bpm",
                )
            elif facts["seconds"] > 0:
                # A 4-bar loop at B bpm runs 4*4*60/B seconds. Anything that is
                # not close to a whole number of bars will not sit in a grid.
                bars = facts["seconds"] * int(m.group(1)) / 240.0
                if abs(bars - round(bars)) > 0.02 and round(bars) > 0:
                    pack.add(
                        "warn",
                        rel,
                        f"{facts['seconds']:.2f}s at {m.group(1)} bpm is {bars:.2f} bars, "
                        f"not a whole number; it will not loop cleanly",
                    )
        else:
            if facts["seconds"] > SPEC["oneshot_max_seconds"]:
                pack.add(
                    "info",
                    rel,
                    f"{facts['seconds']:.1f}s one-shot; check it is trimmed",
                )
            if top in TONAL_FOLDERS and not KEY_RE.search(path.name):
                pack.add("warn", rel, "tonal material without a key in the filename")

        if deep:
            peak = peak_dbfs(path, facts)
            if peak is not None and peak > SPEC["peak_ceiling_dbfs"]:
                pack.add("error", rel, f"peaks at {peak:.2f} dBFS; likely clipped")
            elif peak == float("-inf"):
                pack.add("error", rel, "silent file")

    if not pack.wavs:
        pack.add("error", ".", "no WAV files found")
    return pack


def readme(root: Path, pack: Pack, title: str) -> str:
    counts = {}
    for p in pack.wavs:
        counts[p.relative_to(root).parts[0]] = counts.get(p.relative_to(root).parts[0], 0) + 1
    lines = [
        title.upper(),
        "by Fate Through / Gabriel G Alonso",
        "-" * 50,
        f"Format:   WAV {SPEC['bit_depth']}-bit / {SPEC['sample_rate'] / 1000:g} kHz",
        f"Files:    {len(pack.wavs)} samples",
        f"BPM:      {'-'.join(str(b) for b in SPEC['loop_bpms'])} (loops)",
        "Keys:     labelled in filenames for tonal material",
        "",
        "CONTENTS",
    ]
    for folder in FOLDERS:
        if counts.get(folder):
            n = counts[folder]
            lines.append(f"{folder:<17}{n} file" + ("s" if n != 1 else ""))
    lines += [
        "",
        "LICENCE",
        "Royalty-free for commercial use in your own music productions.",
        "Do not resell or redistribute the samples as-is, on their own or in",
        "another pack. Credit is appreciated, not required.",
        "",
        "CONTACT",
        "hologrampeoplemusic@gmail.com",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pack", help="the pack folder")
    ap.add_argument("--title", default="Duress - Vol. 1")
    ap.add_argument("--write-readme", action="store_true", help="write README.txt into the pack")
    ap.add_argument(
        "--quick", action="store_true", help="skip decoding audio (no clipping or silence check)"
    )
    args = ap.parse_args()

    root = Path(args.pack)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    pack = check_pack(root, deep=not args.quick)

    order = {"error": 0, "warn": 1, "info": 2}
    for f in sorted(pack.findings, key=lambda f: (order[f.level], f.where)):
        mark = {"error": "x", "warn": "!", "info": "-"}[f.level]
        print(f"  {mark} {f.where}: {f.message}")

    errors = sum(1 for f in pack.findings if f.level == "error")
    warns = sum(1 for f in pack.findings if f.level == "warn")
    print(f"\n{len(pack.wavs)} WAV files, {errors} error(s), {warns} warning(s)")

    if args.write_readme:
        if errors:
            print("not writing README.txt while there are errors", file=sys.stderr)
        else:
            (root / "README.txt").write_text(readme(root, pack, args.title), encoding="utf-8")
            print(f"wrote {root / 'README.txt'}")

    return 1 if errors or warns else 0


if __name__ == "__main__":
    raise SystemExit(main())
