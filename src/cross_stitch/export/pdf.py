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
the symbol is black or white, whichever reads better on it (`symbol_ink`); the
black-and-white variant uses grey levels only. Symbols come from `pattern_symbols`, numbers
only from the `Pattern`. The same pattern and settings always give the same bytes.
"""

import io
import math
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from typing import Literal, TypedDict, Unpack, get_args

import numpy as np
import numpy.typing as npt
from PIL import Image
from reportlab.lib.pagesizes import A2, A3, A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from cross_stitch.export.geometry import (
    CELL_MM,
    FONT_PATH,
    MAX_CELL_MM,
    MIN_CELL_MM,
    SYMBOL_CENTRING,
    SYMBOL_SIZE_PT,
)
from cross_stitch.export.symbols import pattern_symbols
from cross_stitch.pattern import EMPTY, KeyEntry, Pattern

Variant = Literal["colour", "bw"]
Paper = Literal["A2", "A3", "A4", "A5"]
Orientation = Literal["portrait", "landscape"]
Split = Literal["cells", "pages"]
VARIANTS: tuple[Variant, ...] = get_args(Variant)
PAPERS: tuple[Paper, ...] = get_args(Paper)
ORIENTATIONS: tuple[Orientation, ...] = get_args(Orientation)
SPLITS: tuple[Split, ...] = get_args(Split)

_FONT = "DejaVuSans"

FABRIC_WHITE = (255, 255, 255)
"""The fabric colour a chart assumes unless told otherwise."""

OVERLAP = 2
"""Columns (or rows) a chart page repeats from its left (or upper) neighbour, by default."""
MAX_OVERLAP = 5
"""The most columns (or rows) a chart page may repeat from its neighbour."""
MAX_PAGES = 20
"""The most pages across (or down) a chart split by pages may take."""

_PORTRAIT_SIZES: dict[Paper, tuple[float, float]] = {"A2": A2, "A3": A3, "A4": A4, "A5": A5}
_CELL = CELL_MM * mm
_MARGIN = 10 * mm
_HEADER = 8 * mm  # the label line above the grid
_GUTTER = 5 * mm  # numbers on the top and left, centre arrows on the bottom and right

_SYMBOL_SIZE = SYMBOL_SIZE_PT
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
    area_width, area_height = _chart_area(_page_size(paper, orientation))
    columns = math.floor(round(area_width / _CELL, 6))
    rows = math.floor(round(area_height / _CELL, 6))
    return columns, rows


def _chart_area(page_size: tuple[float, float]) -> tuple[float, float]:
    """Width and height, in points, a chart page of this size gives its cells."""
    width, height = page_size
    return width - 2 * _MARGIN - 2 * _GUTTER, height - 2 * _MARGIN - _HEADER - 2 * _GUTTER


@dataclass(frozen=True)
class Band:
    """A run of columns (or rows) on one chart page."""

    start: int
    """First cell, 0-based."""
    end: int
    """One past the last cell."""
    repeated: int
    """Leading cells repeated from the previous band."""

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class ChartLayout:
    """How a chart is cut into pages: the cell side, the column and row bands, and the sheet
    they are printed on."""

    cell_mm: float
    columns: tuple[Band, ...]
    rows: tuple[Band, ...]
    page_size: tuple[float, float]
    """Width and height of the sheet in points, as oriented."""


class LayoutSettings(TypedDict, total=False):
    """The keyword arguments of `chart_layout` after the pattern's size, which `render_pdf`
    takes and passes on as they are."""

    paper: Paper
    orientation: Orientation
    split: Split
    pages_across: int
    pages_down: int
    overlap: int


def chart_layout(  # pylint: disable=too-many-arguments
    width: int,
    height: int,
    *,
    paper: Paper = "A4",
    orientation: Orientation = "portrait",
    split: Split = "cells",
    pages_across: int = 2,
    pages_down: int = 2,
    overlap: int = OVERLAP,
) -> ChartLayout:
    """Cut a `width` x `height` pattern into chart pages.

    - `"cells"`: a `CELL_MM` cell on every paper; as many pages as the pattern needs
      (`chart_capacity` cells each); `pages_across` and `pages_down` play no part.
    - `"pages"`: exactly `pages_across` x `pages_down` pages, bands as equal as possible
      (sizes differ by at most one, earlier bands take the extra cell), and the largest
      cell that fits the biggest band, floored to 0.1 mm, at most `MAX_CELL_MM`.

    Neighbouring pages share `overlap` columns or rows (0 to `MAX_OVERLAP`). Raises
    `ValueError` for an unknown split, an overlap or page count out of range, or a pages
    split that needs a cell under `MIN_CELL_MM` (the message names the fewest pages that
    would do).
    """
    page_size = _page_size(paper, orientation)
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
    if not 0 <= overlap <= MAX_OVERLAP:
        raise ValueError(f"overlap must be 0-{MAX_OVERLAP}, got {overlap}")
    if split == "cells":
        columns, rows = chart_capacity(paper, orientation)
        return ChartLayout(
            CELL_MM,
            tuple(_bands(width, columns, overlap)),
            tuple(_bands(height, rows, overlap)),
            page_size,
        )
    for name, pages in (("pages_across", pages_across), ("pages_down", pages_down)):
        if not 1 <= pages <= MAX_PAGES:
            raise ValueError(f"{name} must be 1-{MAX_PAGES}, got {pages}")
    return _pages_layout((width, height), (pages_across, pages_down), overlap, page_size)


def _pages_layout(
    size: tuple[int, int], pages: tuple[int, int], overlap: int, page_size: tuple[float, float]
) -> ChartLayout:
    """The `"pages"` split of `chart_layout`, its arguments checked."""
    width, height = size
    pages_across, pages_down = pages
    area_width, area_height = _chart_area(page_size)
    cell_mm = min(
        _fitting_cell_mm(width, pages_across, overlap, area_width),
        _fitting_cell_mm(height, pages_down, overlap, area_height),
        MAX_CELL_MM,
    )
    narrow = width < pages_across + overlap or height < pages_down + overlap
    if narrow or cell_mm < MIN_CELL_MM:
        across = _fewest_pages(width, overlap, area_width)
        down = _fewest_pages(height, overlap, area_height)
        raise ValueError(
            f"{pages_across} x {pages_down} pages would need cells under {MIN_CELL_MM:.1f} mm "
            f"or pages narrower than the overlap; this pattern needs at least {across} pages "
            f"across and {down} down at {MIN_CELL_MM:.1f} mm"
        )
    return ChartLayout(
        cell_mm,
        tuple(_equal_bands(width, pages_across, overlap)),
        tuple(_equal_bands(height, pages_down, overlap)),
        page_size,
    )


def _equal_sizes(length: int, count: int, overlap: int) -> list[int]:
    """Band sizes covering `length` cells in `count` bands that share `overlap` cells."""
    total = length + (count - 1) * overlap
    base, extra = divmod(total, count)
    return [base + 1 if k < extra else base for k in range(count)]


def _equal_bands(length: int, count: int, overlap: int) -> Iterator[Band]:
    start = 0
    for k, size in enumerate(_equal_sizes(length, count, overlap)):
        yield Band(start, start + size, overlap if k else 0)
        start += size - overlap


def _fitting_cell_mm(length: int, count: int, overlap: int, area: float) -> float:
    """The largest cell, floored to 0.1 mm, at which the biggest band fits `area`."""
    biggest = max(_equal_sizes(length, count, overlap))
    return math.floor(round(area / mm / biggest * 10, 6)) / 10


def _fewest_pages(length: int, overlap: int, area: float) -> int:
    """The fewest bands at which a cell of `MIN_CELL_MM` fits."""
    for count in range(1, length + 1):
        if length >= count + overlap and _fitting_cell_mm(length, count, overlap, area) >= (
            MIN_CELL_MM
        ):
            return count
    return length


# The layout settings are keyword-only and mirror the route's form fields one for one.
def render_pdf(
    pattern: Pattern,
    *,
    variant: Variant = "colour",
    centre_lines: bool = False,
    fabric_rgb: tuple[int, int, int] = FABRIC_WHITE,
    **settings: Unpack[LayoutSettings],
) -> bytes:
    """The pattern as a PDF chart: cover page(s), then the chart pages.

    The layout `settings` are those of `chart_layout`, with its defaults; `centre_lines`
    draws the centre column and row through the chart (red in colour, dashed black in
    black and white). The cover and section plan thumbnails show bare fabric in
    `fabric_rgb` (its grey in black and white); chart pages leave it unprinted.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    layout = chart_layout(pattern.width, pattern.height, **settings)
    page_size = layout.page_size
    _register_font()
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=page_size, invariant=True, pageCompression=True)
    canvas.setTitle("Cross-stitch chart")
    document = _Document(
        canvas, pattern, pattern_symbols(pattern), variant == "colour", page_size, fabric_rgb
    )
    document.draw_cover(layout.cell_mm)
    document.draw_chart(layout, centre_lines=centre_lines)
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


