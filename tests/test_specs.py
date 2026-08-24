import pytest

from coverforge.specs import SpecError, load_targets


def test_builtin_targets_load():
    targets = load_targets()
    assert len(targets) >= 8
    assert "bandcamp" in targets.targets
    assert targets.targets["bandcamp"].is_square


def test_every_builtin_target_is_coherent():
    for target in load_targets():
        assert target.width > 0 and target.height > 0
        assert target.format in {"jpeg", "png"}
        assert target.extension in {"jpg", "png"}
        # A target that demands less source than it outputs would silently upscale.
        if target.min_source:
            assert target.min_source <= max(target.width, target.height)


def test_groups_are_declaration_ordered():
    assert load_targets().groups[:2] == ["dsp", "social"]


def test_select_by_key_and_group():
    targets = load_targets()
    picked = targets.select(only=["soundcloud"], groups=["social"])
    keys = [t.key for t in picked]
    assert "soundcloud" in keys
    assert "instagram_story" in keys
    assert "bandcamp" not in keys


def test_select_rejects_unknown():
    targets = load_targets()
    with pytest.raises(SpecError, match="unknown target"):
        targets.select(only=["myspace"])
    with pytest.raises(SpecError, match="unknown group"):
        targets.select(groups=["vinyl"])


def _write(tmp_path, body):
    path = tmp_path / "targets.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_extra_targets_override_and_extend(tmp_path):
    extra = _write(
        tmp_path,
        """
[targets.bandcamp]
name = "Bandcamp"
group = "dsp"
width = 4000
height = 4000
format = "jpeg"

[targets.vinyl_sleeve]
name = "Vinyl sleeve proof"
group = "print"
width = 3500
height = 3500
format = "png"
""",
    )
    targets = load_targets(extra=extra)
    assert targets.targets["bandcamp"].width == 4000
    assert "vinyl_sleeve" in targets.targets
    assert "spotify" in targets.targets  # built-ins survive the merge


def test_target_keys_cannot_differ_only_by_case_within_one_file(tmp_path):
    path = _write(
        tmp_path,
        """
[targets.Artwork]
width = 100
height = 100
format = "jpeg"

[targets.artwork]
width = 200
height = 200
format = "png"
""",
    )

    with pytest.raises(SpecError, match="collide case-insensitively"):
        load_targets(path)


def test_overlay_target_keys_cannot_differ_from_base_only_by_case(tmp_path):
    base = tmp_path / "base.toml"
    base.write_text(
        """
[targets.Artwork]
width = 100
height = 100
format = "jpeg"
""",
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.toml"
    overlay.write_text(
        """
[targets.artwork]
width = 200
height = 200
format = "png"
""",
        encoding="utf-8",
    )

    with pytest.raises(SpecError, match="collide case-insensitively"):
        load_targets(base, extra=overlay)


def test_empty_target_name_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
[targets.artwork]
name = ""
width = 100
height = 100
format = "jpeg"
""",
    )

    with pytest.raises(SpecError, match="name must be a non-empty string"):
        load_targets(path)


@pytest.mark.parametrize(
    "body, message",
    [
        ('[targets.x]\nwidth = 100\nheight = 100\n', "missing required field 'format'"),
        ('[targets.x]\nwidth = 0\nheight = 100\nformat = "jpeg"\n', "must be positive"),
        ('[targets.x]\nwidth = 10\nheight = 10\nformat = "tiff"\n', "format must be one of"),
        ('[targets.x]\nwidth = 10\nheight = 10\nformat = "jpeg"\nfit = "squish"\n', "fit must be one of"),
        (
            '[targets.x]\nwidth = 10\nheight = 10\nformat = "jpeg"\npad_style = "reddish"\n',
            "pad_style must be",
        ),
        ('[targets.x]\nwidth = 10\nheight = 10\nformat = "jpeg"\nquality = 0\n', "quality must be"),
        ('[targets.x]\nwidth = 10\nheight = 10\nformat = "jpeg"\nquality = true\n', "quality must be an integer"),
        ('[targets.x]\nwidth = 10\nheight = 10\nformat = "jpeg"\nmin_source = -1\n', "min_source must be"),
        ('[targets.x]\nwidth = 10\nheight = 10\nformat = "jpeg"\nmax_bytes = true\n', "max_bytes must be"),
        ('[targets.x]\nname = 3\nwidth = 10\nheight = 10\nformat = "jpeg"\n', "name must be"),
        ("[nothing]\n", "no [targets.*] tables"),
    ],
)
def test_malformed_targets_are_rejected(tmp_path, body, message):
    with pytest.raises(SpecError) as exc:
        load_targets(_write(tmp_path, body))
    assert message in str(exc.value)


def test_missing_file(tmp_path):
    with pytest.raises(SpecError, match="not found"):
        load_targets(tmp_path / "nope.toml")


def test_targets_path_io_error_is_a_spec_error(tmp_path):
    with pytest.raises(SpecError, match="could not read targets file"):
        load_targets(tmp_path)
