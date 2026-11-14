"""PDF chart: a pattern as a printable, multi-page cross-stitch chart.

The document is one or more cover pages (thumbnail, sizes, the thread key with symbol,
code, name, stitches and skeins) followed by the chart: the grid split into pages in
reading order (left to right, then top to bottom). Neighbouring chart pages share
`OVERLAP` columns or rows, shaded on the page that repeats them. Each chart page draws
every stitched cell's symbol, thin lines between cells, a bold line every 10 cells counted
from the pattern's top-left and on the pattern's edges, row and column numbers every 10,
arrows at the centre row
and column, and a label stating the columns and rows it shows.

The cell side is `CELL_MM` on every paper; a bigger sheet holds more cells per page
(`chart_capacity`). In the colour variant cells are filled with their thread's colour and
the symbol is black or white, whichever reads better on it; the black-and-white variant
uses grey levels only. Symbols come from `key_symbols`, numbers only from the `Pattern`.
The same pattern and settings always give the same bytes.
"""

import io
import math
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal, get_args

import numpy as np
import numpy.typing as npt
from PIL import Image
from reportlab.lib.pagesizes import A2, A3, A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from cross_stitch.export.symbols import key_symbols
from cross_stitch.pattern import EMPTY, KeyEntry, Pattern

Variant = Literal["colour", "bw"]
Paper = Literal["A2", "A3", "A4", "A5"]
Orientation = Literal["portrait", "landscape"]
VARIANTS: tuple[Variant, ...] = get_args(Variant)
PAPERS: tuple[Paper, ...] = get_args(Paper)
ORIENTATIONS: tuple[Orientation, ...] = get_args(Orientation)

FONT_PATH = Path(__file__).with_name("DejaVuSans.ttf")
"""The chart font, DejaVu Sans, shipped with the package (see `FONT_SOURCE.md`)."""
_FONT = "DejaVuSans"

CELL_MM = 3.0
"""Side of one chart cell on paper, the same for every paper size."""
OVERLAP = 2
"""Columns (or rows) a chart page repeats from its left (or upper) neighbour."""

_PORTRAIT_SIZES: dict[Paper, tuple[float, float]] = {"A2": A2, "A3": A3, "A4": A4, "A5": A5}
_CELL = CELL_MM * mm
_MARGIN = 10 * mm
_HEADER = 8 * mm  # the label line above the grid
_GUTTER = 5 * mm  # numbers on the top and left, centre arrows on the bottom and right

_SYMBOL_SIZE = 6.5
_NUMBER_SIZE = 6.0
_THIN_LINE = 0.25
_BOLD_LINE = 1.0
_THIN_GREY = 0.6
_OVERLAP_GREY = 0.85
_DARK_FILL = 140.0  # below this luminance a colour cell takes a white symbol
_ARROW = 2.5 * mm

_KEY_ROW = 5 * mm
_KEY_TEXT_SIZE = 8.5
_TITLE_SIZE = 16.0
_INFO_SIZE = 9.0


def chart_capacity(paper: Paper, orientation: Orientation) -> tuple[int, int]:
    """(columns, rows) of cells one chart page holds on this paper and orientation.

    Margins and gutters are fixed lengths, so the counts follow the sheet:

    ========  ==========  ==========
    paper     portrait    landscape
    ========  ==========  ==========
    A2        130 x 185   188 x 127
    A3        89 x 127    130 x 86
    A4        60 x 86     89 x 57
    A5        39 x 57     60 x 36
    ========  ==========  ==========

    A change to these numbers re-splits every chart. The division is rounded before it is
    floored, so a sheet that holds a whole number of cells is not short of one by a float
    error (A4 portrait is exactly 60 columns).
    """
    width, height = _page_size(paper, orientation)
    columns = math.floor(round((width - 2 * _MARGIN - 2 * _GUTTER) / _CELL, 6))
    rows = math.floor(round((height - 2 * _MARGIN - _HEADER - 2 * _GUTTER) / _CELL, 6))
    return columns, rows


