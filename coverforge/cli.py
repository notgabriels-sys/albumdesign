"""coverforge command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import report
from .audit import run_audit
from .build import build, summarise
from .imageops import ImageError, SourceImage, inspect, is_image_path, slugify
from .package import PackageResult, build_package
from .preflight import ERROR, WARN, check, worst_level
from .sheet import build_sheet
from .manifest import compare_manifests, load_manifest
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
            found.extend(
                sorted(p for p in path.iterdir() if p.is_file() and is_image_path(p))
            )
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
        worst = max(
            worst,
            worst_level(findings),
            key=lambda lvl: {"info": 0, "warn": 1, "error": 2}[lvl],
        )

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
    if any(r.skipped for r in results) or any(
        o.over_cap for r in results for o in r.outputs
    ):
        return EXIT_FINDINGS
    return EXIT_OK


def _add_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--only", help="comma-separated target keys, e.g. spotify,bandcamp"
    )
    parser.add_argument("--group", help="comma-separated groups, e.g. dsp,social")
    parser.add_argument(
        "--targets-file", help="replace the built-in target definitions"
    )
    parser.add_argument(
        "--extra-targets", help="merge extra/overriding target definitions on top"
    )


def cmd_sheet(args) -> int:
    masters = collect_masters(args.masters)
    if not masters:
        print("no images found", file=sys.stderr)
        return EXIT_USAGE

    if args.columns < 1:
        print("--columns must be at least 1", file=sys.stderr)
        return EXIT_USAGE

    if args.thumb_size < 64:
        print("--thumb-size is too small", file=sys.stderr)
        return EXIT_USAGE

    failures = 0
    try:
        result = build_sheet(
            masters,
            Path(args.out),
            columns=args.columns,
            thumb_size=args.thumb_size,
            gap=args.gap,
            show_labels=not args.no_labels,
            title=args.title,
        )
    except ImageError as exc:
        print(exc, file=sys.stderr)
        failures += 1
        result = None
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE

    if failures:
        return EXIT_USAGE

    if args.json:
        print(json.dumps({"sheet": result.as_dict() if result else {}}, indent=2))
        return EXIT_OK if result else EXIT_USAGE

    if result:
        print(f"wrote {result.out} ({result.master_count} masters)")
    return EXIT_OK if result else EXIT_USAGE


def cmd_audit(args) -> int:
    target_set = _load(args)
    targets = _selected(args, target_set)
    bundles = [Path(raw) for raw in args.deliveries]

    try:
        results = run_audit(bundles, targets)
    except (ValueError, FileNotFoundError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        print(
            json.dumps({"bundles": [result.as_dict() for result in results]}, indent=2)
        )
        return EXIT_OK if all(result.ok for result in results) else EXIT_FINDINGS

    exit_code = EXIT_OK
    for result in results:
        marker = "ok" if result.ok else "findings"
        print(f"{marker}: {result.bundle} (slug={result.slug or 'unknown'})")
        if result.missing_targets:
            print(f"  missing: {', '.join(result.missing_targets)}")
            exit_code = EXIT_FINDINGS
        if result.malformed_files:
            print(f"  malformed files: {', '.join(result.malformed_files)}")
            exit_code = EXIT_FINDINGS
        if result.missing_files:
            print(f"  missing files: {', '.join(result.missing_files)}")
            exit_code = EXIT_FINDINGS
        if result.dimension_mismatches:
            print(f"  dimension mismatches: {', '.join(result.dimension_mismatches)}")
            exit_code = EXIT_FINDINGS
        if result.format_mismatches:
            print(f"  format mismatches: {', '.join(result.format_mismatches)}")
            exit_code = EXIT_FINDINGS

        if result.extra_targets:
            print(f"  extra targets present: {', '.join(result.extra_targets)}")

        if not result.ok:
            continue

    if not results:
        print("no bundles found", file=sys.stderr)
        return EXIT_USAGE

    return exit_code


def _next_zip_name(out_dir: Path, base_name: str) -> Path:
    candidate = out_dir / f"{base_name}.zip"
    if not candidate.exists():
        return candidate

    index = 1
    while True:
        candidate = out_dir / f"{base_name}-{index:02d}.zip"
        if not candidate.exists():
            return candidate
        index += 1


def cmd_package(args) -> int:
    target_set = _load(args)
    targets = _selected(args, target_set)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    try:
        results = run_audit([Path(raw) for raw in args.deliveries], targets)
    except (ValueError, FileNotFoundError) as exc:
        print(f"package failed: {exc}", file=sys.stderr)
        return EXIT_USAGE

    packages: list[PackageResult] = []
    skipped = 0

    for audit_result in results:
        if not audit_result.ok and not args.force:
            skipped += 1
            continue

        if audit_result.slug:
            base = slugify(audit_result.slug)
        else:
            base = slugify(audit_result.bundle.name)
        if args.name:
            base = (
                slugify(args.name)
                if len(results) == 1
                else slugify(f"{args.name}-{base}")
            )

        path = _next_zip_name(out_root, base)

        packages.append(build_package(audit_result, path))

    if args.json:
        payload = {
            "packages": [item.as_dict() for item in packages],
            "packages_skipped": skipped,
        }
        print(json.dumps(payload, indent=2))
        if not packages:
            return EXIT_FINDINGS if skipped else EXIT_USAGE
        if skipped or any(not package.ok for package in packages):
            return EXIT_FINDINGS
        return EXIT_OK

    if not packages:
        if skipped:
            print(
                "no package produced due findings; pass --force to include",
                file=sys.stderr,
            )
            return EXIT_FINDINGS
        print("no package produced", file=sys.stderr)
        return EXIT_USAGE

    for package in packages:
        status = "ok" if package.ok else "warn"
        print(f"{status}: {package.zip_path}")

    if skipped:
        print(
            f"skipped {skipped} delivery bundle(s) with findings; pass --force to include"
        )
        return EXIT_FINDINGS

    if any(not package.ok for package in packages):
        return EXIT_FINDINGS

    return EXIT_OK


def cmd_manifest(args) -> int:
    try:
        left_payload, left_path = load_manifest(args.left)
        right_payload, right_path = load_manifest(args.right)
        diff = compare_manifests(left_payload, right_payload, left_path, right_path)
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"manifest diff failed: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        print(json.dumps(diff, indent=2))
        return EXIT_OK if diff["identical"] else EXIT_FINDINGS

    print(report.format_manifest_diff(diff))
    return EXIT_OK if diff["identical"] else EXIT_FINDINGS


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
    p_check.add_argument(
        "masters", nargs="+", help="image files or directories of images"
    )
    p_check.add_argument(
        "--flatten", default="#ffffff", help="colour used behind transparency"
    )
    p_check.add_argument("--allow-upscale", action="store_true")
    p_check.add_argument(
        "--strict", action="store_true", help="exit non-zero on warnings too"
    )
    p_check.add_argument("--json", action="store_true")
    _add_target_flags(p_check)
    p_check.set_defaults(func=cmd_check)

    p_build = sub.add_parser("build", help="write the delivery pack")
    p_build.add_argument(
        "masters", nargs="+", help="image files or directories of images"
    )
    p_build.add_argument("-o", "--out", required=True, help="output directory")
    p_build.add_argument("--name", help="release name used for output filenames")
    p_build.add_argument(
        "--flatten", default="#ffffff", help="colour used behind transparency"
    )
    p_build.add_argument("--allow-upscale", action="store_true")
    p_build.add_argument(
        "--dry-run", action="store_true", help="report what would be written"
    )
    p_build.add_argument("--json", action="store_true")
    _add_target_flags(p_build)
    p_build.set_defaults(func=cmd_build)

    p_sheet = sub.add_parser(
        "sheet", help="build a contact sheet from one or more masters"
    )
    p_sheet.add_argument(
        "masters", nargs="+", help="image files or directories of images"
    )
    p_sheet.add_argument(
        "-o", "--out", required=True, help="output path for the contact sheet image"
    )
    p_sheet.add_argument("--columns", type=int, default=4, help="thumbnails per row")
    p_sheet.add_argument(
        "--thumb-size", type=int, default=580, help="square preview size in pixels"
    )
    p_sheet.add_argument(
        "--gap", type=int, default=20, help="spacing around and between tiles in pixels"
    )
    p_sheet.add_argument("--title", help="header text shown at the top of the sheet")
    p_sheet.add_argument(
        "--no-labels",
        action="store_true",
        help="hide filename labels below each thumbnail",
    )
    p_sheet.add_argument("--json", action="store_true")
    p_sheet.set_defaults(func=cmd_sheet)

    p_audit = sub.add_parser("audit", help="validate one or more delivery bundles")
    p_audit.add_argument("deliveries", nargs="+", help="delivery folders")
    p_audit.add_argument("--json", action="store_true")
    _add_target_flags(p_audit)
    p_audit.set_defaults(func=cmd_audit)

    p_package = sub.add_parser("package", help="zip one or more delivery bundles")
    p_package.add_argument("deliveries", nargs="+", help="delivery folders")
    p_package.add_argument("-o", "--out", required=True, help="output directory")
    p_package.add_argument("--name", help="bundle filename prefix")
    p_package.add_argument(
        "--force", action="store_true", help="package bundles even with findings"
    )
    p_package.add_argument("--json", action="store_true")
    _add_target_flags(p_package)
    p_package.set_defaults(func=cmd_package)

    p_manifest = sub.add_parser(
        "manifest", help="compare manifest.json between two exports or bundles"
    )
    p_manifest.add_argument("left", help="left manifest.json path or bundle directory")
    p_manifest.add_argument(
        "right", help="right manifest.json path or bundle directory"
    )
    p_manifest.add_argument("--json", action="store_true")
    p_manifest.set_defaults(func=cmd_manifest)

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
