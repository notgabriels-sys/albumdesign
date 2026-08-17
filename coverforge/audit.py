"""Validate delivery folders after export."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .imageops import is_image_path
from .specs import Target

_OUTPUT_RE = re.compile(
    r"(?P<slug>.+)--(?P<target>[a-z0-9_]+)--(?P<width>\d+)x(?P<height>\d+)\.(?P<ext>jpe?g|png)$"
)


@dataclass
class BundleAudit:
    """Structured result of one audited delivery folder."""

    bundle: Path
    slug: str | None
    checked_targets: list[str]
    present_targets: list[str]
    missing_targets: list[str]
    extra_targets: list[str]
    malformed_files: list[str]
    missing_files: list[str]
    dimension_mismatches: list[str]
    format_mismatches: list[str]
    manifest_present: bool

    @property
    def ok(self) -> bool:
        return not (
            self.missing_targets
            or self.malformed_files
            or self.missing_files
            or self.dimension_mismatches
            or self.format_mismatches
        )

    def as_dict(self) -> dict:
        return {
            "bundle": str(self.bundle),
            "slug": self.slug,
            "checked_targets": self.checked_targets,
            "present_targets": self.present_targets,
            "missing_targets": self.missing_targets,
            "extra_targets": self.extra_targets,
            "malformed_files": self.malformed_files,
            "missing_files": self.missing_files,
            "dimension_mismatches": self.dimension_mismatches,
            "format_mismatches": self.format_mismatches,
            "manifest_present": self.manifest_present,
            "ok": self.ok,
        }


def _read_manifest(bundle: Path) -> tuple[dict, str | None]:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        return {}, None

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"invalid manifest payload in {manifest_path}")
    return payload, str(payload.get("slug", "") or "") or None


def _parse_output_name(filename: str) -> dict[str, str] | None:
    match = _OUTPUT_RE.fullmatch(filename)
    if not match:
        return None
    return match.groupdict()


def _is_bundle(path: Path) -> bool:
    if (path / "manifest.json").exists():
        return True
    return any(
        _parse_output_name(child.name.lower()) is not None
        for child in path.iterdir()
        if child.is_file() and is_image_path(child)
    )


def _discover_bundle_dirs(paths: list[Path]) -> list[Path]:
    bundles: list[Path] = []
    seen: set[Path] = set()

    def add(bundle: Path) -> None:
        if bundle in seen:
            return
        seen.add(bundle)
        bundles.append(bundle)

    for raw in paths:
        if raw.is_file():
            if raw.name == "manifest.json":
                add(raw.parent)
            else:
                raise ValueError(f"{raw} is not a delivery bundle file")
            continue
        if not raw.exists():
            raise FileNotFoundError(f"{raw} does not exist")
        if not raw.is_dir():
            raise ValueError(f"{raw} is not a delivery path")
        if _is_bundle(raw):
            add(raw)
            continue
        for child in sorted(raw.iterdir()):
            if child.is_dir() and _is_bundle(child):
                add(child)

    return bundles


def _scan_without_manifest(
    bundle: Path,
) -> tuple[dict[str, str], list[str], str | None]:
    present_by_target: dict[str, str] = {}
    malformed: list[str] = []
    slug: str | None = None

    for child in sorted(bundle.iterdir()):
        if not child.is_file() or not is_image_path(child):
            continue
        parsed = _parse_output_name(child.name.lower())
        if not parsed:
            continue

        target = parsed["target"]
        filename = child.name
        if target in present_by_target:
            malformed.append(f"duplicate target file for {target}: {filename}")
            continue

        if slug is None:
            slug = parsed["slug"]
        present_by_target[target] = filename

    return present_by_target, malformed, slug


def _read_image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.width, im.height


def _check_bundle(
    bundle: Path,
    targets: list[Target],
    expected_targets: dict[str, Target],
) -> BundleAudit:
    checked = [target.key for target in targets]
    malformed: list[str] = []
    missing_files: list[str] = []
    dimension_mismatches: list[str] = []
    format_mismatches: list[str] = []

    manifest_payload, manifest_slug = _read_manifest(bundle)
    manifest_present = bool(manifest_payload)
    slug = manifest_slug

    present_by_target: dict[str, str] = {}
    if manifest_present:
        outputs = manifest_payload.get("outputs")
        if not isinstance(outputs, list):
            raise ValueError(f"manifest missing outputs in {bundle}/manifest.json")

        for item in outputs:
            if not isinstance(item, dict):
                malformed.append(f"non-object output entry in manifest for {bundle}")
                continue

            target_key = item.get("target")
            filename = item.get("file")
            if not isinstance(target_key, str) or not isinstance(filename, str):
                malformed.append(
                    f"bad manifest output entry in {bundle / 'manifest.json'}"
                )
                continue

            target_key = target_key.strip()
            filename = filename.strip()
            if not target_key:
                malformed.append(f"empty manifest target in {bundle / 'manifest.json'}")
                continue
            if not filename:
                malformed.append(
                    f"empty manifest filename for {target_key} in {bundle / 'manifest.json'}"
                )
                continue

            if target_key in present_by_target:
                malformed.append(f"duplicate manifest target: {target_key}")
                continue
            present_by_target[target_key] = filename

            output_path = bundle / filename
            if not output_path.exists():
                missing_files.append(filename)
                continue

            parsed = _parse_output_name(filename.lower())
            if not parsed:
                malformed.append(
                    f"manifest filename not matching standard pattern: {filename}"
                )
                continue

            expected_target = expected_targets.get(target_key)

            try:
                actual = _read_image_dimensions(output_path)
            except OSError as exc:
                malformed.append(f"cannot read output image {filename}: {exc}")
                continue

            expected_from_name = f"{parsed['width']}x{parsed['height']}"
            actual_dimensions = f"{actual[0]}x{actual[1]}"
            if actual_dimensions != expected_from_name:
                dimension_mismatches.append(
                    f"{target_key}: actual size {actual_dimensions} does not match filename dimensions {expected_from_name} in {filename}"
                )

            if expected_target:
                if parsed["width"] != str(expected_target.width) or parsed[
                    "height"
                ] != str(expected_target.height):
                    dimension_mismatches.append(
                        f"{target_key}: expected {expected_target.dimensions}, got {parsed['width']}x{parsed['height']} in {filename}"
                    )
                if parsed["ext"] != expected_target.extension:
                    format_mismatches.append(
                        f"{target_key}: expected {expected_target.extension}, got {parsed['ext']} in {filename}"
                    )
                if actual_dimensions != expected_target.dimensions:
                    dimension_mismatches.append(
                        f"{target_key}: actual size {actual_dimensions} does not match expected {expected_target.dimensions} in {filename}"
                    )

    else:
        present_by_target, scan_malformed, detected_slug = _scan_without_manifest(
            bundle
        )
        malformed.extend(scan_malformed)
        if slug is None:
            slug = detected_slug
        for target_key, filename in present_by_target.items():
            output_path = bundle / filename
            expected_target = expected_targets.get(target_key)
            if not expected_target:
                continue
            parsed = _parse_output_name(filename.lower()) or {}
            if parsed:
                if parsed["width"] != str(expected_target.width) or parsed[
                    "height"
                ] != str(expected_target.height):
                    dimension_mismatches.append(
                        f"{target_key}: expected {expected_target.dimensions}, got {parsed['width']}x{parsed['height']} in {filename}"
                    )
                if parsed["ext"] != expected_target.extension:
                    format_mismatches.append(
                        f"{target_key}: expected {expected_target.extension}, got {parsed['ext']} in {filename}"
                    )

            try:
                actual = _read_image_dimensions(output_path)
            except OSError as exc:
                malformed.append(f"cannot read output image {filename}: {exc}")
                continue

            actual_dimensions = f"{actual[0]}x{actual[1]}"
            if actual_dimensions != expected_target.dimensions:
                dimension_mismatches.append(
                    f"{target_key}: actual size {actual_dimensions} does not match expected {expected_target.dimensions} in {filename}"
                )

    present_targets = sorted(present_by_target)
    present_set = set(present_targets)
    expected_set = set(checked)
    missing_targets = sorted(expected_set - present_set)
    extra_targets = sorted(present_set - expected_set)

    return BundleAudit(
        bundle=bundle,
        slug=slug,
        checked_targets=checked,
        present_targets=present_targets,
        missing_targets=missing_targets,
        extra_targets=extra_targets,
        malformed_files=malformed,
        missing_files=missing_files,
        dimension_mismatches=dimension_mismatches,
        format_mismatches=format_mismatches,
        manifest_present=manifest_present,
    )


def run_audit(
    paths: list[Path],
    targets: list[Target],
) -> list[BundleAudit]:
    """Validate selected targets in each delivery bundle path."""
    bundles = _discover_bundle_dirs(paths)
    if not bundles:
        raise FileNotFoundError("no delivery bundle directories found")

    expected_targets = {target.key: target for target in targets}
    results = [
        _check_bundle(bundle, targets, expected_targets) for bundle in sorted(bundles)
    ]

    return results