def render_pdf(
    pattern: Pattern,
    *,
    variant: Variant = "colour",
    paper: Paper = "A4",
    orientation: Orientation = "portrait",
) -> bytes:
    """The pattern as a PDF chart: cover page(s), then the chart pages."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    page_size = _page_size(paper, orientation)
    _register_font()
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=page_size, invariant=True, pageCompression=True)
    canvas.setTitle("Cross-stitch chart")
    document = _Document(canvas, pattern, key_symbols(pattern.key), variant == "colour", page_size)
    document.draw_cover()
    document.draw_chart(chart_capacity(paper, orientation))
    canvas.save()
    return buffer.getvalue()


def _page_size(paper: Paper, orientation: Orientation) -> tuple[float, float]:
    if paper not in _PORTRAIT_SIZES:
        raise ValueError(f"unknown paper {paper!r}; expected one of {PAPERS}")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"unknown orientation {orientation!r}; expected one of {ORIENTATIONS}")
    width, height = _PORTRAIT_SIZES[paper]
    return (height, width) if orientation == "landscape" else (width, height)


@cache
def _register_font() -> None:
    pdfmetrics.registerFont(TTFont(_FONT, str(FONT_PATH)))


_REC601 = np.array([0.299, 0.587, 0.114])
"""Luminance weights of sRGB, as greyscale printing uses them."""


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Luminance of an sRGB colour, 0-255."""
    return float(np.dot(_REC601, rgb))


def _key_text_width(value: str) -> float:
    return float(pdfmetrics.stringWidth(value, _FONT, _KEY_TEXT_SIZE))


