"""Loading and validation of delivery-target definitions."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_TARGETS = Path(__file__).with_name("targets.toml")

VALID_FORMATS = {"jpeg", "png"}
VALID_FITS = {"cover", "pad"}
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
TARGET_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
MAX_SELECTED_TARGETS = 64
MAX_TARGET_KEY_LENGTH = 64
MAX_TARGET_NAME_LENGTH = 256
MAX_TARGET_TEXT_LENGTH = 4_096
MAX_TARGET_EDGE = 16_384
MAX_TARGET_PIXELS = 64_000_000


class SpecError(ValueError):
    """A targets file is malformed."""


def is_portable_target_key(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_TARGET_KEY_LENGTH
        and TARGET_KEY.fullmatch(value) is not None
    )


def _reject_casefold_key_collisions(keys, context: str) -> None:
    seen: dict[str, str] = {}
    for key in keys:
        folded = key.casefold()
        previous = seen.get(folded)
        if previous is not None and previous != key:
            raise SpecError(
                f"{context}: target keys {previous!r} and {key!r} "
                "collide case-insensitively"
            )
        seen[folded] = key


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    group: str
    width: int
    height: int
    format: str
    quality: int = 92
    min_source: int = 0
    max_bytes: int | None = None
    fit: str = "cover"
    pad_style: str = "blur"
    notes: str = ""
    source: str = ""

    @property
    def is_square(self) -> bool:
        return self.width == self.height

    @property
    def extension(self) -> str:
        return "jpg" if self.format == "jpeg" else "png"

    @property
    def dimensions(self) -> str:
        return f"{self.width}x{self.height}"


def validate_target(target: Target) -> Target:
    """Validate a Target regardless of whether it came from TOML or Python."""
    label = f"target {target.key!r}"
    if not is_portable_target_key(target.key):
        raise SpecError(
            f"{label}: key must use only letters, digits, '_' or '-', "
            "with no path separators or leading dot"
        )
    if not isinstance(target.name, str) or not target.name.strip():
        raise SpecError(f"{label}: name must be a non-empty string")
    if len(target.name) > MAX_TARGET_NAME_LENGTH:
        raise SpecError(
            f"{label}: name exceeds {MAX_TARGET_NAME_LENGTH} characters"
        )
    if not isinstance(target.group, str) or not target.group.strip():
        raise SpecError(f"{label}: group must be a non-empty string")
    if len(target.group) > MAX_TARGET_NAME_LENGTH:
        raise SpecError(
            f"{label}: group exceeds {MAX_TARGET_NAME_LENGTH} characters"
        )
    if (
        not isinstance(target.width, int)
        or isinstance(target.width, bool)
        or not isinstance(target.height, int)
        or isinstance(target.height, bool)
    ):
        raise SpecError(f"{label}: width and height must be integers")
    if target.width <= 0 or target.height <= 0:
        raise SpecError(f"{label}: width and height must be positive")
    if target.width > MAX_TARGET_EDGE or target.height > MAX_TARGET_EDGE:
        raise SpecError(
            f"{label}: width and height must not exceed {MAX_TARGET_EDGE} pixels"
        )
    if target.width * target.height > MAX_TARGET_PIXELS:
        raise SpecError(
            f"{label}: target canvas exceeds {MAX_TARGET_PIXELS} pixels"
        )
    if not isinstance(target.format, str) or target.format not in VALID_FORMATS:
        raise SpecError(
            f"{label}: format must be one of {sorted(VALID_FORMATS)}, "
            f"got {target.format!r}"
        )
    if (
        not isinstance(target.quality, int)
        or isinstance(target.quality, bool)
        or not 1 <= target.quality <= 100
    ):
        raise SpecError(
            f"{label}: quality must be an integer between 1 and 100, "
            f"got {target.quality!r}"
        )
    if (
        not isinstance(target.min_source, int)
        or isinstance(target.min_source, bool)
        or target.min_source < 0
    ):
        raise SpecError(
            f"{label}: min_source must be a non-negative integer, "
            f"got {target.min_source!r}"
        )
    if target.max_bytes is not None and (
        not isinstance(target.max_bytes, int)
        or isinstance(target.max_bytes, bool)
        or target.max_bytes <= 0
    ):
        raise SpecError(
            f"{label}: max_bytes must be a positive integer or omitted, "
            f"got {target.max_bytes!r}"
        )
    if not isinstance(target.fit, str) or target.fit not in VALID_FITS:
        raise SpecError(
            f"{label}: fit must be one of {sorted(VALID_FITS)}, got {target.fit!r}"
        )
    if not isinstance(target.pad_style, str) or (
        target.pad_style != "blur" and HEX_COLOUR.fullmatch(target.pad_style) is None
    ):
        raise SpecError(
            f"{label}: pad_style must be 'blur' or a #rrggbb colour, "
            f"got {target.pad_style!r}"
        )
    for field_name in ("notes", "source"):
        value = getattr(target, field_name)
        if not isinstance(value, str):
            raise SpecError(f"{label}: {field_name} must be a string")
        if len(value) > MAX_TARGET_TEXT_LENGTH:
            raise SpecError(
                f"{label}: {field_name} exceeds {MAX_TARGET_TEXT_LENGTH} characters"
            )
    return target


def validate_targets(targets: list[Target]) -> list[Target]:
    """Validate one bounded, case-insensitively unique bundle target set."""
    if len(targets) > MAX_SELECTED_TARGETS:
        raise SpecError(
            f"selected {len(targets)} targets; a delivery bundle supports "
            f"at most {MAX_SELECTED_TARGETS}"
        )
    seen: dict[str, str] = {}
    for target in targets:
        validate_target(target)
        folded = target.key.casefold()
        previous = seen.get(folded)
        if previous is not None:
            raise SpecError(
                f"duplicate target keys {previous!r} and {target.key!r} "
                "collide case-insensitively"
            )
        seen[folded] = target.key
    return targets


@dataclass
class TargetSet:
    targets: dict[str, Target] = field(default_factory=dict)
    reviewed: str = ""

    def __iter__(self):
        return iter(self.targets.values())

    def __len__(self) -> int:
        return len(self.targets)

    @property
    def groups(self) -> list[str]:
        seen: list[str] = []
        for t in self.targets.values():
            if t.group not in seen:
                seen.append(t.group)
        return seen

    def select(self, only: list[str] | None = None, groups: list[str] | None = None) -> list[Target]:
        """Pick targets by key and/or group. No filters means everything."""
        if not only and not groups:
            selected = list(self.targets.values())
            return validate_targets(selected)

        chosen: dict[str, Target] = {}
        for key in only or []:
            if key not in self.targets:
                raise SpecError(f"unknown target {key!r}. known: {', '.join(sorted(self.targets))}")
            chosen[key] = self.targets[key]

        known_groups = set(self.groups)
        for group in groups or []:
            if group not in known_groups:
                raise SpecError(f"unknown group {group!r}. known: {', '.join(self.groups)}")
            for target in self.targets.values():
                if target.group == group:
                    chosen[target.key] = target

        # Keep declaration order rather than selection order.
        selected = [t for t in self.targets.values() if t.key in chosen]
        return validate_targets(selected)


def _require(raw: dict, key: str, target_key: str, kind: type):
    if key not in raw:
        raise SpecError(f"target {target_key!r} is missing required field {key!r}")
    value = raw[key]
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise SpecError(f"target {target_key!r}: {key!r} must be {kind.__name__}, got {value!r}")
    return value


def _parse_target(key: str, raw: dict) -> Target:
    # The key is interpolated straight into the output filename, so a key
    # carrying separators or dot segments would write outside the pack. The
    # slug is checked for exactly this in build(); the key was not, and
    # --extra-targets lets anyone supply one.
    if not isinstance(raw, dict):
        raise SpecError(f"target {key!r}: definition must be a table")

    name = raw.get("name", key)
    group = raw.get("group", "other")
    notes = raw.get("notes", "")
    source = raw.get("source", "")

    fmt = _require(raw, "format", key, str).lower()
    fit_raw = raw.get("fit", "cover")
    fit = fit_raw.lower() if isinstance(fit_raw, str) else fit_raw
    pad_style = raw.get("pad_style", "blur")

    width = _require(raw, "width", key, int)
    height = _require(raw, "height", key, int)
    quality = raw.get("quality", 92)
    min_source = raw.get("min_source", 0)
    max_bytes = raw.get("max_bytes")

    return validate_target(Target(
        key=key,
        name=name,
        group=group,
        width=width,
        height=height,
        format=fmt,
        quality=quality,
        min_source=min_source,
        max_bytes=max_bytes,
        fit=fit,
        pad_style=pad_style,
        notes=notes,
        source=source,
    ))


def load_targets(path: Path | None = None, extra: Path | None = None) -> TargetSet:
    """Load the built-in targets, optionally replaced or extended by a user file.

    `path` replaces the built-in set outright; `extra` merges on top of it, so a
    project can override a single target without restating all of them.
    """
    base = _load_file(path or BUILTIN_TARGETS)
    if extra is not None:
        overlay = _load_file(extra)
        _reject_casefold_key_collisions(
            [*base.targets, *overlay.targets],
            f"{path or BUILTIN_TARGETS} and {extra}",
        )
        base.targets.update(overlay.targets)
        base.reviewed = overlay.reviewed or base.reviewed
    if not base.targets:
        raise SpecError("no targets defined")
    return base


def _load_file(path: Path) -> TargetSet:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SpecError(f"targets file not found: {path}") from None
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise SpecError(f"could not read targets file {path}: {reason}") from None
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"could not parse {path}: {exc}") from None

    section = raw.get("targets")
    if section is None:
        raise SpecError(f"{path} has no [targets.*] tables")
    if not isinstance(section, dict):
        raise SpecError(f"{path}: [targets] must contain one table per target")

    _reject_casefold_key_collisions(section, str(path))
    targets = {key: _parse_target(key, value) for key, value in section.items()}
    reviewed = str(raw.get("meta", {}).get("reviewed", ""))
    return TargetSet(targets=targets, reviewed=reviewed)
