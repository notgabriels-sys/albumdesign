"""Terminal formatting for check and build results."""

from __future__ import annotations

import os
import sys

from .build import BuildResult
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


def format_check(src: SourceImage, findings: list[Finding], targets: list[Target], colour: bool) -> str:
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

    blocked = {f.target for f in findings if f.level == ERROR}
    passing = [t for t in targets if t.key not in blocked]
    lines.append("")
    tick = _paint("ok", "\033[32m", colour)
    lines.append(f"  {tick} {len(passing)}/{len(targets)} targets clear: {', '.join(t.key for t in passing) or 'none'}")
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


def format_targets(target_set: TargetSet, colour: bool) -> str:
    lines = []
    if target_set.reviewed:
        lines.append(f"specs last reviewed {target_set.reviewed} - verify against your distributor")
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
        lines.append("")
    return "\n".join(lines).rstrip()