def _rgb_fraction(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb
    return r / 255, g / 255, b / 255


@dataclass(frozen=True)
class _Band:
    """A run of columns (or rows) on one chart page."""

    start: int  # first cell, 0-based
    end: int  # one past the last cell
    repeated: int  # leading cells repeated from the previous band

    @property
    def size(self) -> int:
        return self.end - self.start


def _bands(length: int, capacity: int) -> Iterator[_Band]:
    """Split `length` cells into bands of at most `capacity`, neighbours sharing OVERLAP."""
    step = capacity - OVERLAP
    count = 1 if length <= capacity else 1 + math.ceil((length - capacity) / step)
    for k in range(count):
        start = k * step
        yield _Band(start, min(start + capacity, length), OVERLAP if k else 0)


@dataclass(frozen=True)
class _Document:
    canvas: Canvas
    pattern: Pattern
    symbols: list[str]
    colour: bool
    page_size: tuple[float, float]

    # --- cover --------------------------------------------------------------------------

    def draw_cover(self) -> None:
        canvas, pattern = self.canvas, self.pattern
        width, height = self.page_size
        top = height - _MARGIN
        canvas.setFont(_FONT, _TITLE_SIZE)
        canvas.drawString(_MARGIN, top - _TITLE_SIZE, "Cross-stitch chart")
        top = self._draw_thumbnail(top - _TITLE_SIZE - 4 * mm) - 6 * mm

        canvas.setFont(_FONT, _INFO_SIZE)
        for line in (
            f"Size: {pattern.width} x {pattern.height} stitches",
            f"Fabric: {pattern.fabric_count:g} count",
            f"Finished size: {pattern.width_in:.1f} x {pattern.height_in:.1f} in "
            f"({pattern.width_cm:.1f} x {pattern.height_cm:.1f} cm)",
            f"Total stitches: {pattern.total_stitches}",
        ):
            canvas.drawString(_MARGIN, top - _INFO_SIZE, line)
            top -= _INFO_SIZE + 2 * mm

        columns = self._key_columns(width)
        top = self._draw_key_header(columns, top - 4 * mm, continued=False)
        for entry, symbol in zip(pattern.key, self.symbols, strict=True):
            if top - _KEY_ROW < _MARGIN:
                canvas.showPage()
                top = self._draw_key_header(columns, height - _MARGIN, continued=True)
            self._draw_key_row(columns, top - _KEY_ROW + 1.5 * mm, entry, symbol)
            top -= _KEY_ROW
        canvas.showPage()

    def _draw_thumbnail(self, top: float) -> float:
        """Draw the thumbnail below `top`; return its bottom edge."""
        pattern, (width, height) = self.pattern, self.page_size
        scale = min(
            (width - 2 * _MARGIN) / pattern.width, (height - 2 * _MARGIN) * 0.4 / pattern.height
        )
        thumb_width, thumb_height = pattern.width * scale, pattern.height * scale
        bottom = top - thumb_height
        self.canvas.drawImage(
            ImageReader(self._thumbnail()), _MARGIN, bottom, width=thumb_width, height=thumb_height
        )
        self.canvas.setLineWidth(_THIN_LINE)
        self.canvas.setStrokeGray(0)
        self.canvas.rect(_MARGIN, bottom, thumb_width, thumb_height, stroke=1, fill=0)
        return bottom

    def _thumbnail(self) -> Image.Image:
        """One pixel per cell: the thread colour (its grey in black and white), bare white."""
        pattern = self.pattern
        palette = np.array(
            [entry.thread.rgb for entry in pattern.key] + [(255, 255, 255)], dtype=np.float64
        )
        pixels = palette[np.where(pattern.grid == EMPTY, len(pattern.key), pattern.grid)]
        if self.colour:
            return Image.fromarray(pixels.astype(np.uint8), mode="RGB")
        grey = pixels @ _REC601
        return Image.fromarray(np.rint(grey).astype(np.uint8), mode="L")

    def _key_columns(self, width: float) -> dict[str, float]:
        """Left edge of each key column (right edge for the two numbers)."""
        left = _MARGIN + (8 * mm if self.colour else 0)
        return {
            "swatch": _MARGIN,
            "symbol": left,
            "code": left + 14 * mm,
            "name": left + 30 * mm,
            "stitches": min(width - _MARGIN - 20 * mm, left + 125 * mm),
            "skeins": min(width - _MARGIN, left + 145 * mm),
        }

    def _draw_key_header(self, columns: dict[str, float], top: float, *, continued: bool) -> float:
        canvas = self.canvas
        canvas.setFillGray(0)
        canvas.setFont(_FONT, _INFO_SIZE + 1)
        title = "Thread key (continued)" if continued else "Thread key"
        canvas.drawString(_MARGIN, top - _INFO_SIZE, title)
        top -= _INFO_SIZE + 3 * mm
        baseline = top - _KEY_ROW + 1.5 * mm
        canvas.setFont(_FONT, _KEY_TEXT_SIZE)
        canvas.drawString(columns["symbol"], baseline, "Symbol")
        canvas.drawString(columns["code"], baseline, "Code")
        canvas.drawString(columns["name"], baseline, "Name")
        canvas.drawRightString(columns["stitches"], baseline, "Stitches")
        canvas.drawRightString(columns["skeins"], baseline, "Skeins")
        canvas.setLineWidth(_THIN_LINE)
        canvas.setStrokeGray(0)
        canvas.line(_MARGIN, top - _KEY_ROW, columns["skeins"], top - _KEY_ROW)
        return top - _KEY_ROW

    def _draw_key_row(
        self, columns: dict[str, float], baseline: float, entry: KeyEntry, symbol: str
    ) -> None:
        canvas = self.canvas
        if self.colour:
            canvas.setFillColorRGB(*_rgb_fraction(entry.thread.rgb))
            canvas.setStrokeGray(0.5)
            canvas.rect(columns["swatch"], baseline - 0.5 * mm, 6 * mm, 3 * mm, stroke=1, fill=1)
        # One text object per row, so the row reads (and copies) as one line.
        stitches, skeins = str(entry.stitches), str(entry.skeins)
        text = canvas.beginText()
        text.setFont(_FONT, _KEY_TEXT_SIZE)
        text.setFillGray(0)
        for x, value in (
            (columns["symbol"] + 5 * mm - _key_text_width(symbol) / 2, symbol),
            (columns["code"], entry.thread.code),
            (columns["name"], entry.thread.name),
            (columns["stitches"] - _key_text_width(stitches), stitches),
            (columns["skeins"] - _key_text_width(skeins), skeins),
        ):
            text.setTextOrigin(x, baseline)
            text.textOut(value)
        canvas.drawText(text)

    # --- chart --------------------------------------------------------------------------

    def draw_chart(self, capacity: tuple[int, int]) -> None:
        columns, rows = capacity
        row_bands = list(_bands(self.pattern.height, rows))
        column_bands = list(_bands(self.pattern.width, columns))
        pages = len(row_bands) * len(column_bands)
        width, height = self.page_size
        for number, (row_band, column_band) in enumerate(
            ((r, c) for r in row_bands for c in column_bands), start=1
        ):
            _ChartPage(self, column_band, row_band).draw()
            self.canvas.setFillGray(0)
            self.canvas.setFont(_FONT, _INFO_SIZE)
            self.canvas.drawRightString(
                width - _MARGIN, height - _MARGIN - _INFO_SIZE, f"Chart page {number} of {pages}"
            )
            self.canvas.showPage()


@dataclass(frozen=True)
class _ChartPage:
    """One chart page: the cells of `columns` x `rows`, drawn from the top-left corner."""

    document: _Document
    columns: _Band
    rows: _Band

    @property
    def left(self) -> float:
        return _MARGIN + _GUTTER

    @property
    def top(self) -> float:
        return self.document.page_size[1] - _MARGIN - _HEADER - _GUTTER

    def x(self, column: float) -> float:
        """Page x of the left edge of `column` (pattern coordinates)."""
        return self.left + (column - self.columns.start) * _CELL

    def y(self, row: float) -> float:
        """Page y of the top edge of `row` (pattern coordinates)."""
        return self.top - (row - self.rows.start) * _CELL

    def cells(self) -> npt.NDArray[np.intp]:
        grid = self.document.pattern.grid
        return grid[self.rows.start : self.rows.end, self.columns.start : self.columns.end]

    def draw(self) -> None:
        canvas = self.document.canvas
        canvas.setFillGray(0)
        canvas.setFont(_FONT, _INFO_SIZE)
        canvas.drawString(
            _MARGIN,
            self.document.page_size[1] - _MARGIN - _INFO_SIZE,
            f"Columns {self.columns.start + 1}-{self.columns.end}, "
            f"rows {self.rows.start + 1}-{self.rows.end}",
        )
        self._draw_overlap()
        if self.document.colour:
            self._draw_fills()
        self._draw_grid_lines()
        self._draw_symbols()
        self._draw_numbers()
        self._draw_centre_arrows()

    def _draw_overlap(self) -> None:
        """Shade the cells repeated from the neighbouring page: over the cells in black and
        white, in the number gutter in colour (where the cells keep their thread colour)."""
        canvas, colour = self.document.canvas, self.document.colour
        canvas.setFillGray(_OVERLAP_GREY)
        if self.columns.repeated:
            span = self.columns.repeated * _CELL
            if colour:
                canvas.rect(self.left, self.top, span, _GUTTER, stroke=0, fill=1)
            else:
                height = self.rows.size * _CELL
                canvas.rect(self.left, self.top - height, span, height, stroke=0, fill=1)
        if self.rows.repeated:
            span = self.rows.repeated * _CELL
            if colour:
                canvas.rect(self.left - _GUTTER, self.top - span, _GUTTER, span, stroke=0, fill=1)
            else:
                width = self.columns.size * _CELL
                canvas.rect(self.left, self.top - span, width, span, stroke=0, fill=1)

    def _draw_fills(self) -> None:
        """Fill each stitched cell with its thread colour, one path per thread."""
        canvas, cells = self.document.canvas, self.cells()
        for index, entry in enumerate(self.document.pattern.key):
            positions = np.argwhere(cells == index).tolist()
            if not positions:
                continue
            canvas.setFillColorRGB(*_rgb_fraction(entry.thread.rgb))
            path = canvas.beginPath()
            for row, column in positions:
                path.rect(self.left + column * _CELL, self.top - (row + 1) * _CELL, _CELL, _CELL)
            canvas.drawPath(path, stroke=0, fill=1)

    def _draw_grid_lines(self) -> None:
        """Thin lines between cells; bold every 10 cells of the pattern and on its edges.

        A page edge inside the pattern follows the same rule, so it is bold only where a
        tenth line falls: a bold line always means a multiple of 10 or the pattern's edge.
        """
        canvas, pattern = self.document.canvas, self.document.pattern
        x0, x1 = self.x(self.columns.start), self.x(self.columns.end)
        y0, y1 = self.y(self.rows.start), self.y(self.rows.end)
        columns = range(self.columns.start, self.columns.end + 1)
        rows = range(self.rows.start, self.rows.end + 1)
        for bold in (False, True):
            canvas.setLineWidth(_BOLD_LINE if bold else _THIN_LINE)
            canvas.setStrokeGray(0 if bold else _THIN_GREY)
            lines = [
                (self.x(c), y0, self.x(c), y1)
                for c in columns
                if (c % 10 == 0 or c == pattern.width) == bold
            ]
            lines += [
                (x0, self.y(r), x1, self.y(r))
                for r in rows
                if (r % 10 == 0 or r == pattern.height) == bold
            ]
            canvas.lines(lines)

    def _draw_symbols(self) -> None:
        """Each stitched cell's symbol, centred, as text in the chart font."""
        document, cells = self.document, self.cells()
        text = document.canvas.beginText()
        text.setFont(_FONT, _SYMBOL_SIZE)
        rise = (_CELL - _SYMBOL_SIZE * 0.7) / 2
        for index, (entry, symbol) in enumerate(
            zip(document.pattern.key, document.symbols, strict=True)
        ):
            positions = np.argwhere(cells == index).tolist()
            if not positions:
                continue
            dark = document.colour and _luminance(entry.thread.rgb) < _DARK_FILL
            text.setFillGray(1 if dark else 0)
            half = pdfmetrics.stringWidth(symbol, _FONT, _SYMBOL_SIZE) / 2
            for row, column in positions:
                text.setTextOrigin(
                    self.left + (column + 0.5) * _CELL - half,
                    self.top - (row + 1) * _CELL + rise,
                )
                text.textOut(symbol)
        document.canvas.drawText(text)

    def _draw_numbers(self) -> None:
        """Column numbers above and row numbers left of every 10th line, in pattern terms."""
        canvas = self.document.canvas
        canvas.setFillGray(0)
        canvas.setFont(_FONT, _NUMBER_SIZE)
        for column in range(self.columns.start + 1, self.columns.end + 1):
            if column % 10 == 0:
                canvas.drawCentredString(self.x(column), self.top + 1.5 * mm, str(column))
        for row in range(self.rows.start + 1, self.rows.end + 1):
            if row % 10 == 0:
                canvas.drawRightString(self.left - 1 * mm, self.y(row) - 0.7 * mm, str(row))

    def _draw_centre_arrows(self) -> None:
        """Filled triangles in the bottom and right gutters, on the centre column and row."""
        pattern = self.document.pattern
        self.document.canvas.setFillGray(0)
        centre_column = pattern.width / 2
        if self.columns.start <= centre_column <= self.columns.end:
            tip_x, tip_y = self.x(centre_column), self.y(self.rows.end) - 1 * mm
            self._triangle(
                (tip_x, tip_y),
                (tip_x - _ARROW / 2, tip_y - _ARROW),
                (tip_x + _ARROW / 2, tip_y - _ARROW),
            )
        centre_row = pattern.height / 2
        if self.rows.start <= centre_row <= self.rows.end:
            tip_x, tip_y = self.x(self.columns.end) + 1 * mm, self.y(centre_row)
            self._triangle(
                (tip_x, tip_y),
                (tip_x + _ARROW, tip_y + _ARROW / 2),
                (tip_x + _ARROW, tip_y - _ARROW / 2),
            )

    def _triangle(
        self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
    ) -> None:
        canvas = self.document.canvas
        path = canvas.beginPath()
        path.moveTo(*a)
        path.lineTo(*b)
        path.lineTo(*c)
        path.close()
        canvas.drawPath(path, stroke=0, fill=1)
