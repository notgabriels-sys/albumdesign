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
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from coverforge import audit as audit_module
from coverforge import imageops
from coverforge.audit import BundleAudit, parse_manifest_json, run_audit
from coverforge.build import build, manifest_capture_id
from coverforge.manifest import compare_manifests, load_manifest
from coverforge.cli import main
from coverforge.imageops import ImageError, inspect
from coverforge.package import PackageError, build_package
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
    def test_public_audit_rejects_an_invalid_programmatic_target(self, tmp_path):
        invalid = replace(TARGETS[0], max_bytes="not-an-integer")

        with pytest.raises(ValueError, match="max_bytes must be"):
            run_audit([tmp_path / "missing"], [invalid], verify_hashes=True)

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
        assert result.package_members == {}

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

    def test_low_level_packaging_rejects_an_audit_that_did_not_hash_files(
        self, bundle, tmp_path
    ):
        unchecked = run_audit(
            [bundle],
            TARGETS,
            verify_hashes=False,
            capture_package_bytes=True,
        )[0]

        with pytest.raises(PackageError, match="verified delivery-file hashes"):
            build_package(unchecked, tmp_path / "unchecked.zip")

    def test_an_edited_delivery_note_is_not_part_of_the_manifest_bound_zip(
        self, bundle, tmp_path
    ):
        secret = "/Users/name/private/client-notes"
        (bundle / "DELIVERY.md").write_text(secret, encoding="utf-8")
        out = tmp_path / "pkg"

        assert main(["package", str(bundle), "-o", str(out), "--only", "spotify,bandcamp"]) == 0
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            names = set(zf.namelist())
            all_bytes = b"\n".join(zf.read(name) for name in names)

        assert "DELIVERY.md" not in names
        assert secret.encode() not in all_bytes

    def test_an_oversized_manifest_inventory_cannot_leave_a_package_snapshot(
        self, bundle, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(audit_module, "_MAX_MANIFEST_OUTPUTS", 1)

        audited = run_audit(
            [bundle],
            TARGETS,
            verify_hashes=True,
            capture_package_bytes=True,
        )[0]

        assert audited.manifest_valid is False
        assert len(audited.manifest_files) == 1
        assert audited.package_members == {}
        finding = next(
            finding
            for finding in audited.malformed_files
            if "outputs contains 2 entries; maximum is 1" in finding
        )
        assert str(tmp_path) not in finding
        with pytest.raises(PackageError, match="valid package inventory"):
            build_package(audited, tmp_path / "oversized-inventory.zip")

    def test_a_snapshot_byte_overflow_clears_every_captured_member(
        self, bundle, tmp_path, monkeypatch
    ):
        manifest_path = bundle / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_size = manifest_path.stat().st_size
        first_output_size = (bundle / payload["outputs"][0]["file"]).stat().st_size
        snapshot_limit = manifest_size + first_output_size
        monkeypatch.setattr(
            audit_module,
            "_MAX_CAPTURED_BUNDLE_BYTES",
            snapshot_limit,
        )

        audited = run_audit(
            [bundle],
            TARGETS,
            verify_hashes=True,
            capture_package_bytes=True,
        )[0]

        assert audited.manifest_valid is False
        assert audited.package_members == {}
        finding = next(
            finding
            for finding in audited.malformed_files
            if f"package snapshot exceeds the {snapshot_limit}-byte per-bundle safety limit"
            in finding
        )
        assert str(tmp_path) not in finding
        with pytest.raises(PackageError, match="valid package inventory"):
            build_package(audited, tmp_path / "oversized-snapshot.zip")

    def test_a_manifest_has_a_small_dedicated_read_limit(
        self, bundle, monkeypatch
    ):
        manifest = bundle / "manifest.json"
        monkeypatch.setattr(
            audit_module, "MAX_MANIFEST_FILE_BYTES", manifest.stat().st_size - 1
        )

        with pytest.raises(ValueError, match="byte safety limit"):
            run_audit([bundle], TARGETS, verify_hashes=True)
        with pytest.raises(ValueError, match="byte safety limit"):
            load_manifest(manifest)

    def test_deep_json_is_reported_as_a_bounded_manifest_error(self):
        nested = '{"value":' * 10_000 + "0" + "}" * 10_000

        with pytest.raises(ValueError, match="nesting exceeds"):
            parse_manifest_json(nested)

    def test_a_late_invalid_bundle_leaves_no_partial_package_batch(
        self, bundle, tmp_path, capsys
    ):
        invalid = tmp_path / "delivery-invalid"
        shutil.copytree(bundle, invalid)
        (invalid / "manifest.json").write_text("{", encoding="utf-8")
        out = tmp_path / "packages"

        assert (
            main(
                [
                    "package",
                    str(bundle),
                    str(invalid),
                    "-o",
                    str(out),
                    "--only",
                    "spotify,bandcamp",
                ]
            )
            == 2
        )

        assert list(out.glob("*.zip")) == []
        assert list(out.glob(".coverforge-*")) == []
        assert "package failed" in capsys.readouterr().err

    def test_a_crowded_bundle_cannot_grow_a_forced_package_summary_without_bound(
        self, bundle, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(audit_module, "MAX_BUNDLE_ENTRIES", 2)

        audited = run_audit(
            [bundle],
            TARGETS,
            verify_hashes=True,
            capture_package_bytes=True,
        )[0]

        assert audited.manifest_valid is False
        assert audited.package_members == {}
        finding = next(
            item
            for item in audited.malformed_files
            if "more than 2 directory entries" in item
        )
        assert str(tmp_path) not in finding
        with pytest.raises(PackageError, match="valid package inventory"):
            build_package(audited, tmp_path / "crowded.zip")


class TestSymlinks:
    @pytest.mark.parametrize("metadata_name", ["manifest.json", "DELIVERY.md"])
    def test_a_build_refuses_to_write_metadata_through_a_symlink(
        self, metadata_name, tmp_path, master
    ):
        out = tmp_path / "delivery"
        out.mkdir()
        precious = tmp_path / f"precious-{metadata_name}"
        precious.write_text("keep this", encoding="utf-8")
        (out / metadata_name).symlink_to(precious)

        with pytest.raises(ImageError, match="symlink"):
            build(inspect(master), TARGETS, out_dir=out, slug="lof001")

        assert precious.read_text(encoding="utf-8") == "keep this"

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

    def test_a_symlinked_manifest_is_not_treated_as_a_real_bundle_manifest(
        self, bundle, tmp_path, capsys
    ):
        outside = tmp_path / "outside-manifest.json"
        (bundle / "manifest.json").replace(outside)
        (bundle / "manifest.json").symlink_to(outside)
        out = tmp_path / "pkg"

        assert (
            main(
                [
                    "package",
                    str(bundle),
                    "-o",
                    str(out),
                    "--only",
                    "spotify,bandcamp",
                ]
            )
            == 2
        )
        assert "symlink" in capsys.readouterr().err
        assert list(out.glob("*.zip")) == []

    def test_bundle_discovery_does_not_follow_a_symlinked_child(
        self, bundle, tmp_path
    ):
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / "outside-bundle").symlink_to(bundle, target_is_directory=True)

        with pytest.raises(FileNotFoundError, match="no delivery bundle"):
            run_audit([parent], TARGETS, verify_hashes=True)


class TestManifestDrivenPackageInventory:
    def test_unmanifested_regular_files_block_a_clean_audit(self, bundle):
        (bundle / "private-notes.txt").write_text("do not send", encoding="utf-8")

        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        payload = result.as_dict()

        assert payload.get("unmanifested_files") == ["private-notes.txt"]
        assert result.ok is False

    def test_force_never_puts_unmanifested_regular_files_in_the_zip(
        self, bundle, tmp_path
    ):
        (bundle / "private-notes.txt").write_text("do not send", encoding="utf-8")
        stale = bundle / "stale--spotify--3000x3000.jpg"
        Image.new("RGB", (3000, 3000), "red").save(stale)
        out = tmp_path / "pkg"

        assert (
            main(
                [
                    "package",
                    str(bundle),
                    "-o",
                    str(out),
                    "--only",
                    "spotify,bandcamp",
                    "--force",
                ]
            )
            == 1
        )
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            names = set(zf.namelist())
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json"))

        assert "private-notes.txt" not in names
        assert stale.name not in names
        assert summary.get("unmanifested_files") == [
            "private-notes.txt",
            stale.name,
        ]

    def test_package_output_must_not_be_inside_the_bundle(self, bundle, capsys):
        assert (
            main(
                [
                    "package",
                    str(bundle),
                    "-o",
                    str(bundle),
                    "--only",
                    "spotify,bandcamp",
                ]
            )
            == 2
        )
        assert "inside" in capsys.readouterr().err
        assert list(bundle.glob("*.zip")) == []

    def test_rejected_nested_output_does_not_create_a_directory(
        self, bundle, capsys
    ):
        nested = bundle / "new-packages"

        assert main(["package", str(bundle), "-o", str(nested)]) == 2
        assert "inside" in capsys.readouterr().err
        assert not nested.exists()

    def test_summary_hashes_the_exact_bytes_written_to_each_zip_member(
        self, bundle, tmp_path
    ):
        victim = bundle / "lof001--spotify--3000x3000.jpg"
        audited = run_audit(
            [bundle],
            TARGETS,
            verify_hashes=True,
            capture_package_bytes=True,
        )[0]
        audited_bytes = victim.read_bytes()
        victim.unlink()
        victim.symlink_to(bundle / "lof001--bandcamp--3000x3000.jpg")

        zip_path = tmp_path / "pkg.zip"
        result = build_package(audited, zip_path)
        assert result.ok is True

        with zipfile.ZipFile(zip_path) as zf:
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json"))
            recorded = {item["name"]: item for item in summary["files"]}
            archived = zf.read(victim.name)

        assert archived == audited_bytes
        assert victim.name not in summary["skipped_symlinks"]
        assert recorded[victim.name]["bytes"] == len(archived)
        assert recorded[victim.name]["sha256"] == hashlib.sha256(archived).hexdigest()

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
    def test_a_fifo_cannot_hang_packaging_or_leak_its_local_path(
        self, bundle, tmp_path
    ):
        victim = bundle / "lof001--spotify--3000x3000.jpg"
        victim.unlink()
        os.mkfifo(victim)
        out = tmp_path / "pkg"

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverforge.cli",
                "package",
                str(bundle),
                "-o",
                str(out),
                "--only",
                "spotify,bandcamp",
                "--force",
            ],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        assert completed.returncode == 1, completed.stderr
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json"))
        assert str(tmp_path) not in json.dumps(summary)

    def test_force_hashes_corrupt_bytes_before_image_decode(
        self, bundle, tmp_path
    ):
        victim = bundle / "lof001--spotify--3000x3000.jpg"
        victim.write_bytes(b"not an image")
        out = tmp_path / "pkg-corrupt"

        assert (
            main(
                [
                    "package",
                    str(bundle),
                    "-o",
                    str(out),
                    "--only",
                    "spotify,bandcamp",
                    "--force",
                ]
            )
            == 1
        )
        with zipfile.ZipFile(next(out.glob("*.zip"))) as zf:
            summary = json.loads(zf.read("COVERFORGE_PACKAGE.json"))
            assert zf.read(victim.name) == b"not an image"

        assert summary["hashes_verified"] is True
        assert summary["checksum_mismatches"]
        assert any(victim.name in item for item in summary["malformed_files"])
        diagnostics = " ".join(summary["malformed_files"])
        assert "image decode failed: UnidentifiedImageError" in diagnostics
        assert "BytesIO" not in diagnostics


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
            "..\\outside--spotify--3000x3000.jpg",
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


