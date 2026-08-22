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

import json
import zipfile

import pytest
from PIL import Image

from coverforge.audit import run_audit
from coverforge.build import build
from coverforge.cli import main
from coverforge.imageops import ImageError, inspect
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
