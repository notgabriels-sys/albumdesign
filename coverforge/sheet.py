"""Contact-sheet generation for quick visual review of variant batches."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .imageops import normalise

CONTACT_SHEET_DEFAULT_SIZE = 580
CONTACT_SHEET_DEFAULT_COLUMNS = 4
CONTACT_SHEET_DEFAULT_GAP = 20
CONTACT_SHEET_LABEL_HEIGHT = 24


@dataclass
class SheetResult:
    """Structured summary of a generated contact sheet."""

    out: Path
    master_count: int
    columns: int
    rows: int
    width: int
    height: int

    def as_dict(self) -> dict:
        return {
            "output": str(self.out),
            "master_count": self.master_count,
            "columns": self.columns,
            "rows": self.rows,
            "width": self.width,
            "height": self.height,
        }


def _thumbnail(im: Image.Image, size: int) -> Image.Image:
    """Create a square preview, preserving aspect ratio with crop fallback."""
    return ImageOps.fit(
        im, (size, size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )


def build_sheet(
    paths: list[Path],
    out: Path,
    *,
    columns: int = CONTACT_SHEET_DEFAULT_COLUMNS,
    thumb_size: int = CONTACT_SHEET_DEFAULT_SIZE,
    gap: int = CONTACT_SHEET_DEFAULT_GAP,
    show_labels: bool = True,
    title: str | None = None,
    background: str = "#f7f7f8",
) -> SheetResult:
    """Create one contact-sheet image and return a compact summary."""
    if not paths:
        raise ValueError("no images provided")
    if columns < 1:
        raise ValueError("columns must be at least 1")
    if thumb_size < 64:
        raise ValueError("thumb-size is too small")

    if not out.suffix:
        out = out.with_suffix(".jpg")

    rendered = []
    for path in paths:
        normalized = normalise(path)
        rendered.append((path, normalized))

    rendered_count = len(rendered)
    rows = math.ceil(rendered_count / columns)
    label_height = CONTACT_SHEET_LABEL_HEIGHT if show_labels else 0
    cell_height = thumb_size + label_height
    title_height = 40 if title else 0
    title_padding = 20 if title else 0

    width = gap * (columns + 1) + columns * thumb_size
    height = gap * (rows + 1) + rows * cell_height + title_height + title_padding
    if rows == 0:
        height = 120

    sheet = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    if title:
        draw.text((gap, gap), title, fill="#111111", font=font)
        title_offset = title_height + title_padding
    else:
        title_offset = 0

    for index, (source, im) in enumerate(rendered):
        row, column = divmod(index, columns)
        x = gap + column * (thumb_size + gap)
        y = title_offset + gap + row * (cell_height + gap)

        thumb = _thumbnail(im, thumb_size)
        sheet.paste(thumb, (x, y))

        if show_labels:
            label_top = y + thumb_size
            text_color = "#111111"
            text = source.stem
            draw.rectangle(
                (x, label_top, x + thumb_size, label_top + CONTACT_SHEET_LABEL_HEIGHT),
                fill="#ffffff",
            )
            draw.text((x + 6, label_top + 6), text, fill=text_color, font=font)

    out.parent.mkdir(parents=True, exist_ok=True)
    # Render to memory, then write through the same guard the delivery files
    # use. Image.save() opens the path plainly, so a symlink sitting at -o was
    # followed and whatever it pointed at was overwritten with a JPEG. Proved by
    # destroying a text file that way before this was fixed.
    buf = io.BytesIO()
    sheet.save(
        buf, format="JPEG", quality=90, optimize=True, progressive=False, subsampling=0
    )
    # Imported here rather than at module scope: build imports sheet for the
    # --sheet flag, so a top-level import would be circular.
    from .build import write_new_bytes

    write_new_bytes(out, buf.getvalue())

    return SheetResult(
        out=out,
        master_count=rendered_count,
        columns=columns,
        rows=rows,
        width=width,
        height=height,
    )
