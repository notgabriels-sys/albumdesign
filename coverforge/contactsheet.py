"""Create local, offline review packets for batches of artwork variants."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import imageops
from .imageops import ImageError, SourceImage

SHEET_FILENAME = "CONTACT_SHEET.jpg"
HTML_FILENAME = "CONTACT_SHEET.html"

DEFAULT_COLUMNS = 4
DEFAULT_CELL_SIZE = 480
DEFAULT_BACKGROUND = "#101116"

OUTER_PADDING = 32
HEADER_HEIGHT = 72
LABEL_HEIGHT = 48
GUTTER = 20
MAX_CANVAS_PIXELS = 80_000_000

_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ContactSheetError(ValueError):
    """Raised when a local contact-sheet packet cannot be safely produced."""


@dataclass(frozen=True)
class ContactSheetEntry:
    """One source image represented in a local review packet."""

    index: int
    filename: str
    dimensions: str
    mode: str


@dataclass(frozen=True)
class ContactSheetResult:
    """Owner-local paths and layout facts for a written review packet."""

    output_dir: Path
    image_path: Path
    html_path: Path
    title: str
    columns: int
    cell_size: int
    width: int
    height: int
    entries: tuple[ContactSheetEntry, ...]

    @property
    def source_count(self) -> int:
        """Return the number of source variants represented in the packet."""
        return len(self.entries)

    @property
    def dimensions(self) -> str:
        """Return the sheet's deterministic canvas geometry."""
        return f"{self.width}x{self.height}"

    def as_dict(self) -> dict:
        """Return an owner-local JSON-friendly command result."""
        return {
            "output_dir": str(self.output_dir),
            "contact_sheet": str(self.image_path),
            "html_index": str(self.html_path),
            "title": self.title,
            "source_count": self.source_count,
            "dimensions": self.dimensions,
            "columns": self.columns,
            "cell_size": self.cell_size,
        }


def write_contact_sheet(
    sources: list[SourceImage] | tuple[SourceImage, ...],
    output_dir: Path | str,
    *,
    title: str = "Coverforge contact sheet",
    columns: int = DEFAULT_COLUMNS,
    cell_size: int = DEFAULT_CELL_SIZE,
    background: str = DEFAULT_BACKGROUND,
) -> ContactSheetResult:
    """Write a fresh JPEG sheet and offline HTML index from inspected source images."""
    selected = tuple(sources)
    result = plan_contact_sheet(
        selected,
        output_dir,
        title=title,
        columns=columns,
        cell_size=cell_size,
        background=background,
    )
    sheet = _compose_sheet(selected, title=title, columns=columns, cell_size=cell_size, background=background)

    try:
        result.output_dir.mkdir(parents=True, exist_ok=False)
        sheet.save(result.image_path, format="JPEG", quality=92, progressive=False, subsampling=0)
        result.html_path.write_text(render_html_index(result), encoding="utf-8")
    except OSError as error:
        raise ContactSheetError(f"could not write contact-sheet packet: {error}") from error
    finally:
        sheet.close()
    return result


def plan_contact_sheet(
    sources: list[SourceImage] | tuple[SourceImage, ...],
    output_dir: Path | str,
    *,
    title: str = "Coverforge contact sheet",
    columns: int = DEFAULT_COLUMNS,
    cell_size: int = DEFAULT_CELL_SIZE,
    background: str = DEFAULT_BACKGROUND,
) -> ContactSheetResult:
    """Validate one packet layout and destination without writing any files."""
    selected = tuple(sources)
    _validate_inputs(selected, title, columns, cell_size, background)

    output_path = Path(output_dir).resolve()
    _reject_output_inside_source_dirs(output_path, selected)
    if output_path.exists():
        raise ContactSheetError(f"contact-sheet output directory already exists: {output_path.name}")

    width, height = sheet_dimensions(len(selected), columns, cell_size)
    entries = tuple(
        ContactSheetEntry(
            index=index,
            filename=source.path.name,
            dimensions=source.dimensions,
            mode=source.mode,
        )
        for index, source in enumerate(selected, start=1)
    )
    return ContactSheetResult(
        output_dir=output_path,
        image_path=output_path / SHEET_FILENAME,
        html_path=output_path / HTML_FILENAME,
        title=title,
        columns=columns,
        cell_size=cell_size,
        width=width,
        height=height,
        entries=entries,
    )


def sheet_dimensions(count: int, columns: int, cell_size: int) -> tuple[int, int]:
    """Return the deterministic canvas size for one planned contact sheet."""
    if count <= 0:
        raise ContactSheetError("contact sheet requires at least one source image")
    _positive_int(columns, "columns")
    _positive_int(cell_size, "cell size")
    rows = math.ceil(count / columns)
    width = OUTER_PADDING * 2 + columns * cell_size + (columns - 1) * GUTTER
    height = (
        OUTER_PADDING * 2
        + HEADER_HEIGHT
        + rows * (cell_size + LABEL_HEIGHT)
        + (rows - 1) * GUTTER
    )
    if width * height > MAX_CANVAS_PIXELS:
        raise ContactSheetError(
            "planned contact sheet exceeds the local canvas limit; reduce --cell-size or add --columns"
        )
    return width, height


