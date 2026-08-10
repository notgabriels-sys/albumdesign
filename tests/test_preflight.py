from PIL import Image

from coverforge.imageops import inspect
from coverforge.preflight import ERROR, INFO, WARN, check, cover_scale, worst_level
from coverforge.specs import load_targets

TARGETS = load_targets().select()


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level == level}


def test_clean_3000px_master_has_no_errors_or_warnings(master):
    findings = check(inspect(master), TARGETS)
    assert codes(findings, ERROR) == set()
    assert codes(findings, WARN) == set()
    assert worst_level(findings) == INFO


def test_small_master_fails_the_big_targets(art_factory):
    src = inspect(art_factory(size=(1000, 1000)))
    findings = check(src, TARGETS)
    blocked = {f.target for f in findings if f.level == ERROR and f.code == "below-minimum"}
    assert {"spotify", "apple_music", "bandcamp"} <= blocked
    # SoundCloud's floor is 800px, so it stays reachable.
    assert "soundcloud" not in blocked


def test_upscale_is_warned_not_silently_done(art_factory):
    src = inspect(art_factory(size=(1600, 1600)))
    findings = check(src, TARGETS)
    upscales = {f.target for f in findings if f.code == "upscale"}
    assert "spotify" in upscales
    assert "web_thumb" not in upscales
    assert all(f.level == WARN for f in findings if f.code == "upscale")


def test_non_square_master_is_flagged_and_crop_is_quantified(art_factory):
    src = inspect(art_factory(size=(4000, 3000)))
    findings = check(src, TARGETS)
    assert "not-square" in codes(findings, WARN)
    crops = [f for f in findings if f.code == "crop" and f.target == "bandcamp"]
    assert crops and "75%" in crops[0].message


def test_pad_targets_do_not_report_crop(art_factory):
    src = inspect(art_factory(size=(4000, 3000)))
    findings = check(src, TARGETS)
    assert not [f for f in findings if f.code == "crop" and f.target == "instagram_story"]


def test_alpha_is_flagged_with_the_flatten_colour(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (3000, 3000), (10, 10, 10, 200)).save(path)
    findings = check(inspect(path), TARGETS, flatten_colour="#000000")
    alpha = [f for f in findings if f.code == "alpha"]
    assert alpha and alpha[0].level == WARN
    assert "#000000" in alpha[0].message


def test_cmyk_is_flagged(tmp_path):
    path = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (3000, 3000), (0, 0, 0, 20)).save(path)
    assert "cmyk" in codes(check(inspect(path), TARGETS), WARN)


def test_missing_icc_is_only_informational(master):
    findings = check(inspect(master), TARGETS)
    icc = [f for f in findings if f.code == "no-icc"]
    assert icc and icc[0].level == INFO


def test_cover_scale_matches_the_long_edge_requirement(art_factory):
    src = inspect(art_factory(size=(1500, 1500)))
    spotify = next(t for t in TARGETS if t.key == "spotify")
    assert cover_scale(src, spotify) == 2.0
    story = next(t for t in TARGETS if t.key == "instagram_story")
    # Pad fits inside, so it scales by the smaller ratio.
    assert cover_scale(src, story) == 1080 / 1500
