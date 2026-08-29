"""Terminal formatting for check and build results."""

from __future__ import annotations

import os
import re
import sys
from datetime import date

from .build import BuildResult, output_name, plan
from .imageops import SourceImage, human_bytes
from .preflight import ERROR, INFO, WARN, Finding
from .specs import Target, TargetSet

_SYMBOL = {ERROR: "x", WARN: "!", INFO: "-"}
_COLOUR = {ERROR: "\033[31m", WARN: "\033[33m", INFO: "\033[90m"}
_BOLD = "\033[1m"
_RESET = "\033[0m"


def use_colour(stream=sys.stdout) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def format_finding(finding: Finding, colour: bool) -> str:
    prefix = _paint(_SYMBOL[finding.level], _COLOUR[finding.level], colour)
    scope = f"[{finding.target}] " if finding.target else ""
    return f"  {prefix} {scope}{finding.message}"


def format_check(
    src: SourceImage,
    findings: list[Finding],
    targets: list[Target],
    colour: bool,
    allow_upscale: bool = False,
) -> str:
    header = _paint(str(src.path), _BOLD, colour)
    lines = [
        f"{header}",
        f"  {src.dimensions}  {src.mode}  {src.file_format.upper()}  "
        f"{human_bytes(src.file_bytes)}  vs {len(targets)} target(s)",
    ]

    general = [f for f in findings if f.target is None]
    per_target = [f for f in findings if f.target is not None]

    if general:
        lines.append("")
        lines += [format_finding(f, colour) for f in general]

    if per_target:
        lines.append("")
        lines += [format_finding(f, colour) for f in per_target]

    # Ask the builder what it would actually render, rather than counting
    # anything without an error. Upscale-skipped targets are not "clear".
    passing, skipped = plan(src, targets, findings, allow_upscale)
    lines.append("")
    tick = _paint("ok", "\033[32m", colour)
    lines.append(
        f"  {tick} {len(passing)}/{len(targets)} targets clear: "
        f"{', '.join(t.key for t in passing) or 'none'}"
    )
    if skipped:
        mark = _paint(_SYMBOL[ERROR], _COLOUR[ERROR], colour)
        lines.append(
            f"  {mark} {len(skipped)} would be skipped by build: "
            f"{', '.join(t.key for t, _ in skipped)}"
        )
    return "\n".join(lines)


def format_build(result: BuildResult, colour: bool) -> str:
    header = _paint(f"{result.source.path.name} -> {result.out_dir}", _BOLD, colour)
    lines = [header]

    for output in result.outputs:
        flag = ""
        if output.over_cap:
            flag = _paint("  OVER SIZE CAP", _COLOUR[WARN], colour)
        quality = f" q{output.quality}" if output.target.format == "jpeg" else ""
        lines.append(
            f"  {output.target.key:<17} {output.target.dimensions:>9}  "
            f"{output.target.format:<4}{quality:<4} {human_bytes(output.bytes_written):>8}  "
            f"{output.path.name}{flag}"
        )

    # A dry run writes nothing, so there are no outputs to list. Show the plan
    # instead, which is what --dry-run says it reports.
    for target in result.planned if not result.outputs else []:
        quality = " jpeg" if target.format == "jpeg" else f" {target.format}"
        lines.append(
            f"  would write  {target.key:<17} {target.dimensions:>9} {quality:<5} "
            f"{output_name(result.slug, target)}"
        )

    for target, reason in result.skipped:
        mark = _paint(_SYMBOL[ERROR], _COLOUR[ERROR], colour)
        lines.append(f"  {mark} {target.key:<15} skipped: {reason}")

    # Skipped targets already printed their reason above; don't say it twice.
    reported = {target.key for target, _ in result.skipped}
    notes = [f for f in result.findings if f.level != INFO and f.target not in reported]
    if notes:
        lines.append("")
        lines += [format_finding(f, colour) for f in notes]

    return "\n".join(lines)


# How old the recorded review date may get before `targets` starts pushing
# back. This is THIS PROJECT'S prompt to go and re-read the platform pages, not
# a number any platform publishes, and the wording says so rather than dressing
# a house rule up as a requirement.
STALE_AFTER_MONTHS = 6

_YYYY_MM = re.compile(r"^(\d{4})-(\d{2})$")


def review_age(reviewed: str, today: date) -> tuple[int | None, str]:
    """Months between a `YYYY-MM` review stamp and today, plus how to say it.

    Returns `(None, reason)` when the stamp cannot be read as a date, because
    "0 months old" and "unreadable" are different answers and printing the
    first for the second would be the file vouching for itself.
    """
    m = _YYYY_MM.match(reviewed.strip())
    if not m:
        return None, "not a YYYY-MM date, so its age cannot be worked out"
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None, "names no real month, so its age cannot be worked out"
    months = (today.year - year) * 12 + (today.month - month)
    if months < 0:
        return months, f"dated {abs(months)} month(s) in the future, so it is wrong"
    if months == 0:
        return months, "this month"
    if months == 1:
        return months, "1 month ago"
    return months, f"{months} months ago"