def render_html_index(result: ContactSheetResult) -> str:
    """Render a local HTML index with no source paths or active source text."""
    rows = "\n".join(
        "      <tr>"
        f"<td>{entry.index:02d}</td>"
        f"<td>{escape(entry.filename)}</td>"
        f"<td>{escape(entry.dimensions)}</td>"
        f"<td>{escape(entry.mode)}</td>"
        "</tr>"
        for entry in result.entries
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(result.title)} — Coverforge contact sheet</title>
  <style>
    :root {{ color-scheme: dark; --ink: #101116; --surface: #181a21; --bone: #f1ede3; --muted: #aaa79f; --line: #343844; --accent: #bf9a63; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: radial-gradient(circle at top right, #24212d 0, var(--ink) 40rem); color: var(--bone); font: 16px/1.5 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 48px 24px 72px; }}
    header {{ border-bottom: 1px solid var(--line); padding-bottom: 28px; margin-bottom: 28px; }}
    .eyebrow {{ color: var(--accent); font-size: .75rem; letter-spacing: .13em; text-transform: uppercase; }}
    h1 {{ margin: 8px 0 10px; font: 600 clamp(2rem, 6vw, 4.75rem)/.95 system-ui, sans-serif; letter-spacing: -.06em; }}
    p, footer {{ color: var(--muted); max-width: 76ch; }}
    img {{ display: block; width: 100%; height: auto; border: 1px solid var(--line); background: var(--surface); }}
    table {{ width: 100%; margin-top: 28px; border-collapse: collapse; background: rgba(24, 26, 33, .78); }}
    th, td {{ text-align: left; vertical-align: top; padding: 11px 12px; border: 1px solid var(--line); word-break: break-word; }}
    th {{ color: var(--muted); font-size: .72rem; font-weight: 500; text-transform: uppercase; letter-spacing: .08em; }}
    footer {{ margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--line); font-size: .8rem; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="eyebrow">Local visual review · offline packet</div>
      <h1>{escape(result.title)}</h1>
      <p>{result.source_count} selected variant(s) · {escape(result.dimensions)} · {result.columns} columns</p>
    </header>
    <img src="{SHEET_FILENAME}" alt="{escape(result.title)} contact sheet">
    <table>
      <thead><tr><th>#</th><th>Filename</th><th>Dimensions</th><th>Mode</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
    <footer>Generated locally by Coverforge. This packet is a visual review aid; it does not record approval, ownership, rights, delivery, or platform acceptance.</footer>
  </main>
</body>
</html>
"""


def _validate_inputs(
    sources: tuple[SourceImage, ...],
    title: str,
    columns: int,
    cell_size: int,
    background: str,
) -> None:
    if not sources:
        raise ContactSheetError("contact sheet requires at least one source image")
    if not isinstance(title, str) or not title.strip() or any(ord(char) < 32 for char in title):
        raise ContactSheetError("contact-sheet title must be non-empty text without control characters")
    _positive_int(columns, "columns")
    _positive_int(cell_size, "cell size")
    if not isinstance(background, str) or not _HEX_COLOUR.fullmatch(background):
        raise ContactSheetError("contact-sheet background must be a #rrggbb colour")
    sheet_dimensions(len(sources), columns, cell_size)


def _positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContactSheetError(f"contact-sheet {label} must be a positive integer")


def _reject_output_inside_source_dirs(output_path: Path, sources: tuple[SourceImage, ...]) -> None:
    for source in sources:
        try:
            output_path.relative_to(source.path.parent.resolve())
        except ValueError:
            continue
        raise ContactSheetError(
            "contact-sheet output directory must be outside selected image directories"
        )


def _compose_sheet(
    sources: tuple[SourceImage, ...],
    *,
    title: str,
    columns: int,
    cell_size: int,
    background: str,
) -> Image.Image:
    width, height = sheet_dimensions(len(sources), columns, cell_size)
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((OUTER_PADDING, OUTER_PADDING + 18), "COVERFORGE CONTACT SHEET", fill="#f1ede3", font=font)
    draw.text(
        (OUTER_PADDING, OUTER_PADDING + 40),
        f"{len(sources)} variants · {_ascii_text(title)}",
        fill="#aaa79f",
        font=font,
    )

    for index, source in enumerate(sources, start=1):
        row, column = divmod(index - 1, columns)
        x = OUTER_PADDING + column * (cell_size + GUTTER)
        y = OUTER_PADDING + HEADER_HEIGHT + row * (cell_size + LABEL_HEIGHT + GUTTER)
        draw.rectangle((x, y, x + cell_size - 1, y + cell_size - 1), outline="#343844", width=1)
        normalised: Image.Image | None = None
        preview: Image.Image | None = None
        try:
            normalised = imageops.normalise(source.path, background)
            preview = ImageOps.contain(
                normalised, (cell_size, cell_size), method=Image.Resampling.LANCZOS
            )
            assert preview is not None
            preview_x = x + (cell_size - preview.width) // 2
            preview_y = y + (cell_size - preview.height) // 2
            canvas.paste(preview, (preview_x, preview_y))
        except (ImageError, OSError, ValueError) as error:
            canvas.close()
            raise ContactSheetError(f"could not compose contact-sheet preview: {error}") from error
        finally:
            if preview is not None:
                preview.close()
            if normalised is not None:
                normalised.close()
        draw.text((x, y + cell_size + 8), f"{index:02d} · {source.dimensions}", fill="#f1ede3", font=font)

    return canvas


def _ascii_text(value: str) -> str:
    """Keep bitmap labels portable when the default Pillow font lacks a glyph."""
    return value.encode("ascii", "replace").decode("ascii")