class TestSchemaOneInventoryValidation:
    def _rewrite(self, bundle, mutate, *, recapture=True):
        path = bundle / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        if recapture:
            payload["capture_id"] = manifest_capture_id(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _audit(self, bundle):
        return run_audit([bundle], TARGETS, verify_hashes=True)[0]

    def test_schema_one_without_its_capture_id_is_not_clean(self, bundle):
        self._rewrite(bundle, lambda payload: payload.pop("capture_id"), recapture=False)

        result = self._audit(bundle)

        assert result.as_dict().get("manifest_valid") is False
        assert result.ok is False

    def test_boolean_true_is_not_schema_version_one(self, bundle):
        self._rewrite(bundle, lambda payload: payload.__setitem__("schema_version", True))

        result = self._audit(bundle)

        assert result.manifest_valid is False
        assert any("schema_version must be integer 1" in item for item in result.malformed_files)

    def test_schema_one_rejects_an_unknown_root_field_that_could_leak_a_path(
        self, bundle
    ):
        self._rewrite(
            bundle,
            lambda payload: payload.__setitem__("local_path", "/Users/name/private"),
        )

        result = self._audit(bundle)

        assert result.as_dict().get("manifest_valid") is False
        assert any("unexpected root field" in item for item in result.malformed_files)

    def test_schema_one_requires_every_output_field(self, bundle):
        self._rewrite(bundle, lambda payload: payload["outputs"][0].pop("name"))

        result = self._audit(bundle)

        assert result.as_dict().get("manifest_valid") is False
        assert any("missing output field" in item for item in result.malformed_files)

    def test_display_size_must_match_the_numeric_byte_count(self, bundle):
        self._rewrite(
            bundle,
            lambda payload: payload["outputs"][0].__setitem__("size", "999 TB"),
        )

        result = self._audit(bundle)

        assert result.manifest_valid is False
        assert any("size does not match" in item for item in result.malformed_files)

    def test_one_file_cannot_satisfy_two_manifest_targets(self, bundle):
        def duplicate(payload):
            first, second = payload["outputs"][:2]
            second["file"] = first["file"]
            data = (bundle / first["file"]).read_bytes()
            second["bytes"] = len(data)
            second["sha256"] = hashlib.sha256(data).hexdigest()

        self._rewrite(bundle, duplicate)

        result = self._audit(bundle)

        assert result.as_dict().get("manifest_valid") is False
        assert any("duplicate manifest filename" in item for item in result.malformed_files)

    def test_a_symlinked_first_entry_cannot_hide_a_duplicate_target(
        self, bundle
    ):
        def duplicate(payload):
            first = copy.deepcopy(payload["outputs"][0])
            first["dimensions"] = "2999x2999"
            first["file"] = first["file"].replace("3000x3000", "2999x2999")
            (bundle / first["file"]).symlink_to(payload["outputs"][0]["file"])
            payload["outputs"].insert(0, first)

        self._rewrite(bundle, duplicate)

        result = self._audit(bundle)

        assert result.manifest_valid is False
        assert any("duplicate manifest target" in item for item in result.malformed_files)

    def test_one_target_cannot_be_both_produced_and_skipped(self, bundle):
        def contradict(payload):
            payload["skipped"].append(
                {
                    "target": payload["outputs"][0]["target"],
                    "reason": "contradictory inventory",
                }
            )

        self._rewrite(bundle, contradict)

        result = self._audit(bundle)

        assert result.manifest_valid is False
        assert any("both outputs and skipped" in item for item in result.malformed_files)

    def test_target_case_cannot_hide_an_output_skipped_collision(self, bundle):
        def contradict(payload):
            payload["skipped"].append(
                {
                    "target": payload["outputs"][0]["target"].upper(),
                    "reason": "case-variant contradictory inventory",
                }
            )

        self._rewrite(bundle, contradict)

        result = self._audit(bundle)

        assert result.manifest_valid is False
        assert any("both outputs and skipped" in item for item in result.malformed_files)

    def test_manifest_targets_must_match_the_target_in_each_filename(self, bundle):
        def swap(payload):
            first, second = payload["outputs"][:2]
            first["file"], second["file"] = second["file"], first["file"]
            for item in (first, second):
                data = (bundle / item["file"]).read_bytes()
                item["bytes"] = len(data)
                item["sha256"] = hashlib.sha256(data).hexdigest()

        self._rewrite(bundle, swap)

        result = self._audit(bundle)

        assert result.as_dict().get("manifest_valid") is False
        assert any("does not match manifest target" in item for item in result.malformed_files)

    def test_manifest_slug_must_match_every_output_filename(self, bundle):
        self._rewrite(bundle, lambda payload: payload.__setitem__("slug", "someone-else"))

        result = self._audit(bundle)

        assert result.as_dict().get("manifest_valid") is False
        assert any("does not match manifest slug" in item for item in result.malformed_files)

    def test_actual_image_encoding_must_match_the_claimed_format(self, bundle):
        victim = bundle / "lof001--spotify--3000x3000.jpg"
        Image.new("RGB", (3000, 3000), "green").save(victim, format="PNG")

        def update(payload):
            entry = next(item for item in payload["outputs"] if item["target"] == "spotify")
            data = victim.read_bytes()
            entry["bytes"] = len(data)
            entry["sha256"] = hashlib.sha256(data).hexdigest()

        self._rewrite(bundle, update)

        result = self._audit(bundle)

        assert result.format_mismatches
        assert result.ok is False

    def test_two_empty_json_objects_are_not_identical_manifest_captures(self):
        result = compare_manifests({}, {}, Path("left.json"), Path("right.json"))

        assert result["identical"] is False
        assert result["delta"]["output_issues"]

    def test_coverforge_generated_hyphenated_target_verifies_and_packages(
        self, master, tmp_path, capsys
    ):
        spec = tmp_path / "targets.toml"
        spec.write_text(
            """
[targets.artist-store]
name = "Artist store"
group = "direct"
width = 3000
height = 3000
format = "jpeg"
""".strip(),
            encoding="utf-8",
        )
        bundle = tmp_path / "hyphenated"
        common = ["--targets-file", str(spec)]

        assert main(["build", str(master), "-o", str(bundle), *common]) == 0
        assert main(["verify", str(bundle), *common]) == 0
        assert main(["package", str(bundle), "-o", str(tmp_path / "pkg"), *common]) == 0

        capsys.readouterr()
        (bundle / "manifest.json").unlink()
        assert main(["verify", str(bundle), *common]) == 1
        assert "no manifest.json" in capsys.readouterr().out

    def test_a_build_time_size_cap_finding_stays_blocking(
        self, master, tmp_path, capsys
    ):
        spec = tmp_path / "tiny-cap.toml"
        spec.write_text(
            """
[targets.tiny-cap]
name = "Tiny capped target"
group = "test"
width = 64
height = 64
format = "jpeg"
max_bytes = 1
""".strip(),
            encoding="utf-8",
        )
        bundle = tmp_path / "over-cap"
        common = ["--targets-file", str(spec)]

        assert main(["build", str(master), "-o", str(bundle), *common]) == 1
        capsys.readouterr()
        assert main(["verify", str(bundle), *common]) == 1
        assert "size cap exceeded" in capsys.readouterr().out

        package_out = tmp_path / "pkg-over-cap"
        assert main(["package", str(bundle), "-o", str(package_out), *common]) == 1
        assert list(package_out.glob("*.zip")) == []

    def test_duplicate_json_keys_cannot_hide_private_text_in_a_package(
        self, bundle, tmp_path, capsys
    ):
        path = bundle / "manifest.json"
        raw = path.read_text(encoding="utf-8")
        path.write_text(
            raw.replace("{", '{\n  "slug": "/Users/name/private",', 1),
            encoding="utf-8",
        )
        out = tmp_path / "pkg"

        assert main(["package", str(bundle), "-o", str(out), "--force"]) == 2
        assert "duplicate JSON key: slug" in capsys.readouterr().err
        assert list(out.glob("*.zip")) == []


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
        # A missing value cannot disagree, but schema version 1 requires one.
        self._edit(bundle, lambda p: p.pop("capture_id", None))
        result = run_audit([bundle], TARGETS, verify_hashes=True)[0]
        assert result.capture_id_mismatch is False
        assert result.manifest_valid is False
        assert result.ok is False

    def test_force_cannot_package_a_capture_id_mismatch(
        self, bundle, tmp_path, capsys
    ):
        self._edit(
            bundle,
            lambda payload: payload["outputs"][0].__setitem__(
                "name", "Edited without recapturing"
            ),
        )
        out = tmp_path / "pkg"

        assert main(["package", str(bundle), "-o", str(out), "--force"]) == 2
        assert "valid package inventory" in capsys.readouterr().err
        assert list(out.glob("*.zip")) == []


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

    def test_the_same_missing_nested_field_on_both_sides_is_not_identical(
        self, bundle, tmp_path
    ):
        other = tmp_path / "copy"
        other.mkdir()
        for destination in (bundle / "manifest.json", other / "manifest.json"):
            payload = json.loads((bundle / "manifest.json").read_text())
            payload["outputs"][0].pop("name", None)
            destination.write_text(json.dumps(payload), encoding="utf-8")

        diff = self._diff(bundle / "manifest.json", other / "manifest.json")
        assert diff["identical"] is False
        assert any(
            "missing output field: name" in item
            for item in diff["delta"]["output_issues"]
        )

    def test_the_same_duplicate_filename_on_both_sides_is_not_identical(
        self, bundle, tmp_path
    ):
        payload = json.loads((bundle / "manifest.json").read_text())
        payload["outputs"][1]["file"] = payload["outputs"][0]["file"]
        payload["capture_id"] = manifest_capture_id(payload)
        other = tmp_path / "copy"
        other.mkdir()
        for path in (bundle / "manifest.json", other / "manifest.json"):
            path.write_text(json.dumps(payload), encoding="utf-8")

        diff = self._diff(bundle / "manifest.json", other / "manifest.json")
        assert diff["identical"] is False
        assert any(
            "duplicate manifest filename" in item
            for item in diff["delta"]["output_issues"]
        )

    def test_two_identically_edited_capture_ids_are_not_called_identical(
        self, bundle, tmp_path
    ):
        payload = json.loads((bundle / "manifest.json").read_text())
        payload["outputs"][0]["name"] = "Edited without recapturing"
        other = tmp_path / "copy"
        other.mkdir()
        for path in (bundle / "manifest.json", other / "manifest.json"):
            path.write_text(json.dumps(payload), encoding="utf-8")

        diff = self._diff(bundle / "manifest.json", other / "manifest.json")
        assert diff["identical"] is False
        assert any(
            "capture_id does not match" in item
            for item in diff["delta"]["output_issues"]
        )

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
    "unmanifested_files",
    "size_cap_exceeded",
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

    def test_an_invalid_manifest_blocks_ok_alone(self):
        assert _clean_audit(manifest_valid=False).ok is False

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


class TestVerifyExitsNonZeroWhenNothingWasVerified:
    """The text-mode exit gate had no test, and it is the one scripts read.

    `if not result.ok: exit_code = EXIT_FINDINGS` in the verify command was
    added because a bundle that is not ok for a reason none of the individual
    lists covers, above all a missing manifest, printed "findings" and still
    exited 0. Removing that line again leaves every test passing, because the
    per-list gates below it fire for every case the suite exercises.

    Reproduced before writing this: a complete bundle with only manifest.json
    deleted prints the "no manifest.json" line either way, and exits 1 with the
    gate and 0 without it. The human output says findings while the status says
    pass, which is the worse half of the two.
    """

    @pytest.fixture
    def unmanifested(self, tmp_path, master):
        # Every target present and correct, so no per-list gate can fire and
        # mask the one being tested.
        out = tmp_path / "complete"
        build(inspect(master), TARGETS, out_dir=out, slug="lof001")
        (out / "manifest.json").unlink()
        return out

    def test_text_mode_exits_non_zero(self, unmanifested, capsys):
        # Scoped to the targets actually built. Without --only, verify checks
        # all ten and the eight absent ones fire missing_targets, which masks
        # the gate under test. That is the same shadowing this whole class is
        # about, and it caught this test out before it caught anything else.
        code = main(["verify", str(unmanifested), "--only", "spotify,bandcamp"])
        out = capsys.readouterr().out
        assert "no manifest.json" in out, "it did not even notice"
        assert code != 0, "printed findings and exited 0; a script would call this a pass"

    def test_json_mode_exits_non_zero_too(self, unmanifested, capsys):
        code = main(
            ["verify", str(unmanifested), "--only", "spotify,bandcamp", "--json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["bundles"][0]["ok"] is False
        assert code != 0

    def test_the_lists_really_are_empty_so_nothing_else_masks_it(self, unmanifested):
        # If a per-list gate fired here the test above would pass for the wrong
        # reason, exactly as the suite did before.
        result = run_audit([unmanifested], TARGETS, verify_hashes=True)[0]
        assert result.missing_targets == []
        assert result.malformed_files == []
        assert result.missing_files == []
        assert result.manifest_present is False
        assert result.ok is False
