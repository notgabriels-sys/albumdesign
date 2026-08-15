"""coverforge command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import report
from .build import build, summarise
from .contactsheet import ContactSheetError, plan_contact_sheet, write_contact_sheet
from .imageops import ImageError, SourceImage, inspect, is_image_path, slugify
from .preflight import ERROR, WARN, check, worst_level
from .specs import SpecError, TargetSet, load_targets

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def collect_masters(paths: list[str]) -> list[Path]:
    """Expand files and directories into a sorted list of image paths."""
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(p for p in path.iterdir() if p.is_file() and is_image_path(p)))
        else:
            found.append(path)
    return found


def _load(args) -> TargetSet:
    target_set = load_targets(
        Path(args.targets_file) if args.targets_file else None,
        Path(args.extra_targets) if args.extra_targets else None,
    )
    return target_set


def _selected(args, target_set: TargetSet):
    return target_set.select(_split_list(args.only), _split_list(args.group))


def cmd_targets(args) -> int:
    target_set = _load(args)
    if args.json:
        payload = {
            "reviewed": target_set.reviewed,
            "targets": [
                {
                    "key": t.key,
                    "name": t.name,
                    "group": t.group,
                    "width": t.width,
                    "height": t.height,
                    "format": t.format,
                    "quality": t.quality,
                    "min_source": t.min_source,
                    "max_bytes": t.max_bytes,
                    "fit": t.fit,
                    "notes": t.notes,
                    "source": t.source,
                }
                for t in target_set
            ],
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    print(report.format_targets(target_set, report.use_colour()))
    return EXIT_OK


def cmd_check(args) -> int:
    target_set = _load(args)
    targets = _selected(args, target_set)
    masters = collect_masters(args.masters)
    if not masters:
        print("no images found", file=sys.stderr)
        return EXIT_USAGE

    colour = report.use_colour()
    payload = []
    worst = "info"
    failed_reads = 0

    for path in masters:
        try:
            src: SourceImage = inspect(path)
        except ImageError as exc:
            failed_reads += 1
            if args.json:
                payload.append({"master": str(path), "error": str(exc)})
            else:
                print(f"{path}: {exc}", file=sys.stderr)
            continue

        findings = check(src, targets, args.flatten, args.allow_upscale)
        worst = max(worst, worst_level(findings), key=lambda lvl: {"info": 0, "warn": 1, "error": 2}[lvl])

        if args.json:
            payload.append(
                {
                    "master": str(path),
                    "dimensions": src.dimensions,
                    "mode": src.mode,
                    "bytes": src.file_bytes,
                    "findings": [f.as_dict() for f in findings],
                }
            )
        else:
            print(report.format_check(src, findings, targets, colour))
            print()

    if args.json:
        print(json.dumps({"results": payload}, indent=2))

    if failed_reads:
        return EXIT_USAGE
    if worst == ERROR:
        return EXIT_FINDINGS
    if worst == WARN and args.strict:
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_build(args) -> int:
    target_set = _load(args)
    targets = _selected(args, target_set)
    masters = collect_masters(args.masters)
    if not masters:
        print("no images found", file=sys.stderr)
        return EXIT_USAGE

    if args.name and len(masters) > 1:
        print("--name only makes sense with a single master", file=sys.stderr)
        return EXIT_USAGE

    out_root = Path(args.out)
    colour = report.use_colour()
    results = []
    failed_reads = 0

    for path in masters:
        try:
            src = inspect(path)
        except ImageError as exc:
            failed_reads += 1
            print(f"{path}: {exc}", file=sys.stderr)
            continue

        slug = slugify(args.name) if args.name else slugify(path.stem)
        # One folder per master keeps batches of variants from colliding.
        out_dir = out_root if len(masters) == 1 else out_root / slug

        result = build(
            src,
            targets,
            out_dir=out_dir,
            slug=slug,
            flatten_colour=args.flatten,
            allow_upscale=args.allow_upscale,
            dry_run=args.dry_run,
        )
        results.append(result)

        if not args.json:
            print(report.format_build(result, colour))
            print()

    if args.json:
        print(json.dumps({"builds": [r.as_dict() for r in results]}, indent=2))
    elif results:
        print(summarise(results))

    if failed_reads:
        return EXIT_USAGE
    if any(r.skipped for r in results) or any(o.over_cap for r in results for o in r.outputs):
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_contact_sheet(args) -> int:
    """Create one offline contact-sheet review packet from selected artwork variants."""
    masters = collect_masters(args.masters)
    if not masters:
        print("no images found", file=sys.stderr)
        return EXIT_USAGE

    sources: list[SourceImage] = []
    failed_reads = 0
    for path in masters:
        try:
            sources.append(inspect(path))
        except ImageError as exc:
            failed_reads += 1
            print(f"{path}: {exc}", file=sys.stderr)
    if failed_reads:
        return EXIT_USAGE

    title = args.title or "Coverforge contact sheet"
    kwargs = {
        "title": title,
        "columns": args.columns,
        "cell_size": args.cell_size,
        "background": args.background,
    }
    try:
        result = (
            plan_contact_sheet(sources, Path(args.out), **kwargs)
            if args.dry_run
            else write_contact_sheet(sources, Path(args.out), **kwargs)
        )
    except ContactSheetError as exc:
        print(f"contact-sheet error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "contact_sheet": result.as_dict()}, indent=2))
    elif args.dry_run:
        print(
            f"Planned offline contact-sheet review: {result.source_count} variants "
            f"at {result.dimensions}"
        )
    else:
        print(f"Wrote offline contact-sheet review: {result.output_dir}")
        print(f"  {result.source_count} variants · {result.dimensions} · {result.columns} columns")
    return EXIT_OK


def _add_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--only", help="comma-separated target keys, e.g. spotify,bandcamp")
    parser.add_argument("--group", help="comma-separated groups, e.g. dsp,social")
    parser.add_argument("--targets-file", help="replace the built-in target definitions")
    parser.add_argument("--extra-targets", help="merge extra/overriding target definitions on top")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coverforge",
        description="Preflight release artwork and export a per-platform delivery pack.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_targets = sub.add_parser("targets", help="list the known delivery targets")
    p_targets.add_argument("--json", action="store_true")
    _add_target_flags(p_targets)
    p_targets.set_defaults(func=cmd_targets)

    p_check = sub.add_parser("check", help="report problems without writing anything")
    p_check.add_argument("masters", nargs="+", help="image files or directories of images")
    p_check.add_argument("--flatten", default="#ffffff", help="colour used behind transparency")
    p_check.add_argument("--allow-upscale", action="store_true")
    p_check.add_argument("--strict", action="store_true", help="exit non-zero on warnings too")
    p_check.add_argument("--json", action="store_true")
    _add_target_flags(p_check)
    p_check.set_defaults(func=cmd_check)

    p_build = sub.add_parser("build", help="write the delivery pack")
    p_build.add_argument("masters", nargs="+", help="image files or directories of images")
    p_build.add_argument("-o", "--out", required=True, help="output directory")
    p_build.add_argument("--name", help="release name used for output filenames")
    p_build.add_argument("--flatten", default="#ffffff", help="colour used behind transparency")
    p_build.add_argument("--allow-upscale", action="store_true")
    p_build.add_argument("--dry-run", action="store_true", help="report what would be written")
    p_build.add_argument("--json", action="store_true")
    _add_target_flags(p_build)
    p_build.set_defaults(func=cmd_build)

    p_contact_sheet = sub.add_parser(
        "contact-sheet", help="write an offline visual-review packet for artwork variants"
    )
    p_contact_sheet.add_argument("masters", nargs="+", help="image files or directories of images")
    p_contact_sheet.add_argument("-o", "--out", required=True, help="new output directory outside images")
    p_contact_sheet.add_argument("--title", help="review title shown in the HTML index")
    p_contact_sheet.add_argument("--columns", type=int, default=4, help="positive grid column count")
    p_contact_sheet.add_argument(
        "--cell-size", type=int, default=480, help="positive preview-cell size in pixels"
    )
    p_contact_sheet.add_argument("--background", default="#101116", help="preview background #rrggbb")
    p_contact_sheet.add_argument("--dry-run", action="store_true", help="validate and plan without writing")
    p_contact_sheet.add_argument("--json", action="store_true")
    p_contact_sheet.set_defaults(func=cmd_contact_sheet)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SpecError as exc:
        print(f"target spec error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