SymbolInk = Literal["black", "white"]


def symbol_ink(rgb: tuple[int, int, int]) -> SymbolInk:
    """The ink a symbol takes on a cell of this colour in the colour chart.

    White on a colour whose Rec. 601 luminance is below 140, black otherwise. The colour
    PDF and the JSON response both read it here, so the page draws every symbol in the ink
    the printed chart uses.
    """
    return "white" if _luminance(rgb) < _DARK_FILL else "black"


def _key_text_width(value: str) -> float:
    return float(pdfmetrics.stringWidth(value, _FONT, _KEY_TEXT_SIZE))


def _rgb_fraction(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb
    return r / 255, g / 255, b / 255


def _bands(length: int, capacity: int, overlap: int) -> Iterator[Band]:
    """Split `length` cells into bands of at most `capacity`, neighbours sharing `overlap`."""
    step = capacity - overlap
    count = 1 if length <= capacity else 1 + math.ceil((length - capacity) / step)
    for k in range(count):
        start = k * step
        yield Band(start, min(start + capacity, length), overlap if k else 0)


@dataclass(frozen=True)
class _Document:
    canvas: Canvas
    pattern: Pattern
    symbols: list[str]
    colour: bool
    page_size: tuple[float, float]
    fabric_rgb: tuple[int, int, int]

    # --- cover --------------------------------------------------------------------------

    def draw_cover(self, cell_mm: float) -> None:
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
            f"Chart cell: {cell_mm:.1f} mm",
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
        """One pixel per cell: the thread colour (its grey in black and white), bare fabric
        in the fabric's colour."""
        pattern = self.pattern
        palette = np.array(
            [entry.thread.rgb for entry in pattern.key] + [self.fabric_rgb], dtype=np.float64
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

    def draw_chart(self, layout: ChartLayout, *, centre_lines: bool) -> None:
        row_bands, column_bands = layout.rows, layout.columns
        pages = len(row_bands) * len(column_bands)
        cell = _CELL if layout.cell_mm == CELL_MM else layout.cell_mm * mm
        if pages > 1:
            self._draw_section_plan(layout)
        width, height = self.page_size
        for number, ((row, row_band), (column, column_band)) in enumerate(
            ((r, c) for r in enumerate(row_bands) for c in enumerate(column_bands)), start=1
        ):
            name = section_name(column, row)
            _ChartPage(self, column_band, row_band, cell, centre_lines, name).draw()
            self.canvas.setFillGray(0)
            self.canvas.setFont(_FONT, _INFO_SIZE)
            self.canvas.drawRightString(
                width - _MARGIN, height - _MARGIN - _INFO_SIZE, f"Chart page {number} of {pages}"
            )
            self.canvas.showPage()

    def _draw_section_plan(self, layout: ChartLayout) -> None:
        """A page with the whole pattern, each section outlined and named on it."""
        canvas, pattern = self.canvas, self.pattern
        width, height = self.page_size
        top = height - _MARGIN
        canvas.setFillGray(0)
        canvas.setFont(_FONT, _TITLE_SIZE)
        canvas.drawString(_MARGIN, top - _TITLE_SIZE, "Section plan")
        top -= _TITLE_SIZE + 6 * mm
        scale = min((width - 2 * _MARGIN) / pattern.width, (top - _MARGIN) / pattern.height)
        left, bottom = _MARGIN, top - pattern.height * scale
        canvas.drawImage(
            ImageReader(self._thumbnail()),
            left,
            bottom,
            width=pattern.width * scale,
            height=pattern.height * scale,
        )
        self._draw_plan_sections(layout, (left, top), scale)
        canvas.showPage()

    def _draw_plan_sections(
        self, layout: ChartLayout, origin: tuple[float, float], scale: float
    ) -> None:
        """Each section outlined over the plan's thumbnail and named inside its outline."""
        canvas = self.canvas
        left, top = origin
        canvas.setLineWidth(_BOLD_LINE)
        canvas.setStrokeGray(0)
        for row, row_band in enumerate(layout.rows):
            for column, column_band in enumerate(layout.columns):
                x0 = left + column_band.start * scale
                y1 = top - row_band.start * scale
                w, h = column_band.size * scale, row_band.size * scale
                canvas.rect(x0, y1 - h, w, h, stroke=1, fill=0)
                self._draw_plan_name(section_name(column, row), x0 + w / 2, y1 - h / 2)

    def _draw_plan_name(self, name: str, x: float, y: float) -> None:
        """A section's name on a white tab, so it reads over light and dark threads."""
        canvas = self.canvas
        size = _INFO_SIZE + 1
        half_width = pdfmetrics.stringWidth(name, _FONT, size) / 2 + 1.5 * mm
        half_height = size / 2 + 1 * mm
        canvas.setFillGray(1)
        canvas.setLineWidth(_THIN_LINE)
        canvas.rect(
            x - half_width, y - half_height, 2 * half_width, 2 * half_height, stroke=1, fill=1
        )
        canvas.setFillGray(0)
        canvas.setFont(_FONT, size)
        canvas.drawCentredString(x, y - size * 0.35, name)
        canvas.setLineWidth(_BOLD_LINE)


def section_name(column: int, row: int) -> str:
    """The name of the chart section in column band `column` and row band `row` (0-based):
    letters for the column (A, B, ... Z, AA, AB, ...), a number from 1 for the row."""
    letters = ""
    number = column + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row + 1}"


@dataclass(frozen=True)
class _ChartPage:
    """One chart page: the cells of `columns` x `rows`, drawn from the top-left corner."""

    document: _Document
    columns: Band
    rows: Band
    cell: float
    """The cell side, in points."""
    centre_lines: bool
    name: str
    """The section's name, as the section plan writes it."""

    @property
    def left(self) -> float:
        return _MARGIN + _GUTTER

    @property
    def top(self) -> float:
        return self.document.page_size[1] - _MARGIN - _HEADER - _GUTTER

    def x(self, column: float) -> float:
        """Page x of the left edge of `column` (pattern coordinates)."""
        return self.left + (column - self.columns.start) * self.cell

    def y(self, row: float) -> float:
        """Page y of the top edge of `row` (pattern coordinates)."""
        return self.top - (row - self.rows.start) * self.cell

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
            f"{self.name} - Columns {self.columns.start + 1}-{self.columns.end}, "
            f"rows {self.rows.start + 1}-{self.rows.end}",
        )
        self._draw_overlap()
        if self.document.colour:
            self._draw_fills()
        self._draw_grid_lines()
        self._draw_symbols()
        self._draw_numbers()
        if self.centre_lines:
            self._draw_centre_lines()
        self._draw_centre_arrows()

    def _draw_overlap(self) -> None:
        """Shade the cells repeated from the neighbouring page: over the cells in black and
        white, in the number gutter in colour (where the cells keep their thread colour)."""
        canvas, colour = self.document.canvas, self.document.colour
        canvas.setFillGray(_OVERLAP_GREY)
        if self.columns.repeated:
            span = self.columns.repeated * self.cell
            if colour:
                canvas.rect(self.left, self.top, span, _GUTTER, stroke=0, fill=1)
            else:
                height = self.rows.size * self.cell
                canvas.rect(self.left, self.top - height, span, height, stroke=0, fill=1)
        if self.rows.repeated:
            span = self.rows.repeated * self.cell
            if colour:
                canvas.rect(self.left - _GUTTER, self.top - span, _GUTTER, span, stroke=0, fill=1)
            else:
                width = self.columns.size * self.cell
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
                path.rect(
                    self.left + column * self.cell,
                    self.top - (row + 1) * self.cell,
                    self.cell,
                    self.cell,
                )
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
        # Symbols scale with the cell; the default cell keeps the exact default size.
        size = _SYMBOL_SIZE if self.cell == _CELL else _SYMBOL_SIZE * self.cell / _CELL
        text.setFont(_FONT, size)
        rise = (self.cell - size * SYMBOL_CENTRING) / 2
        for index, (entry, symbol) in enumerate(
            zip(document.pattern.key, document.symbols, strict=True)
        ):
            positions = np.argwhere(cells == index).tolist()
            if not positions:
                continue
            dark = document.colour and symbol_ink(entry.thread.rgb) == "white"
            text.setFillGray(1 if dark else 0)
            half = pdfmetrics.stringWidth(symbol, _FONT, size) / 2
            for row, column in positions:
                text.setTextOrigin(
                    self.left + (column + 0.5) * self.cell - half,
                    self.top - (row + 1) * self.cell + rise,
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

    def _draw_centre_lines(self) -> None:
        """The centre column and row across the cells, on the page that holds them."""
        canvas, pattern = self.document.canvas, self.document.pattern
        x0, x1 = self.x(self.columns.start), self.x(self.columns.end)
        y0, y1 = self.y(self.rows.start), self.y(self.rows.end)
        lines = []
        centre_column = pattern.width / 2
        if self.columns.start <= centre_column <= self.columns.end:
            lines.append((self.x(centre_column), y0, self.x(centre_column), y1))
        centre_row = pattern.height / 2
        if self.rows.start <= centre_row <= self.rows.end:
            lines.append((x0, self.y(centre_row), x1, self.y(centre_row)))
        if not lines:
            return
        canvas.saveState()
        canvas.setLineWidth(_BOLD_LINE)
        if self.document.colour:
            canvas.setStrokeColorRGB(1, 0, 0)
        else:
            canvas.setStrokeGray(0)
            canvas.setDash(3, 2)
        canvas.lines(lines)
        canvas.restoreState()

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
