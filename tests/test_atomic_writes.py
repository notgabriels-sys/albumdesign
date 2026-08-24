"""Destination writes must be bounded, private, and all-or-nothing."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from coverforge import build as build_module
from coverforge import cli as cli_module
from coverforge import package as package_module
from coverforge.audit import BundleAudit
from coverforge.build import write_new_bytes
from coverforge.imageops import ImageError
from coverforge.package import PackageError, PackageResult, build_package


def _packageable_audit(bundle: Path) -> BundleAudit:
    return BundleAudit(
        bundle=bundle,
        slug="release",
        checked_targets=[],
        present_targets=[],
        missing_targets=[],
        extra_targets=[],
        malformed_files=[],
        missing_files=[],
        bytes_mismatches=[],
        checksum_mismatches=[],
        dimension_mismatches=[],
        format_mismatches=[],
        manifest_present=True,
        hashes_verified=True,
        package_members={"manifest.json": b"{}"},
    )


def test_delivery_write_replaces_a_hard_link_without_mutating_its_other_name(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original.bin"
    destination = tmp_path / "delivery.bin"
    original.write_bytes(b"keep")
    os.link(original, destination)

    write_new_bytes(destination, b"replacement")

    assert original.read_bytes() == b"keep"
    assert destination.read_bytes() == b"replacement"


def test_package_replaces_a_hard_link_without_mutating_its_other_name(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    original = tmp_path / "original.bin"
    destination = tmp_path / "delivery.zip"
    original.write_bytes(b"keep")
    os.link(original, destination)

    build_package(_packageable_audit(bundle), destination)

    assert original.read_bytes() == b"keep"
    assert zipfile.is_zipfile(destination)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
@pytest.mark.parametrize("writer", ["delivery", "package"])
def test_special_destination_is_rejected_without_blocking(
    tmp_path: Path, writer: str
) -> None:
    destination = tmp_path / ("delivery.bin" if writer == "delivery" else "delivery.zip")
    os.mkfifo(destination)
    script = r"""
import sys
from pathlib import Path
from coverforge.audit import BundleAudit
from coverforge.build import write_new_bytes
from coverforge.imageops import ImageError
from coverforge.package import PackageError, build_package

destination = Path(sys.argv[2])
try:
    if sys.argv[1] == "delivery":
        write_new_bytes(destination, b"data")
    else:
        audit = BundleAudit(
            bundle=destination.parent / "bundle",
            slug="release",
            checked_targets=[], present_targets=[], missing_targets=[], extra_targets=[],
            malformed_files=[], missing_files=[], bytes_mismatches=[],
            checksum_mismatches=[], dimension_mismatches=[], format_mismatches=[],
            manifest_present=True, hashes_verified=True,
            package_members={"manifest.json": b"{}"},
        )
        build_package(audit, destination)
except (ImageError, PackageError) as exc:
    print(exc)
    raise SystemExit(7)
raise SystemExit(0)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, writer, str(destination)],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 7, completed.stderr
    assert "not a regular file" in completed.stdout


def test_existing_restrictive_mode_is_preserved(tmp_path: Path) -> None:
    destination = tmp_path / "delivery.bin"
    destination.write_bytes(b"old")
    destination.chmod(0o600)

    write_new_bytes(destination, b"new")

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_existing_restrictive_package_mode_is_preserved(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    destination = tmp_path / "delivery.zip"
    destination.write_bytes(b"old")
    destination.chmod(0o600)

    build_package(_packageable_audit(bundle), destination)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


@pytest.mark.parametrize("writer", ["delivery", "package"])
def test_a_near_limit_destination_name_does_not_expand_the_temporary_name(
    tmp_path: Path, writer: str
) -> None:
    suffix = ".zip" if writer == "package" else ".bin"
    destination = tmp_path / ("x" * (250 - len(suffix)) + suffix)

    if writer == "delivery":
        write_new_bytes(destination, b"data")
        assert destination.read_bytes() == b"data"
    else:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        build_package(_packageable_audit(bundle), destination)
        assert zipfile.is_zipfile(destination)


def test_failed_zip_write_keeps_existing_destination_and_removes_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    destination = tmp_path / "delivery.zip"
    destination.write_bytes(b"previous complete package")

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail_write)

    with pytest.raises(PackageError, match="simulated storage failure"):
        build_package(_packageable_audit(bundle), destination)

    assert destination.read_bytes() == b"previous complete package"
    assert list(tmp_path.glob(".coverforge-*.tmp")) == []


def test_mode_adjustment_failure_closes_and_removes_the_package_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    destination = tmp_path / "delivery.zip"
    destination.write_bytes(b"previous complete package")

    def fail_mode(*_args, **_kwargs):
        raise OSError("simulated mode failure")

    monkeypatch.setattr(package_module.os, "chmod", fail_mode)

    with pytest.raises(PackageError, match="simulated mode failure"):
        build_package(_packageable_audit(bundle), destination)

    assert destination.read_bytes() == b"previous complete package"
    assert list(tmp_path.glob(".coverforge-*.tmp")) == []


@pytest.mark.parametrize("interrupt_on", [1, 2])
def test_batch_commit_interrupt_removes_every_reserved_or_published_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_on: int
) -> None:
    staged = []
    for index in range(2):
        stage = tmp_path / f"stage-{index}.zip"
        stage.write_bytes(f"package {index}".encode())
        package = PackageResult(
            bundle=tmp_path / f"bundle-{index}",
            zip_path=stage,
            slug=f"release-{index}",
            ok=True,
            files=[],
        )
        staged.append((package, tmp_path / f"final-{index}.zip"))

    real_replace = os.replace
    calls = 0

    def interrupting_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == interrupt_on:
            raise KeyboardInterrupt
        return real_replace(source, destination)

    monkeypatch.setattr(cli_module.os, "replace", interrupting_replace)

    with pytest.raises(KeyboardInterrupt):
        cli_module._commit_staged_packages(staged)

    assert list(tmp_path.glob("final-*.zip")) == []


@pytest.mark.parametrize("existing_bundle", [False, True])
def test_bundle_commit_failure_rolls_back_every_published_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_bundle: bool
) -> None:
    stage = tmp_path / "stage"
    out = tmp_path / "bundle"
    stage.mkdir()
    names = ["alpha.png", "beta.png", "DELIVERY.md", "manifest.json"]
    for name in names:
        (stage / name).write_bytes(f"new {name}".encode())

    before: dict[str, bytes] = {}
    if existing_bundle:
        out.mkdir()
        for name in names:
            data = f"old {name}".encode()
            (out / name).write_bytes(data)
            before[name] = data

    real_replace = os.replace

    def fail_second_publish(source, destination):
        if Path(source) == stage / "beta.png" and Path(destination) == out / "beta.png":
            raise OSError("simulated publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(build_module.os, "replace", fail_second_publish)

    with pytest.raises(ImageError, match="could not publish complete bundle"):
        build_module._commit_staged_bundle(stage, out, names)

    if existing_bundle:
        assert {path.name: path.read_bytes() for path in out.iterdir()} == before
    else:
        assert not out.exists()
