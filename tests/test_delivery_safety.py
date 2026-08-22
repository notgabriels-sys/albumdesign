"""A delivery command must not claim more than it checked, or write where it was pointed.

Every case here was reproduced against the code before it was fixed: a bundle
whose cover had been swapped was called ok, a shareable zip was stamped ok
without a hash ever being computed, a contact sheet destroyed the file a symlink
pointed at, and a manifest's `file` field reached outside the folder.

A manifest is by design something you receive from someone else, so its contents
are untrusted text, and a package is by design something you hand to a client,
so what it embeds leaves the machine.
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from coverforge import imageops
from coverforge.audit import BundleAudit, run_audit
from coverforge.build import build
from coverforge.manifest import compare_manifests
from coverforge.cli import main
from coverforge.imageops import ImageError, inspect
from coverforge.preflight import ERROR, WARN, check
from coverforge.specs import load_targets

TARGETS = [t for t in load_targets(None, None) if t.key in {"spotify", "bandcamp"}]


@pytest.fixture
def master(tmp_path):
    path = tmp_path / "master.png"
    Image.new("RGB", (4000, 4000), (30, 80, 140)).save(path)
    return path


@pytest.fixture
def bundle(tmp_path, master):
    out = tmp_path / "delivery"
    build(inspect(master), TARGETS, out_dir=out, slug="lof001")
    return out


def _swap_cover(bundle):
    """Replace a delivered file with a different image of the same name."""
    victim = bundle / "lof001--spotify--3000x3000.jpg"
    Image.new("RGB", (3000, 3000), (200, 0, 0)).save(victim)
    return victim


class TestNothingCheckedIsNotClean:
    def test_a_bundle_with_no_manifest_is_not_ok(self, bundle):
        _swap_cover(bundle)
        (bundle / "manifest.json").unlink()
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.manifest_present is False
        assert result.hashes_verified is False
        assert result.ok is False

    def test_and_the_command_exits_non_zero(self, bundle, capsys):
        _swap_cover(bundle)
        (bundle / "manifest.json").unlink()
        assert main(["verify", str(bundle), "--only", "spotify,bandcamp"]) == 1
        assert "no manifest.json" in capsys.readouterr().out

    def test_a_real_bundle_still_passes(self, bundle):
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.ok is True
        assert result.hashes_verified is True

    def test_a_swapped_file_is_caught(self, bundle):
        _swap_cover(bundle)
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.checksum_mismatches
        assert result.ok is False


class TestPackageChecksWhatItStamps:
    def test_package_hashes_before_declaring_ok(self, bundle, tmp_path, capsys):
        # package ran a weaker check than verify and wrote its verdict into the
        # artefact: a swapped bundle failed verify and still shipped ok: true.
        _swap_cover(bundle)
        out = tmp_path / "pkg"
        main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"])
        assert not list(out.glob("*.zip")), "a bundle failing verify must not package"

    def test_the_summary_carries_no_absolute_path(self, bundle, tmp_path):
        out = tmp_path / "pkg"
        assert main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"]) == 0
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json").decode("utf-8"))
        assert summary["bundle"] == bundle.name
        assert str(tmp_path) not in json.dumps(summary)

    def test_the_summary_records_hash_findings(self, bundle, tmp_path):
        out = tmp_path / "pkg"
        main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"])
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json").decode("utf-8"))
        # Both were absent, so a mismatch left no trace in the shipped file.
        assert "bytes_mismatches" in summary
        assert "checksum_mismatches" in summary
        assert summary["hashes_verified"] is True


class TestSymlinks:
    def test_a_contact_sheet_refuses_to_write_through_one(
        self, tmp_path, master, capsys
    ):
        # Reproduced before the fix: this overwrote the text file with a JPEG.
        precious = tmp_path / "precious.txt"
        precious.write_text("irreplaceable")
        link = tmp_path / "sheet.jpg"
        link.symlink_to(precious)
        assert main(["sheet", str(master), "-o", str(link)]) != 0
        assert "symlink" in capsys.readouterr().err
        assert precious.read_text() == "irreplaceable"

    def test_a_package_refuses_a_dangling_link_at_its_path(self, bundle, tmp_path, capsys):
        # exists() follows the link and returns False for a dangling one, so the
        # name-picking loop chose it and the zip was written to its target.
        out = tmp_path / "pkg"
        out.mkdir()
        outside = tmp_path / "outside.zip"
        (out / "lof001.zip").symlink_to(outside)
        main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"])
        assert not outside.exists()

    def test_a_symlink_inside_a_bundle_is_not_copied_into_the_zip(
        self, bundle, tmp_path
    ):
        secret = tmp_path / "id_rsa"
        secret.write_text("PRIVATE KEY")
        (bundle / "id_rsa").symlink_to(secret)
        out = tmp_path / "pkg"
        main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"])
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            names = set(zf.namelist())
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json").decode("utf-8"))
        assert "id_rsa" not in names
        assert "id_rsa" in summary["skipped_symlinks"]


class TestManifestFilenamesAreUntrusted:
    def _retarget(self, bundle, value):
        path = bundle / "manifest.json"
        payload = json.loads(path.read_text())
        for entry in payload["outputs"]:
            if entry["target"] == "spotify":
                entry["file"] = value
        path.write_text(json.dumps(payload, indent=2))

    @pytest.mark.parametrize(
        "hostile",
        [
            "../outside--spotify--3000x3000.jpg",
            "../../etc/x--spotify--3000x3000.jpg",
            "sub/dir--spotify--3000x3000.jpg",
        ],
    )
    def test_a_path_is_refused(self, bundle, hostile):
        self._retarget(bundle, hostile)
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert any("not a plain name" in m for m in result.malformed_files)
        assert result.ok is False

    def test_an_absolute_path_is_refused(self, bundle, tmp_path):
        self._retarget(bundle, str(tmp_path / "x--spotify--3000x3000.jpg"))
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.ok is False

    def test_it_does_not_read_the_file_it_was_pointed_at(self, bundle, tmp_path):
        # The traversal was worse than a wrong verdict: verify opened, sized and
        # hashed the outside file and printed the result.
        outside = tmp_path / "outside--spotify--3000x3000.jpg"
        Image.new("RGB", (3000, 3000), (9, 9, 9)).save(outside)
        self._retarget(bundle, f"../{outside.name}")
        (bundle / "lof001--spotify--3000x3000.jpg").unlink()
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert "spotify" not in result.present_targets
        assert result.ok is False

    def test_a_symlinked_entry_is_refused(self, bundle, tmp_path):
        outside = tmp_path / "outside.jpg"
        Image.new("RGB", (3000, 3000), (9, 9, 9)).save(outside)
        target = bundle / "lof001--spotify--3000x3000.jpg"
        target.unlink()
        target.symlink_to(outside)
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert any("symlink" in m for m in result.malformed_files)
        assert result.ok is False


class TestMalformedManifestDoesNotCrash:
    def test_a_json_array_is_a_usage_error_not_a_traceback(self, bundle, capsys):
        (bundle / "manifest.json").write_text("[]")
        assert main(["verify", str(bundle), "--only", "spotify,bandcamp"]) == 2
        assert "failed" in capsys.readouterr().err


class TestTheManifestsOwnIntegrity:
    """capture_id is a hash of the manifest's contents, so it can be checked.

    Nothing checked it. Swap a delivery file, edit the manifest so its bytes and
    sha256 match the swap, leave capture_id alone, and verify said ok. The
    "hash-bound" claim only held against a manifest you already trusted, which
    is exactly the case a portable manifest exists to remove.
    """

    def _edit(self, bundle, mutate):
        path = bundle / "manifest.json"
        payload = json.loads(path.read_text())
        mutate(payload)
        path.write_text(json.dumps(payload, indent=2))
        return payload

    def test_an_untouched_manifest_matches_its_own_token(self, bundle):
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.capture_id_mismatch is False
        assert result.ok is True

    def test_an_edited_manifest_is_caught(self, bundle):
        self._edit(bundle, lambda p: p.__setitem__("slug", "someone-elses-record"))
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.capture_id_mismatch is True
        assert result.ok is False

    def test_rewriting_the_disclaimer_is_caught(self, bundle):
        # The boundary says these hashes do not establish ownership, rights or
        # approval. Inverting it is a claim made on the manifest's authority.
        self._edit(
            bundle,
            lambda p: p.__setitem__(
                "boundary", "This capture proves authorship and ownership."
            ),
        )
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.capture_id_mismatch is True
        assert result.ok is False

    def test_a_consistent_forgery_is_still_caught(self, bundle):
        # The realistic attack: swap the file, then edit bytes and sha256 to
        # match so every per-file check passes. Only the token disagrees.
        victim = _swap_cover(bundle)
        import hashlib

        digest = hashlib.sha256(victim.read_bytes()).hexdigest()

        def mutate(payload):
            for entry in payload["outputs"]:
                if entry["target"] == "spotify":
                    entry["bytes"] = victim.stat().st_size
                    entry["sha256"] = digest

        self._edit(bundle, mutate)
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert not result.checksum_mismatches, "the forgery is internally consistent"
        assert not result.bytes_mismatches
        assert result.capture_id_mismatch is True
        assert result.ok is False

    def test_the_command_says_what_happened(self, bundle, capsys):
        self._edit(bundle, lambda p: p.__setitem__("slug", "elsewhere"))
        assert main(["verify", str(bundle), "--only", "spotify,bandcamp"]) == 1
        assert "capture_id does not match" in capsys.readouterr().out

    def test_a_manifest_without_a_token_is_not_a_mismatch(self, bundle):
        # Older captures carry no capture_id. Nothing to check is not a failure.
        self._edit(bundle, lambda p: p.pop("capture_id", None))
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.capture_id_mismatch is False
        assert result.ok is True


class TestTheDiffComparesTheDisclaimer:
    def test_a_rewritten_boundary_is_not_identical(self, bundle, tmp_path):
        from coverforge.manifest import compare_manifests, load_manifest

        other = tmp_path / "copy"
        other.mkdir()
        payload = json.loads((bundle / "manifest.json").read_text())
        payload["boundary"] = "This capture proves authorship and ownership."
        (other / "manifest.json").write_text(json.dumps(payload, indent=2))

        left, left_path = load_manifest(bundle / "manifest.json")
        right, right_path = load_manifest(other / "manifest.json")
        diff = compare_manifests(left, right, left_path, right_path)
        assert diff["delta"]["boundary_changed"] is True
        assert diff["identical"] is False


class TestThePackageIsReproducible:
    """The same bundle must package to the same bytes.

    zf.write takes each member's mtime from the filesystem and zf.writestr
    stamps time.localtime(), so two packages of one bundle seconds apart hashed
    differently, and the difference moved with the local timezone. This repo
    already zeroes the ICC creation timestamp for the same reason: a rebuild
    that changes bytes has no stable identifier.
    """

    def test_two_packages_of_one_bundle_are_byte_identical(self, bundle, tmp_path):
        import hashlib

        digests = []
        for name in ("first", "second"):
            out = tmp_path / name
            assert main(
                ["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"]
            ) == 0
            zip_path = next(out.glob("*.zip"))
            digests.append(hashlib.sha256(zip_path.read_bytes()).hexdigest())
        assert digests[0] == digests[1]

    def test_the_members_carry_no_wall_clock_time(self, bundle, tmp_path):
        out = tmp_path / "pkg"
        main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"])
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            stamps = {info.date_time for info in zf.infolist()}
        assert stamps == {(1980, 1, 1, 0, 0, 0)}

    def test_the_contents_are_still_readable(self, bundle, tmp_path):
        out = tmp_path / "pkg"
        main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"])
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            assert zf.testzip() is None
            names = set(zf.namelist())
            assert "manifest.json" in names
            payload = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert payload["slug"] == "lof001"


class TestAMalformedManifestIsNotIdentical:
    """Damage on both sides used to cancel out.

    Sections of the wrong shape were replaced with empty ones and nothing
    recorded it, so two manifests whose outputs array was unreadable compared
    as "identical captures" with exit 0. Neither had been read.
    """

    def _damage(self, path):
        payload = json.loads(path.read_text())
        payload["outputs"] = None
        payload["source"] = "master.png"
        payload["findings"] = "see notes"
        path.write_text(json.dumps(payload, indent=2))

    def _diff(self, left, right):
        from coverforge.manifest import compare_manifests, load_manifest

        lp, lpath = load_manifest(left)
        rp, rpath = load_manifest(right)
        return compare_manifests(lp, rp, lpath, rpath)

    def test_two_damaged_manifests_are_not_identical(self, bundle, tmp_path):
        other = tmp_path / "copy"
        other.mkdir()
        (other / "manifest.json").write_text((bundle / "manifest.json").read_text())
        self._damage(bundle / "manifest.json")
        self._damage(other / "manifest.json")

        diff = self._diff(bundle / "manifest.json", other / "manifest.json")
        assert diff["identical"] is False
        assert diff["delta"]["output_issues"]

    def test_each_damaged_section_is_named(self, bundle, tmp_path):
        other = tmp_path / "copy"
        other.mkdir()
        (other / "manifest.json").write_text((bundle / "manifest.json").read_text())
        self._damage(bundle / "manifest.json")
        self._damage(other / "manifest.json")

        issues = " ".join(self._diff(bundle / "manifest.json", other / "manifest.json")["delta"]["output_issues"])
        assert "outputs is null" in issues
        assert "source is not an object" in issues
        assert "findings is not a list" in issues

    def test_the_command_exits_non_zero(self, bundle, tmp_path, capsys):
        other = tmp_path / "copy"
        other.mkdir()
        (other / "manifest.json").write_text((bundle / "manifest.json").read_text())
        self._damage(bundle / "manifest.json")
        self._damage(other / "manifest.json")

        code = main(["manifest", str(bundle / "manifest.json"), str(other / "manifest.json")])
        out = capsys.readouterr().out
        assert code != 0
        assert "identical captures" not in out

    def test_two_healthy_manifests_are_still_identical(self, bundle, tmp_path):
        other = tmp_path / "copy"
        other.mkdir()
        (other / "manifest.json").write_text((bundle / "manifest.json").read_text())
        diff = self._diff(bundle / "manifest.json", other / "manifest.json")
        assert diff["identical"] is True
        assert not diff["delta"]["output_issues"]

    def test_the_outputs_line_is_not_called_source_outputs(self, bundle, tmp_path, capsys):
        other = tmp_path / "copy"
        other.mkdir()
        (other / "manifest.json").write_text((bundle / "manifest.json").read_text())
        main(["manifest", str(bundle / "manifest.json"), str(other / "manifest.json")])
        out = capsys.readouterr().out
        assert "source outputs:" not in out
        assert "outputs:" in out


class TestAnUntaggedBuildSaysSo:
    """The sRGB profile is built once at import and embedded only `if
    SRGB_BYTES`. When ImageCms cannot create one that test silently skips, so
    every output shipped untagged while the build reported no warning at all.

    Two things rest on that profile being there. Untagged artwork is
    interpreted differently from platform to platform, which is the whole
    reason this tool converts colour. And the repo's byte-reproducibility
    guarantee assumes the profile is embedded with its timestamp zeroed, so a
    silently untagged build changes every hash with nothing to explain why.
    """

    def _build(self, master, tmp_path, name):
        return build(inspect(master), TARGETS, out_dir=tmp_path / name, slug="lof001")

    def test_a_normal_build_tags_its_outputs_and_says_nothing(self, master, tmp_path):
        result = self._build(master, tmp_path, "tagged")
        with Image.open(result.outputs[0].path) as im:
            assert im.info.get("icc_profile")
        assert not [f for f in result.findings if f.code == "srgb-profile-unavailable"]

    def test_an_untagged_build_warns(self, master, tmp_path, monkeypatch):
        monkeypatch.setattr(imageops, "SRGB_BYTES", None)
        result = self._build(master, tmp_path, "untagged")
        warned = [f for f in result.findings if f.code == "srgb-profile-unavailable"]
        assert warned, "an untagged build reported nothing"
        assert warned[0].level == WARN

    def test_the_warning_is_not_an_error_that_blocks_the_build(
        self, master, tmp_path, monkeypatch
    ):
        # Untagged output is worse than tagged, not unusable. The files still
        # have to be written, or a machine without ImageCms could not deliver
        # at all.
        monkeypatch.setattr(imageops, "SRGB_BYTES", None)
        result = self._build(master, tmp_path, "still_writes")
        assert result.outputs
        assert all(f.level != ERROR for f in result.findings)

    def test_the_untagged_files_really_carry_no_profile(self, master, tmp_path, monkeypatch):
        # The warning has to describe what actually happened, not stand in for
        # a check nobody made.
        monkeypatch.setattr(imageops, "SRGB_BYTES", None)
        result = self._build(master, tmp_path, "verify_untagged")
        for output in result.outputs:
            with Image.open(output.path) as im:
                assert not im.info.get("icc_profile"), output.path.name


class TestAColourTransformThatDidNotHappenSaysSo:
    """The tool told the user a conversion would happen, then did not.

    inspect() records 'unreadable ICC profile' when a profile will not parse.
    preflight then emitted `tagged 'unreadable ICC profile'; will be converted
    to sRGB` at INFO, promising a transform it had already established was
    impossible, and _to_srgb failed on the same profile and quietly plain
    converted. Nothing corrected the promise.

    Proved by instrumenting the real path: profileToProfile was attempted zero
    times, because the profile fails to load before the transform is reached.
    """

    @pytest.fixture
    def broken_icc(self, tmp_path):
        path = tmp_path / "broken.png"
        Image.new("RGB", (4000, 4000), (10, 120, 60)).save(
            path, icc_profile=b"NOTAPROFILE" * 45
        )
        return path

    def test_an_unreadable_profile_is_a_warning_not_a_promise(self, broken_icc):
        findings = check(inspect(broken_icc), TARGETS, "#ffffff", False)
        icc = [f for f in findings if f.code in ("icc", "icc-unreadable")]
        assert icc, "nothing said anything about the profile at all"
        assert icc[0].code == "icc-unreadable"
        assert icc[0].level == WARN
        assert "will be converted" not in icc[0].message

    def test_the_build_reports_the_transform_it_could_not_do(self, broken_icc, tmp_path):
        result = build(inspect(broken_icc), TARGETS, out_dir=tmp_path / "b", slug="x")
        codes = [f.code for f in result.findings if f.level == WARN]
        assert "colour-transform-degraded" in codes

    def test_a_clean_master_says_none_of_this(self, master, tmp_path):
        result = build(inspect(master), TARGETS, out_dir=tmp_path / "c", slug="x")
        codes = [f.code for f in result.findings]
        assert "colour-transform-degraded" not in codes
        assert "icc-unreadable" not in codes

    def test_the_build_still_delivers(self, broken_icc, tmp_path):
        # Degraded colour is worse than converted colour, not a reason to
        # refuse to produce anything.
        result = build(inspect(broken_icc), TARGETS, out_dir=tmp_path / "d", slug="x")
        assert result.outputs
        assert all(f.level != ERROR for f in result.findings)

    def test_normalise_reports_nothing_when_it_had_nothing_to_report(self, master):
        notes: list[str] = []
        imageops.normalise(master, notes=notes)
        assert notes == []


# Every field name that must, on its own, stop a bundle being certified ok.
_BLOCKING_LISTS = [
    "missing_targets",
    "malformed_files",
    "missing_files",
    "bytes_mismatches",
    "checksum_mismatches",
    "dimension_mismatches",
    "format_mismatches",
]


def _clean_audit(**overrides):
    """A BundleAudit with nothing wrong with it, plus whatever is overridden."""
    fields = dict(
        bundle=Path("delivery"),
        slug="lof001",
        checked_targets=["spotify"],
        present_targets=["spotify"],
        missing_targets=[],
        extra_targets=[],
        malformed_files=[],
        missing_files=[],
        bytes_mismatches=[],
        checksum_mismatches=[],
        dimension_mismatches=[],
        format_mismatches=[],
        manifest_present=True,
        capture_id_mismatch=False,
        hashes_verified=True,
    )
    fields.update(overrides)
    return BundleAudit(**fields)


class TestEveryFailureBlocksOkOnItsOwn:
    """Each condition in ok() is pinned separately, because the suite could not
    tell if one were dropped.

    Found by mutation, not by reading: removing any one of the seven list
    terms from the ok() disjunction left all 41 tests passing. The existing
    checksum test asserts `ok is False` after swapping a delivered file, but
    the swap also changes the byte count, so bytes_mismatches fires and masks
    the term the test is named for. That is exactly the failure this repo has
    a note about, on the function that certifies a bundle to a client.

    The code was correct throughout. What was missing was anything that would
    notice if it stopped being.
    """

    def test_a_clean_audit_is_ok(self):
        assert _clean_audit().ok is True

    @pytest.mark.parametrize("field", _BLOCKING_LISTS)
    def test_each_failure_list_blocks_ok_alone(self, field):
        # One field set, everything else clean, so nothing else can mask it.
        assert _clean_audit(**{field: ["something wrong"]}).ok is False, field

    def test_a_missing_manifest_blocks_ok_alone(self):
        assert _clean_audit(manifest_present=False).ok is False

    def test_a_capture_id_mismatch_blocks_ok_alone(self):
        assert _clean_audit(capture_id_mismatch=True).ok is False

    def test_extra_targets_alone_do_not_block(self):
        # Deliberately not blocking: an extra file in the folder is worth
        # reporting but is not a defect in what was delivered. Pinned so the
        # decision is visible rather than incidental.
        assert _clean_audit(extra_targets=["stray.jpg"]).ok is True


# One payload edit per difference category compare_manifests reports, each
# touching nothing else so no sibling term can mask it.
def _one_difference(payload, kind):
    p = copy.deepcopy(payload)
    if kind == "schema_changed":
        p["schema_version"] = (p.get("schema_version") or 0) + 1
    elif kind == "generator_changed":
        p["generated_by"] = "something else"
    elif kind == "slug_changed":
        p["slug"] = "a-different-slug"
    elif kind == "capture_id_changed":
        p["capture_id"] = "0" * 64
    elif kind == "left_sources":
        p["source"]["sha256"] = "1" * 64
    elif kind == "changed_skipped":
        p["skipped"] = list(p["skipped"]) + [{"target": "beatport", "reason": "test"}]
    elif kind == "changed_findings":
        p["findings"] = list(p["findings"]) + [
            {"level": "info", "code": "test", "message": "test", "target": None}
        ]
    elif kind == "added_outputs":
        extra = copy.deepcopy(p["outputs"][0])
        extra["target"] = "a-target-that-was-not-there"
        p["outputs"] = list(p["outputs"]) + [extra]
    elif kind == "removed_outputs":
        p["outputs"] = list(p["outputs"])[:-1]
    elif kind == "changed_outputs":
        p["outputs"][0]["bytes"] = (p["outputs"][0]["bytes"] or 0) + 1
    else:
        raise AssertionError(f"unknown difference kind {kind}")
    return p


_DIFFERENCE_KINDS = [
    "schema_changed",
    "generator_changed",
    "slug_changed",
    "capture_id_changed",
    "left_sources",
    "changed_skipped",
    "changed_findings",
    "added_outputs",
    "removed_outputs",
    "changed_outputs",
]


class TestEveryDifferenceStopsTwoManifestsBeingIdentical:
    """Each term in has_issues is pinned separately.

    Found by mutation, the same way as the audit one. Ten of the twelve terms
    could be removed from has_issues with every manifest test still passing:
    only boundary_changed and output_issues were pinned, and both of those had
    been added deliberately. So a build that dropped, say, added_outputs would
    have reported two manifests with different output lists as "identical
    captures", and the suite would not have said a word.

    The code was correct. Nothing would have noticed if it stopped being.
    """

    @pytest.fixture
    def payload(self, bundle):
        return json.loads((bundle / "manifest.json").read_text())

    def test_a_manifest_is_identical_to_itself(self, payload, bundle):
        diff = compare_manifests(payload, copy.deepcopy(payload), bundle, bundle)
        assert diff["identical"] is True

    @pytest.mark.parametrize("kind", _DIFFERENCE_KINDS)
    def test_one_difference_is_enough(self, payload, bundle, kind):
        other = _one_difference(payload, kind)
        assert other != payload, f"{kind} did not actually change the payload"
        diff = compare_manifests(payload, other, bundle, bundle)
        assert diff["identical"] is False, kind