def format_targets(target_set: TargetSet, colour: bool, today: date | None = None) -> str:
    """Render the target table.

    `today` is a parameter so the age line can be tested at a fixed date. It
    defaults to the real one; a renderer that could only be checked against the
    clock could not be checked at all.
    """
    today = today or date.today()
    lines = []
    if target_set.reviewed:
        months, phrase = review_age(target_set.reviewed, today)
        head = f"specs last reviewed {target_set.reviewed} ({phrase})"
        if months is None or months < 0:
            lines.append(_paint(f"{head} - fix the date in targets.toml", _COLOUR[WARN], colour))
        elif months >= STALE_AFTER_MONTHS:
            lines.append(_paint(
                f"{head} - past the {STALE_AFTER_MONTHS} months this project "
                f"allows before re-reading the platform pages. Check the source "
                f"links below before you deliver",
                _COLOUR[WARN], colour))
        else:
            lines.append(f"{head} - verify against your distributor")
        lines.append("")

    for group in target_set.groups:
        lines.append(_paint(group, _BOLD, colour))
        for target in target_set:
            if target.group != group:
                continue
            cap = f"<= {human_bytes(target.max_bytes)}" if target.max_bytes else ""
            lines.append(
                f"  {target.key:<17} {target.dimensions:>9}  {target.format:<4} "
                f"min {target.min_source or 0:>4}px  {cap:<9} {target.name}"
            )
            if target.notes:
                lines.append(f"  {'':<17} {_paint(target.notes, _COLOUR[INFO], colour)}")
            # Where the numbers came from. This was in `targets --json` and
            # nowhere a human could see it, so the one command you run to read
            # the specs could not tell you which of them carry a citation.
            #
            # "no source recorded" is deliberately a statement about this file
            # and not about the number. instagram_post's 1080 is Instagram's
            # own documented size; nobody wrote the link down. Saying "this
            # project chose it" would be the stronger claim, and a false one.
            provenance = target.source or "no source recorded"
            lines.append(f"  {'':<17} {_paint(provenance, _COLOUR[INFO], colour)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_manifest_diff(payload: dict) -> str:
    left = payload["left"]
    right = payload["right"]
    delta = payload["delta"]

    lines = [
        f"manifest diff: {left['path']} -> {right['path']}",
        f"  schema_version: {left['schema_version']} -> {right['schema_version']}",
        f"  generated_by: {left['generated_by']} -> {right['generated_by']}",
    ]

    if left["slug"] or right["slug"]:
        lines.append(f"  slug: {left['slug']} -> {right['slug']}")

    # "source outputs" read as a count of something belonging to the source
    # image. It is the number of delivery files the capture recorded.
    lines.append(f"  outputs: {left['outputs_count']} -> {right['outputs_count']}")

    if payload["identical"]:
        lines.append("")
        lines.append("  identical captures")
        return "\n".join(lines)

    lines.append("")
    if delta["schema_version_changed"]:
        lines.append("  schema_version changed")
    if delta["generated_by_changed"]:
        lines.append("  generated_by changed")
    if delta["slug_changed"]:
        lines.append("  slug changed")
    if delta["capture_id_changed"]:
        lines.append("  capture_id changed")
    if delta.get("boundary_changed"):
        # Worth its own line rather than folding into "capture_id changed": the
        # boundary is the sentence saying these hashes do not establish
        # ownership, rights or approval, so a rewritten one is a claim being
        # made on the manifest's authority.
        lines.append("  boundary changed: the capture's own disclaimer differs")

    if delta["source"]:
        lines.append("")
        lines.append("  source differences:")
        for item in delta["source"]:
            lines.append(
                f"    {item['key']}: {item['left']} -> {item['right']}"
            )

    if delta["skipped"]["changed"]:
        lines.append("")
        lines.append(
            f"  skipped changed: {delta['skipped']['left_count']} -> {delta['skipped']['right_count']}"
        )

    if delta["findings"]["changed"]:
        lines.append("")
        lines.append(
            f"  findings changed: {delta['findings']['left_count']} -> {delta['findings']['right_count']}"
        )

    output_delta = delta["outputs"]
    if output_delta["added"]:
        lines.append("")
        lines.append("  outputs added:")
        for item in output_delta["added"]:
            lines.append(f"    {item['target']}: {item['file']}")
    if output_delta["removed"]:
        lines.append("")
        lines.append("  outputs removed:")
        for item in output_delta["removed"]:
            lines.append(f"    {item['target']}: {item['file']}")

    if output_delta["changed"]:
        lines.append("")
        lines.append("  outputs changed:")
        for item in output_delta["changed"]:
            lines.append(f"    {item['target']}:")
            for change in item["changes"]:
                lines.append(
                    f"      {change['key']}: {change['left']} -> {change['right']}"
                )

    if delta["output_issues"]:
        lines.append("")
        lines.append("  manifest issues:")
        lines.extend([f"    {issue}" for issue in delta["output_issues"]])

    return "\n".join(lines)
