import pytest

from coverforge.specs import SpecError, TargetSet, load_targets
from datetime import date as _date


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


# --- `coverforge targets` tells you how old the numbers are, and where they came from ---
#
# CLAUDE.md: "Keep the source and retrieval date for any numeric requirement."
# Both were in the file and neither was in the one command a human runs to read
# the specs: `source` was reachable only through `targets --json`, and the
# review date printed as a bare stamp that prompts nobody.


def _head(reviewed: str, today: _date) -> str:
    from coverforge.report import format_targets
    return format_targets(TargetSet(reviewed=reviewed), colour=False, today=today).splitlines()[0]


@pytest.mark.parametrize(
    "reviewed,today,expected",
    [
        ("2026-08", _date(2026, 8, 29), "(this month)"),
        ("2026-07", _date(2026, 8, 29), "(1 month ago)"),
        ("2025-11", _date(2026, 8, 29), "(9 months ago)"),
        ("2025-12", _date(2026, 1, 1), "(1 month ago)"),
    ],
)
def test_review_date_is_aged_against_a_fixed_today(reviewed, today, expected):
    """`today` is injected so this is a test and not a reading of the clock."""
    assert expected in _head(reviewed, today)


def test_a_fresh_review_does_not_nag():
    head = _head("2026-08", _date(2026, 8, 29))
    assert "verify against your distributor" in head
    assert "re-reading the platform pages" not in head


def test_a_stale_review_says_so_at_the_boundary_and_past_it():
    """6 months is this project's own prompt, so the wording must say whose it is."""
    from coverforge.report import STALE_AFTER_MONTHS

    assert STALE_AFTER_MONTHS == 6
    just_inside = _head("2026-03", _date(2026, 8, 29))   # 5 months
    at_boundary = _head("2026-02", _date(2026, 8, 29))   # 6 months
    assert "re-reading the platform pages" not in just_inside
    assert "re-reading the platform pages" in at_boundary
    assert "this project" in at_boundary, "a house rule must not read as a platform requirement"


@pytest.mark.parametrize("bad", ["soon", "2026-13", "2026", "", "2026-00"])
def test_an_unreadable_review_date_is_not_reported_as_fresh(bad):
    """"0 months old" and "unreadable" are different answers.

    Printing the first for the second would be the file vouching for itself.
    An empty stamp prints no age line at all, which is the honest nothing.
    """
    from coverforge.report import review_age

    months, phrase = review_age(bad, _date(2026, 8, 29))
    assert months is None
    assert "cannot be worked out" in phrase


def test_a_review_date_in_the_future_is_called_wrong_not_fresh():
    head = _head("2026-12", _date(2026, 8, 29))
    assert "in the future" in head and "fix the date" in head


def _provenance_lines(rendered: str) -> list[str]:
    """The lines that state where a target's numbers came from.

    Matched exactly, not by substring over the whole render. Scanning the whole
    document for a word like "invented" hits Beatport's note, which says a
    render below its floor is "mostly invented pixels" and is correct prose.
    """
    return [line.strip() for line in rendered.splitlines()]


def test_every_target_states_where_its_numbers_came_from():
    from coverforge.report import format_targets

    ts = load_targets()
    lines = _provenance_lines(format_targets(ts, colour=False, today=_date(2026, 8, 29)))
    for target in ts:
        expected = target.source or "no source recorded"
        assert expected in lines, f"{target.key} does not say where its numbers came from"


def test_the_cited_and_uncited_targets_are_both_really_there():
    """Neither half may be empty, or one of the two branches above is untested."""
    from coverforge.report import format_targets

    ts = load_targets()
    lines = _provenance_lines(format_targets(ts, colour=False, today=_date(2026, 8, 29)))
    cited = [t for t in ts if t.source]
    uncited = [t for t in ts if not t.source]
    assert cited and uncited, "one branch has no target exercising it"
    assert lines.count("no source recorded") == len(uncited)
    for target in cited:
        assert lines.count(target.source) >= 1


def test_a_missing_source_is_described_as_missing_not_as_a_choice():
    """instagram_post's 1080 is Instagram's own documented size; nobody wrote
    the link down.

    "no source recorded" is a claim about this file, which is checkable.
    "chosen by this project" would be a claim about the number, and a false
    one. This asserts the sentinel wording itself rather than scanning the
    whole render, so a target's prose cannot satisfy or break it.
    """
    from coverforge.report import format_targets

    ts = load_targets()
    lines = _provenance_lines(format_targets(ts, colour=False, today=_date(2026, 8, 29)))
    sentinels = {line for line in lines if "source" in line and "://" not in line}
    assert sentinels == {"no source recorded"}, sentinels
    for overclaim in ("chosen", "our own", "invented", "made up", "estimated"):
        assert overclaim not in "no source recorded"
