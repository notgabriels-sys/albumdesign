"""A pack nobody listened to is not a clean pack.

`packcheck.py` had no tests and is not a CI step of its own, which is how
this survived: `peak_dbfs` returns None for any width it cannot decode and on
any read error, and the caller dropped that on the floor. A 32-bit file
clipping at 0 dBFS drew no comment while a 24-bit file at the identical
amplitude was reported as clipped. `--quick` skips the decode entirely and
still printed the same "N WAV files, 0 error(s), 0 warning(s)" summary, then
wrote README.txt for a pack holding that clipped file.

Both were proved on a built pack before being fixed. These pin the fix, and
the fixtures are built here rather than committed, like every other fixture in
this repo.
"""

from __future__ import annotations

import importlib.util
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "packcheck", ROOT / "tools" / "packcheck.py"
)
pc = importlib.util.module_from_spec(_spec)
# @dataclass resolves annotations through sys.modules[cls.__module__], so the
# module has to be registered before it is executed or the decorator raises.
sys.modules["packcheck"] = pc
_spec.loader.exec_module(pc)


def _tone(path: Path, amp: float, width: int, secs: float = 0.2, rate: int = 44100) -> None:
    """A mono sine at `amp` of full scale, written at `width` bytes per sample."""
    n = int(rate * secs)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        full = {2: 32767, 3: 8388607, 4: 2147483647}[width]
        raw = bytearray()
        for i in range(n):
            v = int(amp * full * math.sin(2 * math.pi * 220 * i / rate))
            if width == 4:
                raw += struct.pack("<i", v)
            else:
                raw += int(v).to_bytes(width, "little", signed=True)
        w.writeframes(bytes(raw))


@pytest.fixture
def pack(tmp_path):
    """An otherwise-correct pack, so any finding is the one under test."""
    root = tmp_path / "Pack"
    root.mkdir()
    for folder in pc.FOLDERS:
        (root / folder).mkdir()
    _tone(root / "01_Kicks" / "Kick_01.wav", 0.5, 3)
    return root


def levels(pack_result):
    return [f.message for f in pack_result.findings]


class TestALevelNobodyMeasuredIsNotALevelUnderTheCeiling:
    def test_an_undecodable_width_is_reported(self, pack):
        # Same amplitude as the clipped 24-bit file below. Its level cannot be
        # read here, and that has to be said rather than passed over.
        _tone(pack / "01_Kicks" / "Hot_32bit.wav", 1.0, 4)
        result = pc.check_pack(pack, deep=True)
        # The message first, so this fails on the defect itself against the
        # old file rather than on the counter below not existing yet.
        assert any("level not measured" in m for m in levels(result))
        assert result.levels_unmeasured == 1

    def test_the_same_amplitude_at_24_bit_is_reported_clipped(self, pack):
        # Proves the fixture really is clipped, so the test above is about the
        # measurement not happening rather than about a quiet file.
        _tone(pack / "01_Kicks" / "Hot_24bit.wav", 1.0, 3)
        result = pc.check_pack(pack, deep=True)
        assert any("likely clipped" in m for m in levels(result))

    def test_an_unmeasured_level_is_a_finding_not_a_silence(self, pack):
        _tone(pack / "01_Kicks" / "Hot_32bit.wav", 1.0, 4)
        result = pc.check_pack(pack, deep=True)
        assert not any("silent file" in m for m in levels(result))

    def test_a_readable_pack_counts_what_it_listened_to(self, pack):
        _tone(pack / "02_Percussion" / "Perc_01.wav", 0.4, 3)
        result = pc.check_pack(pack, deep=True)
        assert result.levels_checked == 2
        assert result.levels_unmeasured == 0

    def test_a_16_bit_file_is_still_decoded(self, pack):
        # 16-bit is wrong for this pack, but its level is readable, so the
        # bit-depth error must not be joined by an unmeasured-level warning.
        _tone(pack / "01_Kicks" / "Old_16bit.wav", 1.0, 2)
        result = pc.check_pack(pack, deep=True)
        assert result.levels_unmeasured == 0
        assert any("likely clipped" in m for m in levels(result))

    def test_silence_is_still_told_apart_from_unmeasured(self, pack):
        _tone(pack / "01_Kicks" / "Quiet.wav", 0.0, 3)
        result = pc.check_pack(pack, deep=True)
        assert any("silent file" in m for m in levels(result))
        assert result.levels_unmeasured == 0


class TestQuickSaysWhatItSkipped:
    def _run(self, monkeypatch, capsys, argv):
        monkeypatch.setattr(sys, "argv", ["packcheck.py", *argv])
        code = pc.main()
        return code, capsys.readouterr()

    def test_quick_does_not_report_a_clipped_pack_as_clean(
        self, pack, monkeypatch, capsys
    ):
        _tone(pack / "01_Kicks" / "Hot_24bit.wav", 1.0, 3)
        _, out = self._run(monkeypatch, capsys, [str(pack), "--quick"])
        assert "0 error(s), 0 warning(s)" in out.out
        assert "not decoded" in out.out, "the summary must say what it skipped"

    def test_a_full_run_on_the_same_pack_does_find_it(self, pack, monkeypatch, capsys):
        # The pair is the point: identical pack, one run finds the clipping and
        # the other cannot, so the two summaries must not read the same.
        _tone(pack / "01_Kicks" / "Hot_24bit.wav", 1.0, 3)
        _, out = self._run(monkeypatch, capsys, [str(pack)])
        assert "likely clipped" in out.out
        assert "not decoded" not in out.out

    def test_a_clean_full_run_claims_nothing_extra(self, pack, monkeypatch, capsys):
        _, out = self._run(monkeypatch, capsys, [str(pack)])
        assert "not decoded" not in out.out
        assert "had no level measured" not in out.out

    def test_the_deep_summary_counts_the_unmeasured(self, pack, monkeypatch, capsys):
        _tone(pack / "01_Kicks" / "Hot_32bit.wav", 1.0, 4)
        _, out = self._run(monkeypatch, capsys, [str(pack)])
        assert "had no level measured" in out.out

    def test_a_readme_from_a_quick_run_says_so(self, pack, monkeypatch, capsys):
        _, out = self._run(
            monkeypatch, capsys, [str(pack), "--quick", "--write-readme"]
        )
        assert (pack / "README.txt").exists()
        assert "--quick" in out.err, "writing the sales document must disclose it"

    def test_a_readme_from_a_full_run_needs_no_note(self, pack, monkeypatch, capsys):
        _, out = self._run(monkeypatch, capsys, [str(pack), "--write-readme"])
        assert (pack / "README.txt").exists()
        assert "--quick" not in out.err


class TestTheGuardsThatMustNotFire:
    """These pass before the fix too. They are here so the fix cannot be made
    by simply warning about everything."""

    def test_an_empty_pack_still_says_so(self, tmp_path):
        root = tmp_path / "Empty"
        root.mkdir()
        result = pc.check_pack(root, deep=True)
        assert any("no WAV files found" in m for m in levels(result))

    def test_a_clean_pack_produces_no_error(self, pack):
        result = pc.check_pack(pack, deep=True)
        assert [f for f in result.findings if f.level == "error"] == []

    def test_junk_is_still_caught(self, pack):
        (pack / "01_Kicks" / ".DS_Store").write_text("junk")
        result = pc.check_pack(pack, deep=True)
        assert any("junk file" in m for m in levels(result))
