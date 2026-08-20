import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from coverforge.build import build, output_name
from coverforge.cli import main
from coverforge.imageops import inspect
from coverforge.specs import load_targets

ALL_TARGETS = load_targets().select()


def test_build_writes_every_target_at_the_right_size(master, tmp_path):
    out = tmp_path / "delivery"
    result = build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    assert not result.skipped
    assert len(result.outputs) == len(ALL_TARGETS)
    for output in result.outputs:
        assert output.path.exists()
        with Image.open(output.path) as im:
            assert im.size == (output.target.width, output.target.height)
            assert im.mode in {"RGB", "P"}


def test_build_honours_size_caps(master, tmp_path):
    targets = [t for t in ALL_TARGETS if t.max_bytes]
    result = build(inspect(master), targets, out_dir=tmp_path / "d", slug="x")
    for output in result.outputs:
        assert output.bytes_written <= output.target.max_bytes
        assert not output.over_cap


def test_build_skips_targets_the_master_cannot_meet(art_factory, tmp_path):
    src = inspect(art_factory(size=(900, 900)))
    result = build(src, ALL_TARGETS, out_dir=tmp_path / "d", slug="tiny")

    skipped = {t.key for t, _ in result.skipped}
    assert "spotify" in skipped
    assert "apple_music" in skipped
    assert not result.ok
    for target, _ in result.skipped:
        assert not (tmp_path / "d" / output_name("tiny", target)).exists()


def test_allow_upscale_forces_the_render(art_factory, tmp_path):
    src = inspect(art_factory(size=(1600, 1600)))
    blocked = build(src, ALL_TARGETS, out_dir=tmp_path / "a", slug="u")
    forced = build(
        src, ALL_TARGETS, out_dir=tmp_path / "b", slug="u", allow_upscale=True
    )

    assert "spotify" in {t.key for t, _ in blocked.skipped}
    assert "spotify" in {o.target.key for o in forced.outputs}
    # apple_music has a 3000px floor, so it stays blocked even when forced.
    assert "apple_music" in {t.key for t, _ in forced.skipped}


def test_dry_run_writes_nothing(master, tmp_path):
    out = tmp_path / "d"
    result = build(inspect(master), ALL_TARGETS, out_dir=out, slug="x", dry_run=True)
    assert result.outputs == []
    assert not out.exists()


def test_build_writes_manifest_and_delivery_note(master, tmp_path):
    out = tmp_path / "d"
    build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["slug"] == "lof001"
    assert len(manifest["outputs"]) == len(ALL_TARGETS)
    assert manifest["outputs"][0]["file"].startswith("lof001--")

    note = (out / "DELIVERY.md").read_text()
    assert "# lof001" in note
    assert "Bandcamp" in note


