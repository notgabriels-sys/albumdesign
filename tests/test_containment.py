"""A build must not write outside the pack, and must not abandon a batch.

Every case here was reproduced against the previous code, which wrote through
a planted symlink and escaped the output directory via a crafted target key,
in both cases exiting 0 with a manifest that recorded the file as part of the
pack.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from coverforge.build import build, output_name
from coverforge.cli import main
from coverforge.imageops import ImageError, inspect
from coverforge.specs import SpecError, load_targets

WEB_THUMB = [t for t in load_targets().select() if t.key == "web_thumb"]


def test_a_symlink_in_the_output_directory_is_refused(master, tmp_path):
    out = tmp_path / "pack"
    out.mkdir()
    victim = tmp_path / "outside" / "victim.txt"
    victim.parent.mkdir()
    victim.write_text("SECRET-ORIGINAL", encoding="utf-8")
    planted = out / output_name("master", WEB_THUMB[0])
    os.symlink(victim, planted)

    with pytest.raises(ImageError, match="symlink"):
        build(inspect(master), WEB_THUMB, out_dir=out, slug="master")

    # The point of the check: the file the link pointed at is untouched.
    assert victim.read_text(encoding="utf-8") == "SECRET-ORIGINAL"


def test_a_target_key_cannot_contain_path_separators(tmp_path):
    spec = tmp_path / "evil.toml"
    spec.write_text(
        '[targets."x/../../../escaped"]\n'
        'name = "Escape"\ngroup = "dsp"\nwidth = 400\nheight = 400\nformat = "jpeg"\n',
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="path separators"):
        load_targets(extra=spec)


@pytest.mark.parametrize("key", ["..", ".", "a/b", "a\\b", ".hidden", ""])
def test_rejected_keys(tmp_path, key):
    spec = tmp_path / "t.toml"
    # Single-quoted TOML keys are literal, so a backslash stays a backslash
    # instead of being read as an escape sequence.
    spec.write_text(
        f"[targets.'{key}']\n"
        'name = "T"\ngroup = "dsp"\nwidth = 10\nheight = 10\nformat = "jpeg"\n',
        encoding="utf-8",
    )
    with pytest.raises(SpecError):
        load_targets(extra=spec)


def test_one_unreadable_master_does_not_abandon_the_batch(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("a", "c"):
        Image.new("RGB", (1200, 1200), (10, 200, 90)).save(src / f"{name}.png")
    Image.new("RGB", (1200, 1200), (200, 10, 90)).save(src / "b.png")
    raw = (src / "b.png").read_bytes()
    (src / "b.png").write_bytes(raw[: len(raw) // 2])  # truncated: inspect ok, decode fails

    out = tmp_path / "out"
    main(["build", str(src), "-o", str(out), "--only", "web_thumb"])

    # c comes after the broken b alphabetically, so it proves the loop continued.
    assert (out / "c").is_dir(), capsys.readouterr().err
    assert (out / "a").is_dir()


def _palette_png_with_transparency(path, transparent_palette_colour=(0, 0, 0)):
    """A PNG-8 whose transparent index is a colour you would notice."""
    im = Image.new("P", (1200, 1200), 1)
    r, g, b = transparent_palette_colour
    im.putpalette([r, g, b, 200, 40, 120] + [0] * (254 * 3))
    for x in range(600):
        for y in range(600):
            im.putpixel((x, y), 0)
    im.save(path, transparency=0)
    return path


@pytest.mark.parametrize("colour,expected", [("#ffffff", (255, 255, 255)), ("#00ff00", (0, 255, 0))])
def test_palette_transparency_is_flattened_onto_the_chosen_colour(tmp_path, colour, expected):
    """Mode P keeps transparency in info, not in the mode.

    Testing the mode alone meant --flatten was a no-op for every PNG-8 and GIF
    master: the transparent pixels came out as whatever colour sat at that
    palette index, while preflight told the user they had been flattened onto
    the colour they asked for.
    """
    src = _palette_png_with_transparency(tmp_path / "pal.png", (0, 0, 0))
    out = tmp_path / "out"
    build(inspect(src), WEB_THUMB, out_dir=out, slug="pal", flatten_colour=colour)

    with Image.open(out / output_name("pal", WEB_THUMB[0])) as delivered:
        pixel = delivered.convert("RGB").getpixel((100, 100))
    assert all(abs(a - b) <= 2 for a, b in zip(pixel, expected)), pixel


def test_the_readme_example_matches_the_real_target_list():
    """The worked example in the README drifted from targets.toml.

    It showed 9 targets where a real run prints 10 (soundcloud_distro was
    missing) and rendered Beatport at 1400x1400 where the spec says 3000. The
    README is the first thing a stranger reads, so it is worth pinning.
    """
    import re

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    keys = [t.key for t in load_targets().select()]

    counts = re.findall(r"vs (\d+) target\(s\)", readme)
    assert counts, "the README example no longer shows a target count"
    assert all(int(c) == len(keys) for c in counts), f"README says {counts}, there are {len(keys)}"

    listed = re.search(r"ok \d+/\d+ targets clear: ([^\n]*(?:\n\s{5}[^\n]*)*)", readme)
    assert listed, "the README example no longer lists the clear targets"
    named = [k.strip() for k in listed.group(1).replace("\n", " ").split(",") if k.strip()]
    assert named == keys, f"README lists {named}, targets.toml has {keys}"


def test_the_readme_does_not_call_min_source_a_platform_floor():
    """targets.toml says several floors are coverforge's own, not the store's.

    The README said the opposite ("the store would reject it anyway"), which
    contradicted the file it was describing.
    """
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert "because the store would reject it anyway" not in readme
