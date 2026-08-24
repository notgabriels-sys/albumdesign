"""Create shareable delivery bundles."""

from __future__ import annotations

import errno
import hashlib
import json
import os
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(audit_result: BundleAudit, zip_path: Path) -> PackageResult:
    """Create a zip package for one audited delivery folder."""
    files: list[dict[str, str | int]] = []

    # A plain open follows a symlink at the destination. A dangling link is not
    # caught by the exists() test that picks the file name either, so a link to
    # a path outside the output directory had a multi-megabyte zip written
    # through it. O_NOFOLLOW fails on the link instead.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(zip_path, flags, 0o644)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PackageError(
                f"{zip_path} is a symlink; refusing to write through it. "
                "Remove it or package into a clean directory."
            ) from None
        raise PackageError(f"could not write {zip_path}: {exc}") from None

    skipped_links: list[str] = []
    with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(
        raw, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as zf:
        for child in sorted(audit_result.bundle.iterdir()):
            # is_file() follows the link, so a symlink planted in a delivery
            # folder had its target's contents copied into a zip meant to be
            # handed to a client. Name it in the summary rather than shipping it.
            if child.is_symlink():
                skipped_links.append(child.name)
                continue
            if not child.is_file():
                continue
            if child.name == _PACKAGE_FILE:
                continue

            arcname = child.name
            # Write through an explicit ZipInfo with a fixed timestamp. zf.write
            # takes the member's mtime from the filesystem and zf.writestr
            # stamps time.localtime(), so two packages of the same bundle
            # seconds apart hashed differently, and the difference moved with
            # the local timezone. This repo zeroes the ICC creation timestamp
            # for the same reason: a rebuild that changes bytes has no stable
            # identifier. The manifest inside carries the real facts.
            info = zipfile.ZipInfo(arcname, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, child.read_bytes())
            data = {
                "name": arcname,
                "bytes": child.stat().st_size,
                "sha256": _sha256_file(child),
            }
            files.append(data)

        package_summary = {
            "coverforge": "package",
            # The folder's name, not its path. str(bundle) put the invoking
            # absolute path into a file that ships to the client, so a normal
            # `coverforge package ~/deliveries/ft011` handed over the home
            # directory and the username. manifest.json was already path-free;
            # this file was the hole in that promise.
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
            # Both were absent, so a bundle whose bytes contradicted its
            # manifest shipped a summary with no trace of it.
            "bytes_mismatches": audit_result.bytes_mismatches,
            "checksum_mismatches": audit_result.checksum_mismatches,
            "hashes_verified": audit_result.hashes_verified,
            "manifest_present": audit_result.manifest_present,
            "skipped_symlinks": skipped_links,
            "files": files,
        }
        summary_info = zipfile.ZipInfo(_PACKAGE_FILE, date_time=_ZIP_EPOCH)
        summary_info.compress_type = zipfile.ZIP_DEFLATED
        summary_info.external_attr = 0o644 << 16
        zf.writestr(
            summary_info, json.dumps(package_summary, indent=2, sort_keys=True)
        )

    return PackageResult(
        bundle=audit_result.bundle,
        zip_path=zip_path,
        slug=audit_result.slug,
        ok=audit_result.ok,
        files=files,
    )
