"""Validate delivery folders after export."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import stat
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .build import (
    MANIFEST_BOUNDARY,
    MANIFEST_SCHEMA_VERSION,
    MAX_MANIFEST_FILE_BYTES,
    MAX_MANIFEST_FINDING_CODE_LENGTH,
    MAX_MANIFEST_FINDING_MESSAGE_LENGTH,
    MAX_MANIFEST_FINDINGS,
    is_portable_slug,
    manifest_capture_id,
)
from .imageops import human_bytes, is_image_path
from .specs import (
    MAX_SELECTED_TARGETS,
    MAX_TARGET_EDGE,
    MAX_TARGET_NAME_LENGTH,
    MAX_TARGET_PIXELS,
    Target,
    is_portable_target_key,
    validate_targets,
)

_OUTPUT_RE = re.compile(
    r"(?P<slug>.+)--(?P<target>[a-z0-9][a-z0-9_-]*)--(?P<width>\d+)x(?P<height>\d+)\.(?P<ext>jpe?g|png)$"
)
_DIMENSIONS_RE = re.compile(r"^[1-9]\d*x[1-9]\d*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPTURE_ID_RE = re.compile(r"^cfp_[0-9a-f]{20}$")
_MAX_DELIVERY_FILE_BYTES = 128_000_000
MAX_MANIFEST_JSON_DEPTH = 64
MAX_MANIFEST_JSON_NODES = 10_000
_MAX_MANIFEST_OUTPUTS = MAX_SELECTED_TARGETS
MAX_MANIFEST_SKIPPED = MAX_SELECTED_TARGETS
_MAX_CAPTURED_BUNDLE_BYTES = 256_000_000
MAX_BUNDLE_ENTRIES = 4_096

_ROOT_FIELDS = {
    "schema_version",
    "generated_by",
    "boundary",
    "capture_id",
    "slug",
    "source",
    "outputs",
    "skipped",
    "findings",
}
_SOURCE_FIELDS = {"sha256", "bytes", "dimensions", "mode", "format"}
_OUTPUT_FIELDS = {
    "target",
    "name",
    "file",
    "dimensions",
    "format",
    "quality",
    "bytes",
    "size",
    "over_size_cap",
    "sha256",
}
_SKIPPED_FIELDS = {"target", "reason"}
_FINDING_FIELDS = {"level", "code", "message", "target"}


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
    bytes_mismatches: list[str]
    checksum_mismatches: list[str]
    dimension_mismatches: list[str]
    format_mismatches: list[str]
    manifest_present: bool
    # The manifest's capture_id is a hash of its own contents, so it can be
    # recomputed and compared. Nothing did: swap a delivery file, edit the
    # manifest so its bytes and sha256 match the swap, leave capture_id alone,
    # and verify said ok. "Hash-bound" only held against a manifest you already
    # trusted, which is the case a portable manifest is meant to remove.
    capture_id_mismatch: bool = False
    # Whether any file's bytes were actually hashed against the manifest.
    # Without this, a bundle with no manifest at all reached `ok` having
    # verified nothing: `coverforge verify` on a folder whose cover had been
    # swapped for a different image exited 0 and printed "ok".
    hashes_verified: bool = False
    # Schema version 1 is an explicit contract, not a bag of optional fields.
    # Packaging may be forced past delivery findings, but never past an
    # ambiguous inventory that could name arbitrary data.
    manifest_valid: bool = True
    manifest_files: list[str] = field(default_factory=list)
    unmanifested_files: list[str] = field(default_factory=list)
    skipped_symlinks: list[str] = field(default_factory=list)
    size_cap_exceeded: list[str] = field(default_factory=list)
    # Private byte snapshots bind package output to the exact files audited.
    # They are intentionally absent from repr() and as_dict().
    package_members: dict[str, bytes] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        if not self.manifest_present:
            return False
        if not self.manifest_valid:
            return False
        if self.capture_id_mismatch:
            return False
        return not (
            self.missing_targets
            or self.malformed_files
            or self.missing_files
            or self.bytes_mismatches
            or self.checksum_mismatches
            or self.dimension_mismatches
            or self.format_mismatches
            or self.unmanifested_files
            or self.size_cap_exceeded
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
            "bytes_mismatches": self.bytes_mismatches,
            "checksum_mismatches": self.checksum_mismatches,
            "dimension_mismatches": self.dimension_mismatches,
            "format_mismatches": self.format_mismatches,
            "manifest_present": self.manifest_present,
            "manifest_valid": self.manifest_valid,
            "manifest_files": self.manifest_files,
            "unmanifested_files": self.unmanifested_files,
            "skipped_symlinks": self.skipped_symlinks,
            "size_cap_exceeded": self.size_cap_exceeded,
            "capture_id_mismatch": self.capture_id_mismatch,
            "hashes_verified": self.hashes_verified,
            "ok": self.ok,
        }


def _read_regular_bytes(
    path: Path, *, max_bytes: int = _MAX_DELIVERY_FILE_BYTES
) -> bytes:
    """Read one regular file without following a final-component symlink."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise ValueError("entry is a symlink; refusing to read through it") from None
        raise

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("entry is not a regular file")
        if file_stat.st_size > max_bytes:
            raise ValueError(
                f"entry exceeds the {max_bytes}-byte safety limit"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(
                    f"entry exceeds the {max_bytes}-byte safety limit"
                )
            return data
    finally:
        os.close(fd)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def parse_manifest_json(text: str) -> dict:
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except RecursionError:
        raise ValueError("manifest nesting exceeds the parser safety limit") from None
    if not isinstance(payload, dict):
        raise TypeError("manifest payload is not a JSON object")
    stack: list[tuple[object, int]] = [(payload, 0)]
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > MAX_MANIFEST_JSON_NODES:
            raise ValueError(
                "manifest structure exceeds the parser node safety limit"
            )
        if depth > MAX_MANIFEST_JSON_DEPTH:
            raise ValueError("manifest nesting exceeds the parser safety limit")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return payload


def read_manifest_file(path: Path) -> tuple[dict, bytes]:
    """Read one bounded, regular, UTF-8 manifest without following a symlink."""
    if path.is_symlink():
        raise ValueError(
            f"{path} is a symlink; a bundle manifest must be a regular file"
        )
    try:
        raw = _read_regular_bytes(path, max_bytes=MAX_MANIFEST_FILE_BYTES)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise ValueError(f"could not read manifest.json: {reason}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"manifest is not UTF-8 in {path}: {exc}") from None
    return parse_manifest_json(text), raw


def _read_manifest(bundle: Path) -> tuple[dict | None, str | None, bytes | None]:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return None, None, None
    payload, raw = read_manifest_file(manifest_path)
    slug = payload.get("slug")
    return payload, slug if isinstance(slug, str) and slug else None, raw


def _read_error_reason(exc: OSError | ValueError) -> str:
    if isinstance(exc, OSError):
        return exc.strerror or type(exc).__name__
    return str(exc)


def _shape_errors(
    value: object, expected: set[str], label: str, *, missing_word: str
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} is not an object"]
    errors = [f"missing {missing_word}: {name}" for name in sorted(expected - value.keys())]
    errors.extend(
        f"unexpected {missing_word}: {name}" for name in sorted(value.keys() - expected)
    )
    return errors


def _is_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _valid_output_dimensions(value: object) -> bool:
    if not isinstance(value, str) or not _DIMENSIONS_RE.fullmatch(value):
        return False
    width_text, height_text = value.split("x", maxsplit=1)
    width = int(width_text)
    height = int(height_text)
    return (
        width <= MAX_TARGET_EDGE
        and height <= MAX_TARGET_EDGE
        and width * height <= MAX_TARGET_PIXELS
    )


def manifest_schema_errors(payload: dict) -> list[str]:
    """Return every schema-v1 structural error without trusting nested values."""
    errors = _shape_errors(payload, _ROOT_FIELDS, "manifest root", missing_word="root field")

    schema_version = payload.get("schema_version")
    if not _is_int(schema_version, minimum=1) or schema_version != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be integer {MANIFEST_SCHEMA_VERSION}, got {schema_version!r}"
        )
    if payload.get("generated_by") != "coverforge":
        errors.append("generated_by must be 'coverforge'")
    if payload.get("boundary") != MANIFEST_BOUNDARY:
        errors.append("boundary does not match the schema-v1 delivery disclaimer")

    capture_id = payload.get("capture_id")
    if not isinstance(capture_id, str) or not _CAPTURE_ID_RE.fullmatch(capture_id):
        errors.append("capture_id must be cfp_ followed by 20 lowercase hexadecimal characters")

    slug = payload.get("slug")
    if not is_portable_slug(slug):
        errors.append("slug is not a portable filename component")

    source = payload.get("source")
    errors.extend(_shape_errors(source, _SOURCE_FIELDS, "source", missing_word="source field"))
    if isinstance(source, dict):
        if not isinstance(source.get("sha256"), str) or not _SHA256_RE.fullmatch(
            source.get("sha256", "")
        ):
            errors.append("source sha256 must be 64 lowercase hexadecimal characters")
        if not _is_int(source.get("bytes")):
            errors.append("source bytes must be a non-negative integer")
        if not isinstance(source.get("dimensions"), str) or not _DIMENSIONS_RE.fullmatch(
            source.get("dimensions", "")
        ):
            errors.append("source dimensions must be WIDTHxHEIGHT")
        if (
            not isinstance(source.get("mode"), str)
            or not source.get("mode")
            or len(source.get("mode", "")) > 64
        ):
            errors.append("source mode must be a non-empty string")
        if (
            not isinstance(source.get("format"), str)
            or not source.get("format")
            or len(source.get("format", "")) > 64
        ):
            errors.append("source format must be a non-empty string")

    outputs = payload.get("outputs")
    output_targets: dict[str, str] = {}
    output_filenames: set[str] = set()
    if not isinstance(outputs, list):
        errors.append("outputs is not a list")
    else:
        if len(outputs) > _MAX_MANIFEST_OUTPUTS:
            errors.append(
                f"outputs contains {len(outputs)} entries; "
                f"maximum is {_MAX_MANIFEST_OUTPUTS}"
            )
        for index, item in enumerate(outputs[:_MAX_MANIFEST_OUTPUTS], start=1):
            label = f"output #{index}"
            errors.extend(
                _shape_errors(item, _OUTPUT_FIELDS, label, missing_word="output field")
            )
            if not isinstance(item, dict):
                continue
            for name in ("target", "name", "file", "size"):
                if not isinstance(item.get(name), str) or not item.get(name):
                    errors.append(f"{label} {name} must be a non-empty string")
            if isinstance(item.get("name"), str) and len(item["name"]) > MAX_TARGET_NAME_LENGTH:
                errors.append(
                    f"{label} name exceeds {MAX_TARGET_NAME_LENGTH} characters"
                )
            target = item.get("target")
            if isinstance(target, str) and target:
                folded_target = target.casefold()
                if folded_target in output_targets:
                    errors.append(f"duplicate output target: {target}")
                else:
                    output_targets[folded_target] = target
            if not is_portable_target_key(target):
                errors.append(
                    f"{label} target is not a portable target key"
                )
            if not _valid_output_dimensions(item.get("dimensions")):
                errors.append(f"{label} dimensions exceed the supported WIDTHxHEIGHT bounds")
            if item.get("format") not in {"jpeg", "png"}:
                errors.append(f"{label} format must be 'jpeg' or 'png'")
            if not _is_int(item.get("quality"), minimum=1) or item.get("quality", 0) > 100:
                errors.append(f"{label} quality must be an integer from 1 to 100")
            if not _is_int(item.get("bytes")):
                errors.append(f"{label} bytes must be a non-negative integer")
            elif (
                isinstance(item.get("size"), str)
                and item.get("size") != human_bytes(item["bytes"])
            ):
                errors.append(f"{label} size does not match its numeric bytes value")
            if not isinstance(item.get("over_size_cap"), bool):
                errors.append(f"{label} over_size_cap must be a boolean")
            if not isinstance(item.get("sha256"), str) or not _SHA256_RE.fullmatch(
                item.get("sha256", "")
            ):
                errors.append(f"{label} sha256 must be 64 lowercase hexadecimal characters")

            filename = item.get("file")
            if isinstance(filename, str) and filename:
                filename_key = filename.casefold()
                if filename_key in output_filenames:
                    errors.append(f"duplicate manifest filename: {filename}")
                output_filenames.add(filename_key)

                dimensions = item.get("dimensions")
                extension = {"jpeg": "jpg", "png": "png"}.get(item.get("format"))
                if (
                    isinstance(slug, str)
                    and isinstance(target, str)
                    and isinstance(dimensions, str)
                    and extension is not None
                ):
                    expected_filename = (
                        f"{slug}--{target}--{dimensions}.{extension}"
                    )
                    if filename != expected_filename:
                        errors.append(
                            f"{label} file does not match manifest slug, target, dimensions and format"
                        )

    skipped = payload.get("skipped")
    skipped_targets: dict[str, str] = {}
    if not isinstance(skipped, list):
        errors.append("skipped is not a list")
    else:
        if len(skipped) > MAX_MANIFEST_SKIPPED:
            errors.append(
                f"skipped contains {len(skipped)} entries; "
                f"maximum is {MAX_MANIFEST_SKIPPED}"
            )
        for index, item in enumerate(skipped[:MAX_MANIFEST_SKIPPED], start=1):
            label = f"skipped entry #{index}"
            errors.extend(
                _shape_errors(item, _SKIPPED_FIELDS, label, missing_word="skipped field")
            )
            if isinstance(item, dict):
                for name in _SKIPPED_FIELDS:
                    if not isinstance(item.get(name), str) or not item.get(name):
                        errors.append(f"{label} {name} must be a non-empty string")
                target = item.get("target")
                if not is_portable_target_key(target):
                    errors.append(f"{label} target is not a portable target key")
                reason = item.get("reason")
                if (
                    isinstance(reason, str)
                    and len(reason) > MAX_MANIFEST_FINDING_MESSAGE_LENGTH
                ):
                    errors.append(f"{label} reason is too long")
                if isinstance(target, str) and target:
                    folded_target = target.casefold()
                    if folded_target in skipped_targets:
                        errors.append(f"duplicate skipped target: {target}")
                    else:
                        skipped_targets[folded_target] = target

    for folded_target in sorted(output_targets.keys() & skipped_targets.keys()):
        errors.append(
            "target appears in both outputs and skipped: "
            f"{output_targets[folded_target]} / {skipped_targets[folded_target]}"
        )

    if isinstance(outputs, list) and isinstance(skipped, list):
        declared_targets = len(outputs) + len(skipped)
        if declared_targets > MAX_SELECTED_TARGETS:
            errors.append(
                f"outputs and skipped contain {declared_targets} entries; "
                f"combined maximum is {MAX_SELECTED_TARGETS}"
            )

    findings = payload.get("findings")
    if not isinstance(findings, list):
        errors.append("findings is not a list")
    else:
        if len(findings) > MAX_MANIFEST_FINDINGS:
            errors.append(
                f"findings contains {len(findings)} entries; "
                f"maximum is {MAX_MANIFEST_FINDINGS}"
            )
        for index, item in enumerate(findings[:MAX_MANIFEST_FINDINGS], start=1):
            label = f"finding #{index}"
            errors.extend(
                _shape_errors(item, _FINDING_FIELDS, label, missing_word="finding field")
            )
            if not isinstance(item, dict):
                continue
            if item.get("level") not in {"info", "warn", "error"}:
                errors.append(f"{label} level is invalid")
            for name in ("code", "message"):
                if not isinstance(item.get(name), str) or not item.get(name):
                    errors.append(f"{label} {name} must be a non-empty string")
            code = item.get("code")
            if isinstance(code, str) and len(code) > MAX_MANIFEST_FINDING_CODE_LENGTH:
                errors.append(f"{label} code is too long")
            message = item.get("message")
            if (
                isinstance(message, str)
                and len(message) > MAX_MANIFEST_FINDING_MESSAGE_LENGTH
            ):
                errors.append(f"{label} message is too long")
            if item.get("target") is not None and not isinstance(item.get("target"), str):
                errors.append(f"{label} target must be a string or null")
            elif item.get("target") is not None and not is_portable_target_key(
                item.get("target")
            ):
                errors.append(f"{label} target is not a portable target key or null")

    return errors


def _parse_output_name(filename: str) -> dict[str, str] | None:
    match = _OUTPUT_RE.fullmatch(filename)
    if not match:
        return None
    return match.groupdict()


def _bounded_directory_entries(path: Path) -> tuple[list[Path], bool]:
    """Capture one stable-size directory-name snapshot without following entries."""
    entries: list[Path] = []
    with os.scandir(path) as iterator:
        for entry in iterator:
            if len(entries) >= MAX_BUNDLE_ENTRIES:
                return sorted(entries, key=lambda child: child.name), True
            entries.append(Path(entry.path))
    return sorted(entries, key=lambda child: child.name), False


def _is_bundle(path: Path, entries: list[Path] | None = None) -> bool:
    manifest = path / "manifest.json"
    if manifest.exists() or manifest.is_symlink():
        return True
    if entries is None:
        entries, overflow = _bounded_directory_entries(path)
        if overflow:
            raise ValueError(
                f"delivery directory contains more than {MAX_BUNDLE_ENTRIES} entries"
            )
    return any(
        _parse_output_name(child.name.lower()) is not None
        for child in entries
        if not child.is_symlink() and child.is_file() and is_image_path(child)
    )


def discover_bundle_dirs(paths: list[Path]) -> list[Path]:
    bundles: list[Path] = []
    seen: set[Path] = set()

    def add(bundle: Path) -> None:
        if bundle in seen:
            return
        seen.add(bundle)
        bundles.append(bundle)

    for raw in paths:
        if raw.is_file() or raw.is_symlink():
            if raw.name == "manifest.json":
                add(raw.parent)
            else:
                raise ValueError(f"{raw} is not a delivery bundle file")
            continue
        if not raw.exists():
            raise FileNotFoundError(f"{raw} does not exist")
        if not raw.is_dir():
            raise ValueError(f"{raw} is not a delivery path")
        raw_entries, raw_overflow = _bounded_directory_entries(raw)
        if _is_bundle(raw, raw_entries):
            add(raw)
            continue
        if raw_overflow:
            raise ValueError(
                f"delivery search directory contains more than {MAX_BUNDLE_ENTRIES} entries"
            )
        for child in raw_entries:
            if not child.is_symlink() and child.is_dir() and _is_bundle(child):
                add(child)

    return bundles


def _scan_without_manifest(
    bundle: Path,
    entries: list[Path],
) -> tuple[dict[str, str], list[str], str | None]:
    present_by_target: dict[str, str] = {}
    malformed: list[str] = []
    slug: str | None = None

    for child in entries:
        if child.is_symlink():
            if is_image_path(child):
                malformed.append(f"output entry is a symlink: {child.name}")
            continue
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


def _read_image_info(data: bytes) -> tuple[tuple[int, int], str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return (image.width, image.height), str(image.format or "").lower()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"image exceeds Pillow's safe pixel limit: {exc}") from None
    except (OSError, SyntaxError, ValueError) as exc:
        # Pillow's message for unidentified BytesIO input includes the object's
        # process-local memory address. That made forced package summaries vary
        # between identical runs and disclosed an implementation detail. The
        # exception class is stable and still distinguishes decoder failures.
        raise ValueError(f"image decode failed: {type(exc).__name__}") from None


def _check_bundle(
    bundle: Path,
    targets: list[Target],
    expected_targets: dict[str, Target],
    *,
    verify_hashes: bool,
    capture_package_bytes: bool,
) -> BundleAudit:
    checked = [target.key for target in targets]
    malformed: list[str] = []
    bytes_mismatches: list[str] = []
    checksum_mismatches: list[str] = []
    missing_files: list[str] = []
    dimension_mismatches: list[str] = []
    format_mismatches: list[str] = []
    size_cap_exceeded: list[str] = []
    readable_outputs = 0
    hashed_outputs = 0
    manifest_files: list[str] = []
    unmanifested_files: list[str] = []
    package_members: dict[str, bytes] = {}
    captured_package_bytes = 0
    package_snapshot_blocked = False
    bundle_entries, entry_overflow = _bounded_directory_entries(bundle)
    skipped_symlinks = sorted(
        child.name for child in bundle_entries if child.is_symlink()
    )
    if entry_overflow:
        malformed.append(
            f"bundle contains more than {MAX_BUNDLE_ENTRIES} directory entries"
        )

    manifest_payload, manifest_slug, manifest_raw = _read_manifest(bundle)
    manifest_present = manifest_payload is not None
    manifest_valid = manifest_present
    if entry_overflow:
        manifest_valid = False
    slug = manifest_slug
    if capture_package_bytes and manifest_raw is not None:
        if len(manifest_raw) > _MAX_CAPTURED_BUNDLE_BYTES:
            malformed.append(
                "package snapshot exceeds the "
                f"{_MAX_CAPTURED_BUNDLE_BYTES}-byte per-bundle safety limit"
            )
            manifest_valid = False
            package_snapshot_blocked = True
        else:
            package_members["manifest.json"] = manifest_raw
            captured_package_bytes = len(manifest_raw)
    if entry_overflow and capture_package_bytes:
        package_members.clear()
        package_snapshot_blocked = True

    # A missing token is a schema error, not a mismatch. Keeping those states
    # separate lets the report say whether a value disagreed or never existed.
    capture_id_mismatch = False
    if manifest_payload is not None:
        schema_errors = manifest_schema_errors(manifest_payload)
        malformed.extend(schema_errors)
        manifest_valid = manifest_valid and not schema_errors
        capture_id = manifest_payload.get("capture_id")
    else:
        capture_id = None
    if isinstance(capture_id, str) and capture_id:
        try:
            expected_capture = manifest_capture_id(manifest_payload)
        except (RecursionError, TypeError, ValueError):
            capture_id_mismatch = True
        else:
            capture_id_mismatch = expected_capture != capture_id

    present_by_target: dict[str, str] = {}
    if manifest_payload is not None:
        outputs = manifest_payload.get("outputs")
        if not isinstance(outputs, list):
            outputs = []
        elif len(outputs) > _MAX_MANIFEST_OUTPUTS:
            outputs = outputs[:_MAX_MANIFEST_OUTPUTS]
            if capture_package_bytes:
                package_members.clear()
                package_snapshot_blocked = True

        seen_filenames: set[str] = set()
        seen_targets: set[str] = set()

        for index, item in enumerate(outputs, start=1):
            if not isinstance(item, dict):
                continue

            target_key = item.get("target")
            filename = item.get("file")
            if not isinstance(target_key, str) or not isinstance(filename, str):
                continue

            if target_key != target_key.strip() or not target_key:
                malformed.append(f"manifest output #{index} has an invalid target")
                manifest_valid = False
                continue
            if filename != filename.strip() or not filename:
                malformed.append(f"manifest output #{index} has an invalid filename")
                manifest_valid = False
                continue

            folded_target = target_key.casefold()
            if folded_target in seen_targets:
                malformed.append(f"duplicate manifest target: {target_key}")
                manifest_valid = False
                continue
            seen_targets.add(folded_target)

            # Validate before recording the target as present. Recording first
            # meant a rejected entry still counted towards present_targets, so
            # the audit reported the cover as delivered while refusing to look
            # at the thing the manifest named.
            # A manifest is by design something you receive from someone else,
            # so its filenames are untrusted text. `.` matches `/` in the name
            # pattern, so "../../etc/x--spotify--3000x3000.jpg" parsed happily
            # and bundle / filename reached outside the folder: verify then
            # opened, sized and hashed that file and printed the result, while
            # audit and package called the bundle complete without the real
            # cover being present. A delivery file is one plain name in the
            # folder, never a path.
            if (
                filename != Path(filename).name
                or Path(filename).is_absolute()
                or "/" in filename
                or "\\" in filename
            ):
                malformed.append(f"manifest filename is not a plain name: {filename}")
                manifest_valid = False
                continue

            filename_key = filename.casefold()
            if filename_key in seen_filenames:
                malformed.append(f"duplicate manifest filename: {filename}")
                manifest_valid = False
                continue
            seen_filenames.add(filename_key)
            manifest_files.append(filename)

            filename_dimensions = item.get("dimensions")
            declared_format = item.get("format")
            extension = {"jpeg": "jpg", "png": "png"}.get(declared_format)
            if (
                not isinstance(slug, str)
                or not isinstance(filename_dimensions, str)
                or extension is None
            ):
                # The schema errors above already name the malformed fields.
                continue
            suffix = f"--{target_key}--{filename_dimensions}.{extension}"
            if not filename.endswith(suffix):
                malformed.append(
                    f"{filename} does not match manifest target {target_key}, "
                    f"dimensions {filename_dimensions}, and format {declared_format}"
                )
                manifest_valid = False
                continue
            filename_slug = filename[: -len(suffix)]
            if filename_slug != slug:
                malformed.append(
                    f"{filename} slug {filename_slug!r} does not match manifest slug {slug!r}"
                )
                manifest_valid = False
                continue

            output_path = bundle / filename
            if output_path.is_symlink():
                malformed.append(f"manifest entry is a symlink: {filename}")
                continue

            present_by_target[target_key] = filename
            try:
                data = _read_regular_bytes(output_path)
            except FileNotFoundError:
                missing_files.append(filename)
                continue
            except (OSError, ValueError) as exc:
                malformed.append(
                    f"cannot read output image {filename}: {_read_error_reason(exc)}"
                )
                continue
            readable_outputs += 1
            if capture_package_bytes and not package_snapshot_blocked:
                next_snapshot_bytes = captured_package_bytes + len(data)
                if next_snapshot_bytes > _MAX_CAPTURED_BUNDLE_BYTES:
                    malformed.append(
                        "package snapshot exceeds the "
                        f"{_MAX_CAPTURED_BUNDLE_BYTES}-byte per-bundle safety limit"
                    )
                    manifest_valid = False
                    package_members.clear()
                    package_snapshot_blocked = True
                else:
                    package_members[filename] = data
                    captured_package_bytes = next_snapshot_bytes

            expected_target = expected_targets.get(target_key)

            if verify_hashes:
                expected_bytes = item.get("bytes")
                if _is_int(expected_bytes) and len(data) != expected_bytes:
                    bytes_mismatches.append(
                        f"{target_key}: expected {expected_bytes} bytes, "
                        f"got {len(data)} in {filename}"
                    )

                expected_sha = item.get("sha256")
                if isinstance(expected_sha, str) and _SHA256_RE.fullmatch(expected_sha):
                    actual_sha = hashlib.sha256(data).hexdigest()
                    hashed_outputs += 1
                    if actual_sha != expected_sha:
                        checksum_mismatches.append(
                            f"{target_key}: expected {expected_sha}, "
                            f"got {actual_sha} in {filename}"
                        )

            try:
                actual, actual_format = _read_image_info(data)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                malformed.append(f"cannot read output image {filename}: {exc}")
                continue

            actual_dimensions = f"{actual[0]}x{actual[1]}"
            if actual_dimensions != filename_dimensions:
                dimension_mismatches.append(
                    f"{target_key}: actual size {actual_dimensions} does not match filename dimensions {filename_dimensions} in {filename}"
                )
            if actual_dimensions != item.get("dimensions"):
                dimension_mismatches.append(
                    f"{target_key}: actual size {actual_dimensions} does not match manifest dimensions {item.get('dimensions')} in {filename}"
                )
            if actual_format != declared_format:
                format_mismatches.append(
                    f"{target_key}: actual format {actual_format or 'unknown'} does not match manifest format {declared_format} in {filename}"
                )

            if expected_target and expected_target.max_bytes is not None and len(data) > expected_target.max_bytes:
                size_cap_exceeded.append(
                    f"{target_key}: {len(data)} bytes exceeds current cap of {expected_target.max_bytes} in {filename}"
                )
            elif item.get("over_size_cap") is True:
                size_cap_exceeded.append(
                    f"{target_key}: manifest records {filename} over its build-time size cap"
                )

            if expected_target:
                if filename_dimensions != expected_target.dimensions:
                    dimension_mismatches.append(
                        f"{target_key}: expected {expected_target.dimensions}, got {filename_dimensions} in {filename}"
                    )
                if declared_format != expected_target.format:
                    format_mismatches.append(
                        f"{target_key}: expected {expected_target.format}, got {declared_format} in {filename}"
                    )
                if actual_dimensions != expected_target.dimensions:
                    dimension_mismatches.append(
                        f"{target_key}: actual size {actual_dimensions} does not match expected {expected_target.dimensions} in {filename}"
                    )
                if actual_format != expected_target.format:
                    format_mismatches.append(
                        f"{target_key}: actual format {actual_format or 'unknown'} does not match expected {expected_target.format} in {filename}"
                    )

        declared = set(manifest_files) | {"manifest.json", "DELIVERY.md"}
        unmanifested_files = sorted(
            child.name
            for child in bundle_entries
            if not child.is_symlink()
            and child.is_file()
            and child.name not in declared
        )

    else:
        present_by_target, scan_malformed, detected_slug = _scan_without_manifest(
            bundle, bundle_entries
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
                data = _read_regular_bytes(output_path)
                actual, _actual_format = _read_image_info(data)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                reason = (
                    _read_error_reason(exc)
                    if isinstance(exc, (OSError, ValueError))
                    else str(exc)
                )
                malformed.append(f"cannot read output image {filename}: {reason}")
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
        bytes_mismatches=bytes_mismatches,
        checksum_mismatches=checksum_mismatches,
        dimension_mismatches=dimension_mismatches,
        format_mismatches=format_mismatches,
        manifest_present=manifest_present,
        capture_id_mismatch=capture_id_mismatch,
        hashes_verified=(
            verify_hashes
            and readable_outputs > 0
            and hashed_outputs == readable_outputs
        ),
        manifest_valid=manifest_valid,
        manifest_files=sorted(manifest_files),
        unmanifested_files=unmanifested_files,
        skipped_symlinks=skipped_symlinks,
        size_cap_exceeded=size_cap_exceeded,
        package_members=package_members,
    )


def run_audit(
    paths: list[Path],
    targets: list[Target],
    *,
    verify_hashes: bool = False,
    capture_package_bytes: bool = False,
) -> list[BundleAudit]:
    """Validate selected targets in each delivery bundle path."""
    validate_targets(targets)
    bundles = discover_bundle_dirs(paths)
    if not bundles:
        raise FileNotFoundError("no delivery bundle directories found")

    expected_targets = {target.key: target for target in targets}
    results = [
        _check_bundle(
            bundle,
            targets,
            expected_targets,
            verify_hashes=verify_hashes,
            capture_package_bytes=capture_package_bytes,
        )
        for bundle in sorted(bundles)
    ]

    return results
