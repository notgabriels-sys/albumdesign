"""Command-line interface for coverforge."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Sequence

from coverforge import __version__
from coverforge.checks import check_cover
from coverforge.report import Status
from coverforge.spec import DEFAULT_PROFILE, PROFILES, Spec, get_profile


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coverforge",
        description="Validate album cover artwork against distribution requirements.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    check = subparsers.add_parser(
        "check",
        help="check one or more cover images against the requirements",
        description="Check one or more cover images against the requirements.",
    )
    check.add_argument("paths", nargs="+", metavar="IMAGE", help="path(s) to cover image(s)")
    check.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help=f"distributor requirement preset (default: {DEFAULT_PROFILE})",
    )
    check.add_argument(
        "--min-size",
        type=int,
        metavar="PX",
        help=f"minimum width/height in pixels (default: {Spec.min_pixels})",
    )
    check.add_argument(
        "--recommended-size",
        type=int,
        metavar="PX",
        help=f"recommended width/height in pixels (default: {Spec.recommended_pixels})",
    )
    check.add_argument(
        "--no-square",
        action="store_true",
        help="do not require a square (1:1) image",
    )
    check.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures (non-zero exit)",
    )
    color = check.add_mutually_exclusive_group()
    color.add_argument(
        "--color",
        dest="color",
        action="store_true",
        default=None,
        help="force coloured output",
    )
    color.add_argument(
        "--no-color",
        dest="color",
        action="store_false",
        help="disable coloured output",
    )
    check.set_defaults(func=_cmd_check)

    return parser


def _spec_from_args(args: argparse.Namespace) -> Spec:
    base = get_profile(args.profile)
    overrides: dict[str, object] = {}
    if args.min_size is not None:
        overrides["min_pixels"] = args.min_size
    if args.recommended_size is not None:
        overrides["recommended_pixels"] = args.recommended_size
    if args.no_square:
        overrides["require_square"] = False
    return dataclasses.replace(base, **overrides)


def _use_color(choice: bool | None) -> bool:
    if choice is not None:
        return choice
    # Respect the NO_COLOR convention and only colourise real terminals.
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _cmd_check(args: argparse.Namespace) -> int:
    spec = _spec_from_args(args)
    color = _use_color(args.color)

    worst = Status.PASS
    for index, path in enumerate(args.paths):
        report = check_cover(path, spec)
        if index:
            print()
        print(report.render(color=color))
        if report.worst.severity > worst.severity:
            worst = report.worst

    if worst is Status.FAIL:
        return 1
    if worst is Status.WARN and args.strict:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
