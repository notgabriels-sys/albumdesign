"""Create shareable delivery bundles."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .audit import BundleAudit

_PACKAGE_FILE = "COVERFORGE_PACKAGE.json"

# The zip format's own epoch. Any fixed value works; this one is the earliest
# a zip can represent, so it reads as "deliberately not a timestamp" rather
# than as a date someone might trust.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class PackageError(Exception):
    """A package could not be written safely."""


@dataclass
class PackageResult:
    bundle: Path
    zip_path: Path
    slug: str | None
    ok: bool
    files: list[dict[str, str | int]]

    def as_dict(self) -> dict:
        return {
            "bundle": str(self.bundle),
            "zip_path": str(self.zip_path),
            "slug": self.slug,
            "ok": self.ok,
            "files": self.files,
        }


def build_package(audit_result: BundleAudit, zip_path: Path) -> PackageResult:
    """Create a zip package for one audited delivery folder."""
    if (
        not audit_result.manifest_valid
        or audit_result.capture_id_mismatch
        or "manifest.json" not in audit_result.package_members
    ):
        raise PackageError(
            f"{audit_result.bundle}/manifest.json does not provide a valid package inventory"
        )
    if not audit_result.hashes_verified:
        raise PackageError(
            "package requires an audit with verified delivery-file hashes"
        )

    try:
        bundle_root = audit_result.bundle.resolve()
        destination = zip_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PackageError(f"could not resolve package destination: {exc}") from None
    try:
        destination.relative_to(bundle_root)
    except ValueError:
        pass
    else:
        raise PackageError(
            f"package output {zip_path} is inside delivery bundle {audit_result.bundle}"
        )

    skipped_links = audit_result.skipped_symlinks
    captured: list[tuple[str, bytes]] = []
    files: list[dict[str, str | int]] = []
    for name, raw_data in sorted(audit_result.package_members.items()):
        if name == _PACKAGE_FILE:
            continue
        if (
            name != Path(name).name
            or Path(name).is_absolute()
            or "/" in name
            or "\\" in name
        ):
            raise PackageError(f"invalid package member name: {name}")
        data = bytes(raw_data)
        captured.append((name, data))
        files.append(
            {
                "name": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    # Refuse special entries explicitly, then build a complete archive in an
    # exclusively created sibling and replace the destination in one step.
    # This neither follows symlinks nor mutates another name of a hard-linked
    # file, and a failed zip write cannot expose a partial final archive.
    existing_mode: int | None = None
    try:
        destination_stat = zip_path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PackageError(f"could not inspect {zip_path}: {exc}") from None
    else:
        if stat.S_ISLNK(destination_stat.st_mode):
            raise PackageError(
                f"{zip_path} is a symlink; refusing to write through it. "
                "Remove it or package into a clean directory."
            )
        if not stat.S_ISREG(destination_stat.st_mode):
            raise PackageError(
                f"{zip_path} is not a regular file; refusing to replace it. "
                "Remove it or package into a clean directory."
            )
        existing_mode = stat.S_IMODE(destination_stat.st_mode)

    temporary: Path | None = None
    fd: int | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=".coverforge-", suffix=".tmp", dir=zip_path.parent
        )
        temporary = Path(temporary_name)
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        with os.fdopen(fd, "w+b", closefd=False) as raw, zipfile.ZipFile(
            raw, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for arcname, data in captured:
                # Write through an explicit ZipInfo with a fixed timestamp.
                # zf.write takes the member's mtime from the filesystem and
                # zf.writestr stamps local time, so identical inputs otherwise
                # produce different package bytes.
                info = zipfile.ZipInfo(arcname, date_time=_ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)

            package_summary = {
                "coverforge": "package",
                # The folder's name, not its path. str(bundle) put the invoking
                # absolute path into a file that ships to the client, so a
                # normal package command handed over the home directory and
                # username. manifest.json was already path-free; this was the
                # hole in that promise.
                "bundle": audit_result.bundle.name,
                "slug": audit_result.slug,
                "ok": audit_result.ok,
                "checked_targets": audit_result.checked_targets,
                "missing_targets": audit_result.missing_targets,
                "extra_targets": audit_result.extra_targets,
                "malformed_files": audit_result.malformed_files,
                "missing_files": audit_result.missing_files,
                "dimension_mismatches": audit_result.dimension_mismatches,
                "format_mismatches": audit_result.format_mismatches,
                "bytes_mismatches": audit_result.bytes_mismatches,
                "checksum_mismatches": audit_result.checksum_mismatches,
                "hashes_verified": audit_result.hashes_verified,
                "manifest_present": audit_result.manifest_present,
                "manifest_valid": audit_result.manifest_valid,
                "manifest_files": audit_result.manifest_files,
                "unmanifested_files": audit_result.unmanifested_files,
                "size_cap_exceeded": audit_result.size_cap_exceeded,
                "skipped_symlinks": skipped_links,
                "files": files,
            }
            summary_info = zipfile.ZipInfo(_PACKAGE_FILE, date_time=_ZIP_EPOCH)
            summary_info.compress_type = zipfile.ZIP_DEFLATED
            summary_info.external_attr = 0o644 << 16
            zf.writestr(
                summary_info, json.dumps(package_summary, indent=2, sort_keys=True)
            )
        os.fsync(fd)
        completed_fd = fd
        fd = None
        os.close(completed_fd)
        os.replace(temporary, zip_path)
        temporary = None
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise PackageError(f"could not write {zip_path}: {exc}") from None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass

    return PackageResult(
        bundle=audit_result.bundle,
        zip_path=zip_path,
        slug=audit_result.slug,
        ok=audit_result.ok,
        files=files,
    )
