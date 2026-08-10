"""Tests for coverforge cover checking."""

from __future__ import annotations

import dataclasses

import pytest
from PIL import Image

from coverforge.checks import check_cover
from coverforge.cli import main
from coverforge.report import Status
from coverforge.spec import Spec, get_profile


def _make_cover(path, size=(3000, 3000), mode="RGB", fmt="PNG"):
    img = Image.new(mode, size, color=(120, 30, 200) if mode == "RGB" else 0)
    img.save(path, format=fmt)
    return str(path)


def _status_for(report, check):
    for result in report.results:
        if result.check == check:
            return result.status
    return None


def test_good_cover_passes(tmp_path):
    path = _make_cover(tmp_path / "cover.png")
    report = check_cover(path)
    assert report.ok
    assert report.worst is Status.PASS


def test_missing_file_fails(tmp_path):
    report = check_cover(str(tmp_path / "nope.png"))
    assert not report.ok
    assert _status_for(report, "file") is Status.FAIL


def test_non_image_fails(tmp_path):
    path = tmp_path / "cover.png"
    path.write_bytes(b"this is not an image")
    report = check_cover(str(path))
    assert not report.ok
    assert _status_for(report, "format") is Status.FAIL


def test_non_square_fails(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(3000, 2000))
    report = check_cover(path)
    assert _status_for(report, "square") is Status.FAIL
    assert not report.ok


def test_too_small_fails(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(800, 800))
    report = check_cover(path)
    assert _status_for(report, "resolution") is Status.FAIL


def test_below_recommended_warns(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(1500, 1500))
    report = check_cover(path)
    assert _status_for(report, "resolution") is Status.WARN
    assert report.ok  # a warning is still overall OK


def test_oversized_warns(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(7000, 7000))
    report = check_cover(path)
    assert _status_for(report, "resolution") is Status.WARN


def test_cmyk_fails(tmp_path):
    path = _make_cover(tmp_path / "cover.jpg", mode="CMYK", fmt="JPEG")
    report = check_cover(path)
    assert _status_for(report, "color") is Status.FAIL


def test_rgba_warns(tmp_path):
    path = _make_cover(tmp_path / "cover.png", mode="RGBA")
    report = check_cover(path)
    assert _status_for(report, "color") is Status.WARN


def test_unsupported_format_fails(tmp_path):
    path = _make_cover(tmp_path / "cover.bmp", fmt="BMP")
    report = check_cover(path)
    assert _status_for(report, "format") is Status.FAIL


def test_no_square_override(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(3000, 2000))
    spec = dataclasses.replace(Spec(), require_square=False)
    report = check_cover(path, spec)
    assert _status_for(report, "square") is None
    assert report.ok


def test_cli_exit_code_pass(tmp_path, capsys):
    path = _make_cover(tmp_path / "cover.png")
    assert main(["check", path]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_exit_code_fail(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(500, 500))
    assert main(["check", path]) == 1


def test_cli_strict_turns_warning_into_failure(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(1500, 1500))
    assert main(["check", path]) == 0
    assert main(["check", "--strict", path]) == 1


def test_cli_no_args_returns_usage():
    assert main([]) == 2


def test_apple_profile_fails_below_3000(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(2000, 2000))
    # Default profile only warns below the recommended size...
    assert _status_for(check_cover(path, get_profile("default")), "resolution") is Status.WARN
    # ...but Apple treats 3000 as a hard floor.
    assert _status_for(check_cover(path, get_profile("apple")), "resolution") is Status.FAIL


def test_spotify_profile_allows_small(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(800, 800))
    # 800px fails the default 1400 minimum but clears Spotify's 640 floor.
    assert _status_for(check_cover(path, get_profile("default")), "resolution") is Status.FAIL
    assert _status_for(check_cover(path, get_profile("spotify")), "resolution") is Status.WARN


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        get_profile("nope")


def test_cli_profile_flag(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(2000, 2000))
    assert main(["check", path]) == 0  # default: warn only
    assert main(["check", "--profile", "apple", path]) == 1  # apple: hard fail


def test_cli_flag_overrides_profile(tmp_path):
    path = _make_cover(tmp_path / "cover.png", size=(2000, 2000))
    # --min-size overrides the apple profile's 3000 floor back down.
    assert main(["check", "--profile", "apple", "--min-size", "1400", path]) == 0


def test_report_shows_non_default_profile(tmp_path):
    path = _make_cover(tmp_path / "cover.png")
    assert "profile: apple" in check_cover(path, get_profile("apple")).render()
    assert "profile:" not in check_cover(path, get_profile("default")).render()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