def test_written_manifest_is_portable_while_build_result_remains_owner_local(
    master, tmp_path
):
    out = tmp_path / "delivery"
    source = inspect(master)
    result = build(source, ALL_TARGETS, out_dir=out, slug="lof001")

    raw = (out / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(raw)

    assert manifest.get("schema_version") == 1
    assert manifest["generated_by"] == "coverforge"
    assert manifest["slug"] == "lof001"
    assert str(tmp_path) not in raw
    assert str(master) not in raw
    assert master.name not in raw
    assert "master" not in manifest
    assert "out_dir" not in manifest
    assert set(manifest["source"]) == {
        "sha256",
        "bytes",
        "dimensions",
        "mode",
        "format",
    }
    assert manifest["source"] == {
        "sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "bytes": master.stat().st_size,
        "dimensions": source.dimensions,
        "mode": source.mode,
        "format": source.file_format,
    }
    for output in manifest["outputs"]:
        rendered = out / output["file"]
        assert output["sha256"] == hashlib.sha256(rendered.read_bytes()).hexdigest()

    capture_payload = {
        key: value for key, value in manifest.items() if key != "capture_id"
    }
    canonical = json.dumps(
        capture_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert manifest["capture_id"] == f"cfp_{hashlib.sha256(canonical).hexdigest()[:20]}"

    owner_local = result.as_dict()
    assert owner_local["master"] == str(master)
    assert owner_local["out_dir"] == str(out)


def test_build_rejects_path_bearing_programmatic_slug_before_writing(master, tmp_path):
    out = tmp_path / "delivery"

    with pytest.raises(ValueError, match="slug"):
        build(inspect(master), [ALL_TARGETS[0]], out_dir=out, slug=str(master))

    assert not out.exists()


def test_cli_targets_json(capsys):
    assert main(["targets", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {t["key"] for t in payload["targets"]} >= {
        "bandcamp",
        "spotify",
        "instagram_story",
    }


def test_cli_check_is_clean_for_a_good_master(master, capsys):
    assert main(["check", str(master)]) == 0
    assert "targets clear" in capsys.readouterr().out


def test_cli_check_exits_nonzero_on_errors(art_factory, capsys):
    small = art_factory(size=(700, 700))
    assert main(["check", str(small)]) == 1


def test_cli_strict_promotes_warnings(art_factory, capsys):
    src = art_factory(size=(1600, 1600))  # upscale warnings, no errors
    assert main(["check", str(src), "--only", "spotify", "--allow-upscale"]) == 0
    assert (
        main(["check", str(src), "--only", "spotify", "--allow-upscale", "--strict"])
        == 1
    )


def test_cli_check_json_shape(master, capsys):
    main(["check", str(master), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["dimensions"] == "3000x3000"
    assert isinstance(payload["results"][0]["findings"], list)


def test_cli_build_single_master(master, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "build",
            str(master),
            "-o",
            str(out),
            "--group",
            "dsp",
            "--name",
            "Lack of Fate - Drift",
        ]
    )
    assert code == 0
    files = sorted(p.name for p in out.glob("*.jpg"))
    assert files and all(f.startswith("lack-of-fate-drift--") for f in files)


def test_cli_build_batch_of_variants_gets_one_folder_each(
    tmp_path, art_factory, capsys
):
    variants = tmp_path / "variants"
    variants.mkdir()
    for i in range(3):
        Image.open(art_factory(size=(3000, 3000))).save(variants / f"cover-v{i}.png")

    out = tmp_path / "out"
    assert main(["build", str(variants), "-o", str(out), "--only", "bandcamp"]) == 0
    made = sorted(p.name for p in out.iterdir())
    assert made == ["cover-v0", "cover-v1", "cover-v2"]
    assert (out / "cover-v0" / "cover-v0--bandcamp--3000x3000.jpg").exists()


def test_cli_contact_sheet_writes_an_offline_variant_review(tmp_path, art_factory, capsys):
    variants = tmp_path / "variants"
    variants.mkdir()
    for index in range(3):
        Image.open(art_factory(size=(3000, 3000))).save(variants / f"cover-v{index}.png")

    output = tmp_path.parent / f"{tmp_path.name}-review"
    code = main(
        [
            "contact-sheet",
            str(variants),
            "-o",
            str(output),
            "--title",
            "Lack of Fate review",
            "--columns",
            "2",
            "--cell-size",
            "120",
        ]
    )

    assert code == 0
    assert sorted(path.name for path in output.iterdir()) == [
        "CONTACT_SHEET.html",
        "CONTACT_SHEET.jpg",
    ]
    assert "Wrote offline contact-sheet review" in capsys.readouterr().out


def test_cli_contact_sheet_dry_run_validates_without_creating_output(art_factory, tmp_path, capsys):
    source = art_factory(size=(3000, 3000))
    output = tmp_path.parent / f"{tmp_path.name}-review"

    code = main(
        [
            "contact-sheet",
            str(source),
            "-o",
            str(output),
            "--dry-run",
            "--columns",
            "2",
            "--cell-size",
            "120",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["contact_sheet"]["dimensions"] == "324x304"
    assert not output.exists()


def test_cli_contact_sheet_rejects_nonpositive_column_count(art_factory, tmp_path, capsys):
    source = art_factory(size=(3000, 3000))
    output = tmp_path.parent / f"{tmp_path.name}-review"

    assert main(["contact-sheet", str(source), "-o", str(output), "--columns", "0"]) == 2
    assert "columns must be a positive integer" in capsys.readouterr().err
    assert not output.exists()


def test_cli_build_rejects_name_with_multiple_masters(tmp_path, art_factory, capsys):
    a, b = art_factory(), art_factory()
    code = main(["build", str(a), str(b), "-o", str(tmp_path / "o"), "--name", "one"])
    assert code == 2
    assert "--name only makes sense" in capsys.readouterr().err


def test_cli_reports_unknown_target(master, capsys):
    assert main(["check", str(master), "--only", "myspace"]) == 2
    assert "unknown target" in capsys.readouterr().err


def test_cli_handles_unreadable_file(tmp_path, capsys):
    junk = tmp_path / "cover.png"
    junk.write_text("not actually a png")
    assert main(["check", str(junk)]) == 2
    assert "not a readable image" in capsys.readouterr().err


def test_cli_sheet_builds_grid(tmp_path, art_factory, capsys):
    assets = tmp_path / "assets"
    assets.mkdir()
    images = [art_factory() for _ in range(3)]
    for image in images:
        image.rename(assets / image.name)

    out = tmp_path / "sheet.jpg"
    assert main(["sheet", str(assets), "-o", str(out), "--columns", "2"]) == 0
    assert out.exists()
    with Image.open(out) as contact:
        assert contact.size == (2 * 580 + 20 * 3, 2 * 580 + 2 * 24 + 20 * 3)


def test_cli_sheet_json_output(tmp_path, art_factory, capsys):
    assets = tmp_path / "assets"
    assets.mkdir()
    for _ in range(3):
        path = art_factory()
        path.rename(assets / path.name)

    out = tmp_path / "sheet.jpg"
    assert main(["sheet", str(assets), "-o", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sheet"]["output"] == str(out.with_suffix(".jpg"))
    assert payload["sheet"]["master_count"] == 3
    assert payload["sheet"]["columns"] == 4


def test_cli_sheet_rejects_no_images(tmp_path, capsys):
    out = tmp_path / "sheet.jpg"
    assert main(["sheet", str(tmp_path), "-o", str(out)]) == 2
    assert "no images found" in capsys.readouterr().err


def test_cli_audit_valid_delivery_bundle(master, tmp_path):
    out = tmp_path / "bundle"
    build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    assert main(["audit", str(out)]) == 0


def test_cli_audit_json_report(master, tmp_path, capsys):
    out = tmp_path / "bundle"
    build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    assert main(["audit", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bundles"][0]["ok"] is True
    assert payload["bundles"][0]["bundle"] == str(out)


def test_cli_verify_checks_manifest_hashes(master, tmp_path, capsys):
    out = tmp_path / "bundle"
    build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    target = next(
        child for child in out.iterdir() if child.suffix.lower() in {".jpg", ".png"}
    )
    data = target.read_bytes()
    target.write_bytes(data + b"x")

    assert main(["verify", str(out), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["bundles"][0]["ok"] is False
    assert payload["bundles"][0]["bytes_mismatches"]
    assert payload["bundles"][0]["checksum_mismatches"]


def test_cli_audit_does_not_verify_hashes_without_verify_flag(master, tmp_path):
    out = tmp_path / "bundle"
    build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    target = next(
        child for child in out.iterdir() if child.suffix.lower() in {".jpg", ".png"}
    )
    data = target.read_bytes()
    target.write_bytes(data + b"x")

    assert main(["audit", str(out)]) == 0



def test_cli_audit_flags_missing_files_as_errors(master, tmp_path):
    out = tmp_path / "bundle"
    build(inspect(master), ALL_TARGETS, out_dir=out, slug="lof001")

    (out / "lof001--spotify--3000x3000.jpg").unlink()
    assert main(["audit", str(out), "--only", "spotify"]) == 1


def test_cli_audit_flags_bad_dimension(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    Image.new("RGB", (1400, 1400), "black").save(bundle / "bad--spotify--1400x1400.jpg")

    # Keep selection tight to one target to make the report precise.
    assert main(["audit", str(bundle), "--only", "spotify"]) == 1


def test_cli_package_creates_delivery_zip(tmp_path, master):
    bundle = tmp_path / "delivery"
    build(inspect(master), ALL_TARGETS, out_dir=bundle, slug="lof001")

    out = tmp_path / "pkg"
    assert main(["package", str(bundle), "-o", str(out)]) == 0

    packed = sorted(out.glob("*.zip"))
    assert len(packed) == 1
    with zipfile.ZipFile(packed[0]) as zf:
        files = set(zf.namelist())
        assert "COVERFORGE_PACKAGE.json" in files
        assert "manifest.json" in files
        summary = json.loads(zf.read("COVERFORGE_PACKAGE.json").decode("utf-8"))

    assert summary["bundle"] == str(bundle)
    assert summary["ok"] is True
    assert summary["checked_targets"] == [target.key for target in ALL_TARGETS]
    assert len(summary["files"]) == len(ALL_TARGETS) + 2


def test_cli_package_json_payload(tmp_path, master, capsys):
    bundle = tmp_path / "delivery"
    build(inspect(master), ALL_TARGETS, out_dir=bundle, slug="lof001")

    out = tmp_path / "pkg"
    assert main(["package", str(bundle), "-o", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["packages"][0]["ok"] is True
    assert payload["packages"][0]["bundle"] == str(bundle)
    assert payload["packages"][0]["files"]


def test_cli_package_skip_invalid_bundle_without_force(tmp_path, master):
    bundle = tmp_path / "delivery"
    build(inspect(master), ALL_TARGETS, out_dir=bundle, slug="lof001")
    (bundle / "lof001--spotify--3000x3000.jpg").unlink()

    out = tmp_path / "pkg"
    assert main(["package", str(bundle), "--only", "spotify", "-o", str(out)]) == 1
    assert list(out.glob("*.zip")) == []


def test_cli_package_includes_invalid_bundle_with_force(tmp_path, master):
    bundle = tmp_path / "delivery"
    build(inspect(master), ALL_TARGETS, out_dir=bundle, slug="lof001")
    (bundle / "lof001--spotify--3000x3000.jpg").unlink()

    out = tmp_path / "pkg"
    assert (
        main(["package", str(bundle), "--only", "spotify", "-o", str(out), "--force"])
        == 1
    )
    packed = sorted(out.glob("*.zip"))
    assert len(packed) == 1


def test_cli_manifest_diff_identical_captures_is_zero(tmp_path, master, capsys):
    left = tmp_path / "left"
    right = tmp_path / "right"
    build(inspect(master), ALL_TARGETS, out_dir=left, slug="lof001")
    build(inspect(master), ALL_TARGETS, out_dir=right, slug="lof001")

    assert main(["manifest", str(left), str(right)]) == 0
    assert "identical captures" in capsys.readouterr().out


def test_cli_manifest_diff_reports_output_and_capture_changes(tmp_path, master, capsys):
    baseline = tmp_path / "left"
    changed = tmp_path / "changed"
    build(inspect(master), ALL_TARGETS, out_dir=baseline, slug="lof001")
    build(inspect(master), ALL_TARGETS, out_dir=changed, slug="lof001")

    baseline_manifest = json.loads((baseline / "manifest.json").read_text())
    changed_payload = json.loads((changed / "manifest.json").read_text())
    changed_payload["outputs"][0]["sha256"] = f"tampered-{changed_payload['outputs'][0]['sha256']}"
    changed_payload["source"]["dimensions"] = "2999x3000"
    changed_payload["outputs"].pop(1)
    (changed / "manifest.json").write_text(json.dumps(changed_payload), encoding="utf-8")

    assert main(["manifest", str(baseline), str(changed), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["identical"] is False
    assert report["delta"]["source"]
    output_delta = report["delta"]["outputs"]
    assert output_delta["changed"]
    assert output_delta["removed"]


def test_builds_are_byte_reproducible(master, tmp_path):
    """Two identical builds must produce identical bytes and the same capture_id.

    The sRGB ICC profile embedded in every output carries a creation timestamp
    in its header. Left as littlecms writes it, that made every rebuild produce
    different files, different output hashes, and a different capture_id, which
    would make the manifest useless for confirming a pack is unchanged.

    Run in two separate processes on purpose. Both builds in one process share
    a module-level SRGB_BYTES computed once at import, so any nondeterminism
    that varies per process rather than per call was invisible: setting that
    constant to a profile with a live timestamp left this test passing.
    """
    import subprocess
    import sys

    def build_in_a_fresh_process(out):
        done = subprocess.run(
            [sys.executable, "-m", "coverforge", "build", str(master),
             "-o", str(out), "--name", "lof001"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
        )
        assert done.returncode in (0, 1), done.stderr
        return json.loads((out / "manifest.json").read_text())

    one = build_in_a_fresh_process(tmp_path / "one")
    two = build_in_a_fresh_process(tmp_path / "two")

    assert one == two
    assert one["capture_id"] == two["capture_id"]

    # And the bytes on disk really are identical, not just the recorded hashes.
    for entry in one["outputs"]:
        a = (tmp_path / "one" / entry["file"]).read_bytes()
        b = (tmp_path / "two" / entry["file"]).read_bytes()
        assert a == b, f"{entry['file']} differs between two separate build processes"


def test_srgb_profile_has_no_embedded_timestamp():
    from coverforge.imageops import SRGB_BYTES

    assert SRGB_BYTES is not None
    assert SRGB_BYTES[24:36] == b"\x00" * 12


def test_manifest_hashes_the_bytes_it_actually_rendered(master, tmp_path, monkeypatch):
    """source.sha256 must describe the read that was decoded, not a second one.

    Hashing the file and then reopening it left a window where the manifest
    could certify a digest for bytes that were never rendered.
    """
    import coverforge.imageops as imageops_module

    replacement = io.BytesIO()
    Image.new("RGB", (3000, 3000), (0, 255, 0)).save(replacement, format="PNG")
    original = imageops_module.normalise

    def swap_then_decode(path, flatten_colour="#ffffff", *, data=None):
        Path(path).write_bytes(replacement.getvalue())
        return original(path, flatten_colour, data=data)

    # Captured before the swap: this is what the manifest must certify, because
    # these are the bytes the build read and decoded.
    original_digest = hashlib.sha256(master.read_bytes()).hexdigest()

    monkeypatch.setattr(imageops_module, "normalise", swap_then_decode)
    targets = [t for t in ALL_TARGETS if t.key == "spotify"]
    result = build(inspect(master), targets, out_dir=tmp_path / "d", slug="probe")

    manifest = json.loads((tmp_path / "d" / "manifest.json").read_text())
    assert manifest["source"]["sha256"] == original_digest
    assert manifest["source"]["sha256"] == result.source_sha256

    # The assertion that actually bites. Comparing digests alone passed even
    # with the double-read bug reintroduced, because the two digests differ
    # either way. What distinguishes the two is the pixels: if normalise had
    # re-read from disk it would have decoded the flat green replacement, and
    # the manifest would be certifying a digest for art nobody rendered.
    with Image.open(result.outputs[0].path) as delivered:
        small = delivered.convert("RGB").resize((8, 8))
        raw = small.tobytes()
    pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    avg = tuple(sum(c) / len(c) for c in zip(*pixels))
    # JPEG will not return exactly (0,255,0), so judge it by tolerance: if
    # normalise had re-read from disk it would have decoded the flat green
    # replacement and this average would sit on green. The real master is a
    # red-to-blue gradient, which cannot.
    looks_like_the_replacement = avg[0] < 60 and avg[1] > 190 and avg[2] < 60
    assert not looks_like_the_replacement, (
        f"delivered file averages {avg}, which is the replacement image, so the "
        "render used a second read while the manifest hashed the first"
    )


def test_masters_sharing_a_name_do_not_overwrite_each_others_packs(tmp_path, capsys):
    """Two folders can hold a master with the same stem, and --name is refused
    for multi-master runs, so the second build used to overwrite the first."""
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    Image.new("RGB", (3000, 3000), (200, 0, 0)).save(first_dir / "ft011.png")
    Image.new("RGB", (3000, 3000), (0, 0, 200)).save(second_dir / "ft011.png")
    out = tmp_path / "out"

    code = main(
        [
            "build",
            str(first_dir / "ft011.png"),
            str(second_dir / "ft011.png"),
            "-o",
            str(out),
            "--only",
            "spotify",
        ]
    )
    assert code == 0

    packs = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert packs == ["ft011", "ft011-2"], packs
    for pack in packs:
        manifest = json.loads((out / pack / "manifest.json").read_text())
        produced = {o["file"] for o in manifest["outputs"]}
        on_disk = {p.name for p in (out / pack).glob("*.jpg")}
        # Nothing in the pack that the manifest does not describe.
        assert on_disk == produced, (pack, on_disk, produced)


def test_an_implausible_image_header_is_an_error_not_a_crash(tmp_path):
    import struct
    import zlib

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    header = struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)
    bomb = tmp_path / "bomb.png"
    bomb.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 40))
        + chunk(b"IEND", b"")
    )
    assert main(["check", str(bomb)]) == 2


def test_check_summary_agrees_with_what_build_writes(art_factory, tmp_path, capsys):
    """`check` counted upscale-skipped targets as clear while `build` skipped them.

    The two decided separately. They now share build.plan(), so the headline
    count cannot drift from reality again.
    """
    master = art_factory("ns", size=(3000, 2000))
    assert main(["check", str(master)]) in (0, 1)
    check_out = capsys.readouterr().out
    clear = int(re.search(r"ok (\d+)/\d+ targets clear", check_out).group(1))

    result = build(inspect(master), ALL_TARGETS, out_dir=tmp_path / "b", slug="ns")
    assert clear == len(result.outputs), (clear, len(result.outputs), check_out)


def test_dry_run_reports_the_files_it_would_write(master, tmp_path, capsys):
    """--dry-run promises to report what would be written, and used to report nothing."""
    out = tmp_path / "dry"
    assert main(["build", str(master), "-o", str(out), "--name", "Dry", "--dry-run"]) in (0, 1)
    printed = capsys.readouterr().out

    assert "would write" in printed
    for target in build(inspect(master), ALL_TARGETS, out_dir=tmp_path / "real", slug="dry").outputs:
        assert target.path.name in printed
    assert not out.exists()


def test_building_into_an_occupied_directory_warns_about_stale_art(master, tmp_path, capsys):
    """Stale covers in a delivery folder are not in the manifest, so zipping it
    for a distributor ships art nothing accounts for."""
    out = tmp_path / "pack"
    assert main(["build", str(master), "-o", str(out), "--name", "First"]) in (0, 1)
    capsys.readouterr()
    assert main(["build", str(master), "-o", str(out), "--name", "Second"]) in (0, 1)
    err = capsys.readouterr().err

    assert "manifest.json does not describe" in err
    assert "first--" in err
