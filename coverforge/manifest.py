"""Compare portable manifest captures produced by Coverforge builds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_OUTPUT_FIELDS = (
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
)

_SOURCE_FIELDS = ("sha256", "bytes", "dimensions", "mode", "format")


def _normalise_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_dir():
        path = path / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    return path


def load_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = _normalise_path(path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"manifest payload in {resolved} is not a JSON object")
    return payload, resolved


def _normalise_outputs(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    outputs: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    raw_outputs = payload.get("outputs", [])
    if raw_outputs is None:
        return outputs, issues
    if not isinstance(raw_outputs, list):
        raise TypeError("manifest outputs must be a list")

    for index, item in enumerate(raw_outputs, start=1):
        if not isinstance(item, dict):
            issues.append(f"output #{index} is not an object")
            continue

        target = item.get("target")
        if not isinstance(target, str) or not target.strip():
            issues.append(f"output #{index} has missing or invalid target")
            continue
        target = target.strip()
        if target in outputs:
            issues.append(f"duplicate output target {target}")
            continue
        outputs[target] = dict(item)

    return outputs, issues


def _normalise_manifest(
    payload: dict[str, Any], path: Path
) -> tuple[dict[str, Any], dict[str, str | Any], dict[str, str | Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    source = payload.get("source")
    if not isinstance(source, dict):
        source = {}

    outputs, output_issues = _normalise_outputs(payload)
    skipped = payload.get("skipped")
    if not isinstance(skipped, list):
        skipped = []

    findings = payload.get("findings")
    if not isinstance(findings, list):
        findings = []

    return (
        {
            "schema_version": payload.get("schema_version"),
            "generated_by": payload.get("generated_by"),
            "slug": payload.get("slug"),
            "capture_id": payload.get("capture_id"),
            # The boundary is the manifest's own disclaimer, the sentence that
            # says these hashes identify bytes and do not establish ownership,
            # rights or approval. It was never compared, so a copy whose
            # disclaimer had been rewritten into the opposite claim diffed as
            # identical. It sits inside the hashed payload, so it is part of
            # what the capture id covers.
            "boundary": payload.get("boundary"),
            "path": str(path),
        },
        {
            key: source.get(key)
            for key in _SOURCE_FIELDS
            if key in source and isinstance(source, dict)
        },
        outputs,
        skipped,
        findings,
        output_issues,
    )


def _dict_field_diff(
    left: dict[str, Any], right: dict[str, Any], keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key in sorted(set(keys)):
        lhs = left.get(key)
        rhs = right.get(key)
        if lhs != rhs:
            changes.append({"key": key, "left": lhs, "right": rhs})
    return changes


def compare_manifests(
    left_payload: dict[str, Any], right_payload: dict[str, Any], left_path: Path, right_path: Path
) -> dict[str, Any]:
    (
        left_meta,
        left_source,
        left_outputs,
        left_skipped,
        left_findings,
        left_output_issues,
    ) = _normalise_manifest(left_payload, left_path)
    (
        right_meta,
        right_source,
        right_outputs,
        right_skipped,
        right_findings,
        right_output_issues,
    ) = _normalise_manifest(right_payload, right_path)

    left_sources = _dict_field_diff(left_source, right_source, _SOURCE_FIELDS)

    left_output_targets = set(left_outputs.keys())
    right_output_targets = set(right_outputs.keys())
    added_outputs = sorted(right_output_targets - left_output_targets)
    removed_outputs = sorted(left_output_targets - right_output_targets)

    changed_outputs: list[dict[str, Any]] = []
    common = sorted(left_output_targets & right_output_targets)
    for target in common:
        left_output = left_outputs[target]
        right_output = right_outputs[target]
        field_changes = _dict_field_diff(
            left_output, right_output, tuple(_OUTPUT_FIELDS)
        )
        if field_changes:
            changed_outputs.append(
                {
                    "target": target,
                    "changes": field_changes,
                }
            )

    changed_skipped = left_skipped != right_skipped
    changed_findings = left_findings != right_findings

    schema_changed = left_meta["schema_version"] != right_meta["schema_version"]
    generator_changed = left_meta["generated_by"] != right_meta["generated_by"]
    slug_changed = left_meta["slug"] != right_meta["slug"]
    capture_id_changed = left_meta["capture_id"] != right_meta["capture_id"]
    boundary_changed = left_meta["boundary"] != right_meta["boundary"]

    output_issues = sorted(set(left_output_issues + right_output_issues))
    has_issues = bool(
        schema_changed
        or generator_changed
        or slug_changed
        or capture_id_changed
        or boundary_changed
        or left_sources
        or changed_skipped
        or changed_findings
        or added_outputs
        or removed_outputs
        or changed_outputs
        or output_issues
    )

    return {
        "left": {
            "path": str(left_meta["path"]),
            "schema_version": left_meta["schema_version"],
            "generated_by": left_meta["generated_by"],
            "slug": left_meta["slug"],
            "capture_id": left_meta["capture_id"],
            "source": left_source,
            "outputs_count": len(left_outputs),
            "skipped_count": len(left_skipped),
            "findings_count": len(left_findings),
        },
        "right": {
            "path": str(right_meta["path"]),
            "schema_version": right_meta["schema_version"],
            "generated_by": right_meta["generated_by"],
            "slug": right_meta["slug"],
            "capture_id": right_meta["capture_id"],
            "source": right_source,
            "outputs_count": len(right_outputs),
            "skipped_count": len(right_skipped),
            "findings_count": len(right_findings),
        },
        "delta": {
            "schema_version_changed": schema_changed,
            "generated_by_changed": generator_changed,
            "slug_changed": slug_changed,
            "capture_id_changed": capture_id_changed,
            "boundary_changed": boundary_changed,
            "source": left_sources,
            "skipped": {
                "left_count": len(left_skipped),
                "right_count": len(right_skipped),
                "changed": changed_skipped,
            },
            "findings": {
                "left_count": len(left_findings),
                "right_count": len(right_findings),
                "changed": changed_findings,
            },
            "outputs": {
                "added": [
                    {
                        "target": target,
                        "file": right_outputs[target].get("file")
                        if target in right_outputs
                        else None,
                    }
                    for target in added_outputs
                ],
                "removed": [
                    {
                        "target": target,
                        "file": left_outputs[target].get("file")
                        if target in left_outputs
                        else None,
                    }
                    for target in removed_outputs
                ],
                "changed": changed_outputs,
            },
            "output_issues": output_issues,
        },
        "identical": not has_issues,
    }
