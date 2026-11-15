"""Patterns and PDF readers several chart test modules share."""

import io
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject

from cross_stitch.export import (
    ORIENTATIONS,
    PAPERS,
    SYMBOLS,
    Orientation,
    Paper,
    pattern_symbols,
)
from cross_stitch.pattern import EMPTY, KeyEntry, Pattern, build_pattern
from cross_stitch.threads import dmc_thread, dmc_threads

HUNDRED = 100
"""The most colours a pattern has, and so the size of the largest key."""

BLACK = dmc_thread("310")  # (0, 0, 0)
RED = dmc_thread("666")  # Bright Red (227, 29, 66)
BLUE = dmc_thread("797")  # Royal Blue (19, 71, 125)
GREEN = dmc_thread("700")  # Green Bright (7, 115, 27)
WHITE = dmc_thread("Blanc")  # White (252, 251, 248), not pure white

LAYOUTS: list[tuple[Paper, Orientation]] = [(p, o) for p in PAPERS for o in ORIENTATIONS]
LAYOUT_IDS = [f"{paper}-{orientation}" for paper, orientation in LAYOUTS]

# ISO 216 sheet sizes in PDF points (1/72 inch), portrait (width, height).
SHEET_POINTS: dict[str, tuple[float, float]] = {
    "A2": (1191, 1684),
    "A3": (842, 1191),
    "A4": (595, 842),
    "A5": (420, 595),
}

MULTIPLICATION_SIGN = "\U000000d7"  # a symbol, but also a natural way to write "w x h"
# Symbols no label, number or other text on a page can contain: they can be counted.
COUNTABLE = [s for s in SYMBOLS if ord(s) > 0x7F and s != MULTIPLICATION_SIGN]

LABEL = re.compile(r"Columns\s+(\d+)\s*-\s*(\d+),\s*rows\s+(\d+)\s*-\s*(\d+)")
NON_GREY_OPERATORS = {b"k", b"K", b"sc", b"scn", b"SC", b"SCN"}
COLOUR_TOLERANCE = 0.003

Label = tuple[int, int, int, int]
"""A chart page's (first column, last column, first row, last row), 1-based, inclusive."""


@dataclass(frozen=True)
class _Pdf:
    reader: PdfReader
    covers: list[str]  # extracted text of each cover page, in page order
    charts: list[str]  # extracted text of each chart page, in page order
    labels: list[Label]  # the label of each chart page, in page order


@dataclass(frozen=True)
class _Parts:
    operations: list[tuple[Any, bytes]]  # the page's and its form XObjects' operators
    images: list[DictionaryObject]  # image XObjects
    fonts: list[DictionaryObject]  # font dictionaries


def _read(data: bytes) -> _Pdf:
    """Parse a rendered PDF: cover pages first, then chart pages, each with one label."""
    reader = PdfReader(io.BytesIO(data))
    covers: list[str] = []
    charts: list[str] = []
    labels: list[Label] = []
    for number, page in enumerate(reader.pages):
        text = page.extract_text()
        found = LABEL.findall(text)
        if not found:
            assert not charts, f"page {number + 1} has no label but follows a chart page"
            covers.append(text)
            continue
        assert len(found) == 1, f"page {number + 1} has {len(found)} labels"
        first_column, last_column, first_row, last_row = (int(value) for value in found[0])
        charts.append(text)
        labels.append((first_column, last_column, first_row, last_row))
    assert covers, "the PDF has no cover page"
    return _Pdf(reader=reader, covers=covers, charts=charts, labels=labels)


def _chart_pages(pdf: _Pdf) -> list[PageObject]:
    return [pdf.reader.pages[i] for i in range(len(pdf.covers), len(pdf.reader.pages))]


def _dict(value: object) -> DictionaryObject:
    resolved = value.get_object() if hasattr(value, "get_object") else value
    assert isinstance(resolved, DictionaryObject), type(resolved)
    return resolved


def _parts(reader: PdfReader, page: PageObject) -> _Parts:
    """Every operator a page draws (its content and its form XObjects, nested), with the
    image XObjects and fonts its resources hold."""
    contents = page.get_contents()
    operations = [] if contents is None else list(ContentStream(contents, reader).operations)
    images: list[DictionaryObject] = []
    fonts: list[DictionaryObject] = []
    pending = [_dict(page["/Resources"])] if "/Resources" in page else []
    while pending:
        current = pending.pop()
        if "/Font" in current:
            font_table = _dict(current["/Font"])
            fonts.extend(_dict(font_table[name]) for name in font_table)
        if "/XObject" not in current:
            continue
        xobjects = _dict(current["/XObject"])
        for name in xobjects:
            xobject = _dict(xobjects[name])
            subtype = str(xobject["/Subtype"])
            if subtype == "/Image":
                images.append(xobject)
            elif subtype == "/Form":
                operations.extend(ContentStream(xobject, reader).operations)
                if "/Resources" in xobject:
                    pending.append(_dict(xobject["/Resources"]))
    return _Parts(operations=operations, images=images, fonts=fonts)


