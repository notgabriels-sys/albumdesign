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


class SpecError(ValueError):
    """A targets file is malformed."""


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
            return list(self.targets.values())

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
        return [t for t in self.targets.values() if t.key in chosen]


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
    if not key or key in {".", ".."} or any(c in key for c in "/\\") or key.startswith("."):
        raise SpecError(
            f"target {key!r}: key must be a plain name, with no path separators or leading dot"
        )

    fmt = _require(raw, "format", key, str).lower()
    if fmt not in VALID_FORMATS:
        raise SpecError(f"target {key!r}: format must be one of {sorted(VALID_FORMATS)}, got {fmt!r}")

    fit = str(raw.get("fit", "cover")).lower()
    if fit not in VALID_FITS:
        raise SpecError(f"target {key!r}: fit must be one of {sorted(VALID_FITS)}, got {fit!r}")

    pad_style = str(raw.get("pad_style", "blur"))
    if pad_style != "blur" and not HEX_COLOUR.match(pad_style):
        raise SpecError(f"target {key!r}: pad_style must be 'blur' or a #rrggbb colour, got {pad_style!r}")

    width = _require(raw, "width", key, int)
    height = _require(raw, "height", key, int)
    if width <= 0 or height <= 0:
        raise SpecError(f"target {key!r}: width and height must be positive")

    quality = int(raw.get("quality", 92))
    if not 1 <= quality <= 100:
        raise SpecError(f"target {key!r}: quality must be between 1 and 100, got {quality}")

    max_bytes = raw.get("max_bytes")
    if max_bytes is not None:
        max_bytes = int(max_bytes)
        if max_bytes <= 0:
            raise SpecError(f"target {key!r}: max_bytes must be positive")

    return Target(
        key=key,
        name=str(raw.get("name", key)),
        group=str(raw.get("group", "other")),
        width=width,
        height=height,
        format=fmt,
        quality=quality,
        min_source=int(raw.get("min_source", 0)),
        max_bytes=max_bytes,
        fit=fit,
        pad_style=pad_style,
        notes=str(raw.get("notes", "")),
        source=str(raw.get("source", "")),
    )


def load_targets(path: Path | None = None, extra: Path | None = None) -> TargetSet:
    """Load the built-in targets, optionally replaced or extended by a user file.

    `path` replaces the built-in set outright; `extra` merges on top of it, so a
    project can override a single target without restating all of them.
    """
    base = _load_file(path or BUILTIN_TARGETS)
    if extra is not None:
        overlay = _load_file(extra)
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
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"could not parse {path}: {exc}") from None

    section = raw.get("targets")
    if section is None:
        raise SpecError(f"{path} has no [targets.*] tables")
    if not isinstance(section, dict):
        raise SpecError(f"{path}: [targets] must contain one table per target")

    targets = {key: _parse_target(key, value) for key, value in section.items()}
    reviewed = str(raw.get("meta", {}).get("reviewed", ""))
    return TargetSet(targets=targets, reviewed=reviewed)
