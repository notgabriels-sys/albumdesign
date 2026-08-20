"""Create shareable delivery bundles."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .audit import BundleAudit

_PACKAGE_FILE = "COVERFORGE_PACKAGE.json"


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

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for child in sorted(audit_result.bundle.iterdir()):
            if not child.is_file():
                continue
            if child.name == _PACKAGE_FILE:
                continue

            arcname = child.name
            zf.write(child, arcname=arcname)
            data = {
                "name": arcname,
                "bytes": child.stat().st_size,
                "sha256": _sha256_file(child),
            }
            files.append(data)

        package_summary = {
            "coverforge": "package",
            "bundle": str(audit_result.bundle),
            "slug": audit_result.slug,
            "ok": audit_result.ok,
            "checked_targets": audit_result.checked_targets,
            "missing_targets": audit_result.missing_targets,
            "extra_targets": audit_result.extra_targets,
            "malformed_files": audit_result.malformed_files,
            "missing_files": audit_result.missing_files,
            "dimension_mismatches": audit_result.dimension_mismatches,
            "format_mismatches": audit_result.format_mismatches,
            "manifest_present": audit_result.manifest_present,
            "files": files,
        }
        zf.writestr(
            _PACKAGE_FILE, json.dumps(package_summary, indent=2, sort_keys=True)
        )

    return PackageResult(
        bundle=audit_result.bundle,
        zip_path=zip_path,
        slug=audit_result.slug,
        ok=audit_result.ok,
        files=files,
    )