def _fills(pdf: _Pdf) -> list[tuple[float, ...]]:
    """The operands of every `rg` (non-stroking RGB colour) on the chart pages."""
    return [
        tuple(float(value) for value in operands)
        for page in _chart_pages(pdf)
        for operands, operator in _parts(pdf.reader, page).operations
        if operator == b"rg"
    ]


def _embedded(font: DictionaryObject) -> bool:
    """Whether a font dictionary (simple or Type 0) carries its font file."""
    if "/DescendantFonts" in font:
        descendants = font["/DescendantFonts"]
        assert isinstance(descendants, ArrayObject)
        font = _dict(descendants[0])
    if "/FontDescriptor" not in font:
        return False
    descriptor = _dict(font["/FontDescriptor"])
    return any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))


def _numbers(text: str) -> set[int]:
    return {int(digits) for digits in re.findall(r"\d+", text)}


def _word(token: str) -> re.Pattern[str]:
    """`token` standing alone: not inside a longer run of letters or digits."""
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(token)}(?![0-9A-Za-z])")


def _number(fragment: str) -> re.Pattern[str]:
    """The number `fragment` (a regex) standing alone: no digit or decimal point around it."""
    return re.compile(rf"(?<![\d.]){fragment}(?!\.?\d)")


def _is_key_row(line: str, entry: KeyEntry) -> bool:
    return (
        entry.thread.name in line
        and _word(entry.thread.code).search(line) is not None
        and _word(str(entry.stitches)).search(line) is not None
        and _word(str(entry.skeins)).search(line) is not None
    )


def _in_window(pattern: Pattern, label: Label, index: int) -> int:
    """How many cells of key entry `index` lie inside a chart page's stated range."""
    first_column, last_column, first_row, last_row = label
    window = pattern.grid[first_row - 1 : last_row, first_column - 1 : last_column]
    return int(np.count_nonzero(window == index))


def _cells(rows: list[list[int]] | npt.NDArray[np.intp]) -> npt.NDArray[np.intp]:
    return np.asarray(rows, dtype=np.intp)


def _two_colour(width: int, height: int, split: int) -> Pattern:
    """Columns left of `split` in black, the rest in red; `split` > width / 2, so black is
    entry 0 and red entry 1."""
    assert split > width - split
    row = np.where(np.arange(width) < split, 0, 1)
    return build_pattern(_cells(np.tile(row, (height, 1))), [BLACK, RED], 14.0)


def _corners(width: int, height: int) -> Pattern:
    """Bare fabric except the four corner cells, in black: cheap to render at any size."""
    cells = np.full((height, width), EMPTY, dtype=np.intp)
    cells[[0, 0, -1, -1], [0, -1, 0, -1]] = 0
    return build_pattern(cells, [BLACK], 14.0)


def _speckled(width: int, height: int) -> Pattern:
    """About 20% black (entry 0) and 10% red (entry 1) cells at seeded random places, the
    rest bare: an irregular layout, so a page that shows a shifted range miscounts."""
    draw = np.random.default_rng(7).random((height, width))
    cells = np.full((height, width), EMPTY, dtype=np.intp)
    cells[draw < 0.2] = 0
    cells[(draw >= 0.2) & (draw < 0.3)] = 1
    pattern = build_pattern(cells, [BLACK, RED], 14.0)
    assert [entry.thread for entry in pattern.key] == [BLACK, RED]
    return pattern


def _five_colours() -> Pattern:
    """12 x 8: red 36, blue 24, green 12, black 8, white 4 stitches, 12 bare cells."""
    bare = EMPTY
    rows = [
        *[[0] * 12] * 3,
        *[[1] * 12] * 2,
        [2] * 12,
        [3] * 8 + [bare] * 4,
        [4] * 4 + [bare] * 8,
    ]
    pattern = build_pattern(_cells(rows), [RED, BLUE, GREEN, BLACK, WHITE], 14.0)
    assert [entry.thread for entry in pattern.key] == [RED, BLUE, GREEN, BLACK, WHITE]
    return pattern


def _hundred_threads() -> Pattern:
    """101 x 50, the first 100 DMC threads: thread i fills 100 - i cells (5050 in all), so
    the key is those threads in source order."""
    threads = dmc_threads()[:HUNDRED]
    counts = [HUNDRED - i for i in range(HUNDRED)]
    cells = np.repeat(np.arange(HUNDRED, dtype=np.intp), counts).reshape(50, 101)
    pattern = build_pattern(cells, threads, 14.0)
    assert [entry.thread for entry in pattern.key] == list(threads)
    return pattern


def _countable_symbols(pattern: Pattern) -> list[str]:
    """The pattern's symbols, in key order, each checked to be countable in page text (an
    assigned symbol can be a letter or digit, which labels and numbers contain too)."""
    symbols = pattern_symbols(pattern)
    for symbol in symbols:
        assert symbol in COUNTABLE, f"U+{ord(symbol):04X} cannot be counted in page text"
    return symbols
