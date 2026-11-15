"""Chart export: the symbol list (one symbol per key entry, by position) and the PDF chart.

The PDF tests read the document back with pypdf. A chart page is told from a cover page by
its label "Columns a-b, rows c-d"; on a chart page every stitched cell is its symbol drawn
as text, so counting a symbol in the page's extracted text counts its cells.
"""

import functools
import io
import re
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pdf_helpers import (
    BLACK,
    COLOUR_TOLERANCE,
    COUNTABLE,
    LAYOUT_IDS,
    LAYOUTS,
    NON_GREY_OPERATORS,
    RED,
    SHEET_POINTS,
    _cells,
    _chart_pages,
    _corners,
    _countable_symbols,
    _embedded,
    _fills,
    _five_colours,
    _hundred_threads,
    _in_window,
    _is_key_row,
    _number,
    _numbers,
    _parts,
    _read,
    _speckled,
    _two_colour,
    _word,
)
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfbase.ttfonts import TTFontFile

from cross_stitch.export import (
    FONT_PATH,
    ORIENTATIONS,
    OVERLAP,
    PAPERS,
    SYMBOLS,
    VARIANTS,
    Orientation,
    Paper,
    Variant,
    chart_capacity,
    pattern_symbols,
    render_pdf,
    symbol_ink,
)
from cross_stitch.pattern import EMPTY, build_pattern, convert_image
from cross_stitch.threads import dmc_threads

LIMIT = 100

# Look-alike groups, written with code point escapes so each member is unambiguous. At most
# one member of a group may be in SYMBOLS: two of them are hard to tell apart on paper.
LOOK_ALIKES: list[tuple[str, ...]] = [
    ("O", "0", "o", "\U000025cb"),
    ("I", "l", "1", "|", "i"),
    ("S", "5", "s"),
    ("Z", "2", "z"),
    ("B", "8"),
    ("C", "c"),
    ("X", "x", "\U000000d7", "\U00002715"),
    ("V", "v"),
    ("W", "w"),
    ("P", "p"),
    ("U", "u"),
    ("K", "k"),
    ("Y", "y"),
    ("-", "\U00002013", "\U00002212"),
    ("'", "`", "\U000000b4"),
    ('"', "\U00002033"),
    ("\U000000b7", ".", "\U00002219", "\U000022c5"),
    ("\U000000b0", "\U000000ba", "\U000002da"),
    ("\U000000a6", "|"),
    ("\U000000ac", "\U00002310"),
    ("\U000025a0", "\U000025aa"),
    ("\U000025a1", "\U000025ab"),
    ("\U000025cf", "\U000026ab"),
    ("\U000025c6", "\U00002666"),
    (",", "\U000000b8"),
    (";", "\U0000037e"),
    (":", "\U00002236"),
    ("~", "\U0000223c"),
    ("^", "\U000002c6"),
    ("\U000000af", "\U0000203e"),
    ("*", "\U00002217"),
    ("/", "\U00002215"),
    ("\\", "\U00002216"),
    ("<", "\U00002039"),
    (">", "\U0000203a"),
    ("C", "G"),
    ("G", "6"),
    ("E", "\U000000c6"),
    ("\U00002234", "\U00002235"),
    ("\U000025cb", "\U00002299", "\U000000a9"),
    ("S", "\U000000a7", "$"),
    ("\U000000a3", "f"),
    ("\U000025a0", "\U000025a3"),
    ("Y", "\U000000a5"),
    ("\U00002205", "\U000000d8"),
]

# Blocks the chart font (DejaVu Sans) is relied on for, as inclusive code point ranges.
ALLOWED_RANGES = [
    (0x0021, 0x007E),  # Basic Latin, printable, no space
    (0x00A1, 0x00FF),  # Latin-1 Supplement, from the inverted exclamation mark
    (0x2190, 0x21FF),  # Arrows
    (0x2200, 0x22FF),  # Mathematical Operators
    (0x25A0, 0x25FF),  # Geometric Shapes
]
EXCLUDED = {0x00A0, 0x00AD}  # no-break space, soft hyphen


def _label(group: tuple[str, ...]) -> str:
    return " ".join(f"U+{ord(c):04X}" for c in group)


def test_the_list_has_exactly_100_symbols() -> None:
    assert len(SYMBOLS) == LIMIT


def test_the_list_has_no_duplicates() -> None:
    assert len(set(SYMBOLS)) == len(SYMBOLS)


@pytest.mark.parametrize("index", range(LIMIT))
def test_every_symbol_is_one_visible_character(index: int) -> None:
    symbol = SYMBOLS[index]
    assert isinstance(symbol, str)
    assert len(symbol) == 1
    assert not symbol.isspace()
    assert symbol.isprintable()


@pytest.mark.parametrize("group", LOOK_ALIKES, ids=_label)
def test_at_most_one_member_of_a_look_alike_group_is_in_the_list(group: tuple[str, ...]) -> None:
    present = [c for c in group if c in SYMBOLS]
    assert len(present) <= 1, f"look-alikes together in SYMBOLS: {present}"


@pytest.mark.parametrize("index", range(LIMIT))
def test_every_symbol_is_in_a_block_the_font_covers(index: int) -> None:
    code_point = ord(SYMBOLS[index])
    assert code_point not in EXCLUDED
    assert any(low <= code_point <= high for low, high in ALLOWED_RANGES), hex(code_point)


# --- PDF chart ---------------------------------------------------------------------------


@functools.cache
def _font_glyphs() -> dict[int, int]:
    glyphs: dict[int, int] = TTFontFile(str(FONT_PATH)).charToGlyph
    return glyphs


# Font


def test_the_font_ships_inside_the_export_package() -> None:
    bundled = resources.files("cross_stitch.export").joinpath("DejaVuSans.ttf")
    assert FONT_PATH.is_file()
    assert FONT_PATH.resolve() == Path(str(bundled)).resolve()


@pytest.mark.parametrize("index", range(LIMIT))
def test_every_symbol_has_a_glyph_in_the_bundled_font(index: int) -> None:
    symbol = SYMBOLS[index]
    assert ord(symbol) in _font_glyphs(), f"U+{ord(symbol):04X} has no glyph"


def test_chart_pages_embed_the_bundled_font() -> None:
    pdf = _read(render_pdf(_two_colour(10, 10, 6)))
    fonts = _parts(pdf.reader, _chart_pages(pdf)[0]).fonts
    embedded = [str(font["/BaseFont"]) for font in fonts if _embedded(font)]
    assert any("DejaVuSans" in name for name in embedded), embedded


# Layouts and capacities


def test_the_choices_are_the_agreed_ones() -> None:
    assert VARIANTS == ("colour", "bw")
    assert PAPERS == ("A2", "A3", "A4", "A5")
    assert ORIENTATIONS == ("portrait", "landscape")
    assert len(LAYOUTS) == 8


def test_neighbouring_pages_share_two_rows_or_columns() -> None:
    assert OVERLAP == 2


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_a_page_holds_more_than_the_overlap(paper: Paper, orientation: Orientation) -> None:
    columns, rows = chart_capacity(paper, orientation)
    assert columns > OVERLAP
    assert rows > OVERLAP


@pytest.mark.parametrize("orientation", ORIENTATIONS)
@pytest.mark.parametrize(("bigger", "smaller"), [("A2", "A3"), ("A3", "A4"), ("A4", "A5")])
def test_capacity_grows_with_the_sheet(
    bigger: Paper, smaller: Paper, orientation: Orientation
) -> None:
    big_columns, big_rows = chart_capacity(bigger, orientation)
    small_columns, small_rows = chart_capacity(smaller, orientation)
    assert big_columns >= small_columns
    assert big_rows >= small_rows
    assert big_columns * big_rows > small_columns * small_rows


# An A(n) sheet's short side is the long side of A(n+1): with one cell side and the same
# margins and gutters on every layout, the same sheet width holds the same columns, and the
# same sheet height the same rows.
@pytest.mark.parametrize(
    ("paper", "orientation", "other_paper", "other_orientation"),
    [
        ("A2", "portrait", "A3", "landscape"),
        ("A3", "portrait", "A4", "landscape"),
        ("A4", "portrait", "A5", "landscape"),
    ],
)
def test_the_same_sheet_width_holds_the_same_columns(
    paper: Paper, orientation: Orientation, other_paper: Paper, other_orientation: Orientation
) -> None:
    columns, _ = chart_capacity(paper, orientation)
    other_columns, _ = chart_capacity(other_paper, other_orientation)
    assert columns == other_columns


@pytest.mark.parametrize(
    ("paper", "orientation", "other_paper", "other_orientation"),
    [
        ("A2", "landscape", "A3", "portrait"),
        ("A3", "landscape", "A4", "portrait"),
        ("A4", "landscape", "A5", "portrait"),
    ],
)
def test_the_same_sheet_height_holds_the_same_rows(
    paper: Paper, orientation: Orientation, other_paper: Paper, other_orientation: Orientation
) -> None:
    _, rows = chart_capacity(paper, orientation)
    _, other_rows = chart_capacity(other_paper, other_orientation)
    assert rows == other_rows


# Page size


def test_no_layout_given_is_a4_portrait() -> None:
    reader = PdfReader(io.BytesIO(render_pdf(_corners(150, 150))))
    assert len(reader.pages) > 2
    for page in reader.pages:
        assert page.mediabox.width == pytest.approx(595, abs=1)
        assert page.mediabox.height == pytest.approx(842, abs=1)
        assert page.rotation == 0


def test_the_defaults_are_colour_a4_portrait() -> None:
    pattern = _two_colour(10, 10, 6)
    explicit = render_pdf(pattern, variant="colour", paper="A4", orientation="portrait")
    assert render_pdf(pattern) == explicit


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_every_page_has_the_sheet_size_asked_for(paper: Paper, orientation: Orientation) -> None:
    columns, rows = chart_capacity(paper, orientation)
    data = render_pdf(_corners(columns + 1, rows + 1), paper=paper, orientation=orientation)
    width, height = SHEET_POINTS[paper]
    if orientation == "landscape":
        width, height = height, width
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 5
    for page in reader.pages:
        assert page.mediabox.width == pytest.approx(width, abs=1)
        assert page.mediabox.height == pytest.approx(height, abs=1)
        assert page.rotation == 0


# Page splitting


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_a_10x10_pattern_is_one_cover_and_one_chart_page(
    paper: Paper, orientation: Orientation
) -> None:
    pdf = _read(render_pdf(_two_colour(10, 10, 6), paper=paper, orientation=orientation))
    assert len(pdf.reader.pages) == 2
    assert len(pdf.covers) == 1
    assert pdf.labels == [(1, 10, 1, 10)]


def test_a_1x1_pattern_is_one_chart_page() -> None:
    pattern = build_pattern(_cells([[0]]), [BLACK], 14.0)
    pdf = _read(render_pdf(pattern))
    assert pdf.labels == [(1, 1, 1, 1)]
    [symbol] = _countable_symbols(pattern)
    assert pdf.charts[0].count(symbol) == 1


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_a_pattern_of_exactly_one_page_capacity_is_one_chart_page(
    paper: Paper, orientation: Orientation
) -> None:
    columns, rows = chart_capacity(paper, orientation)
    pattern = _corners(columns, rows)
    pdf = _read(render_pdf(pattern, paper=paper, orientation=orientation))
    assert pdf.labels == [(1, columns, 1, rows)]
    [symbol] = _countable_symbols(pattern)
    assert pdf.charts[0].count(symbol) == 4


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_one_column_too_many_gives_two_chart_pages(paper: Paper, orientation: Orientation) -> None:
    columns, _ = chart_capacity(paper, orientation)
    pdf = _read(render_pdf(_corners(columns + 1, 3), paper=paper, orientation=orientation))
    assert len(pdf.charts) == 2


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_the_second_page_repeats_the_overlap_columns(
    paper: Paper, orientation: Orientation
) -> None:
    columns, _ = chart_capacity(paper, orientation)
    pdf = _read(render_pdf(_corners(columns + 1, 3), paper=paper, orientation=orientation))
    assert pdf.labels == [(1, columns, 1, 3), (columns - OVERLAP + 1, columns + 1, 1, 3)]


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_one_row_too_many_gives_two_pages_repeating_the_overlap_rows(
    paper: Paper, orientation: Orientation
) -> None:
    _, rows = chart_capacity(paper, orientation)
    pdf = _read(render_pdf(_corners(3, rows + 1), paper=paper, orientation=orientation))
    assert pdf.labels == [(1, 3, 1, rows), (1, 3, rows - OVERLAP + 1, rows + 1)]


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_one_column_and_one_row_too_many_give_four_chart_pages(
    paper: Paper, orientation: Orientation
) -> None:
    columns, rows = chart_capacity(paper, orientation)
    data = render_pdf(_corners(columns + 1, rows + 1), paper=paper, orientation=orientation)
    assert len(_read(data).charts) == 4


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_two_full_bands_of_columns_give_exactly_two_pages(
    paper: Paper, orientation: Orientation
) -> None:
    columns, _ = chart_capacity(paper, orientation)
    width = 2 * columns - OVERLAP
    pdf = _read(render_pdf(_corners(width, 3), paper=paper, orientation=orientation))
    assert pdf.labels == [(1, columns, 1, 3), (columns - OVERLAP + 1, width, 1, 3)]


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_a_third_band_starts_two_strides_in(paper: Paper, orientation: Orientation) -> None:
    columns, _ = chart_capacity(paper, orientation)
    stride = columns - OVERLAP
    width = 2 * columns - OVERLAP + 1
    pdf = _read(render_pdf(_corners(width, 3), paper=paper, orientation=orientation))
    assert pdf.labels == [
        (1, columns, 1, 3),
        (stride + 1, stride + columns, 1, 3),
        (2 * stride + 1, width, 1, 3),
    ]


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_chart_pages_cover_every_cell_in_reading_order_with_its_own_symbol(
    paper: Paper, orientation: Orientation
) -> None:
    columns, rows = chart_capacity(paper, orientation)
    pattern = _speckled(columns + 1, rows + 1)
    pdf = _read(render_pdf(pattern, paper=paper, orientation=orientation))
    first_column, first_row = columns - OVERLAP + 1, rows - OVERLAP + 1
    assert pdf.labels == [
        (1, columns, 1, rows),
        (first_column, columns + 1, 1, rows),
        (1, columns, first_row, rows + 1),
        (first_column, columns + 1, first_row, rows + 1),
    ]
    first, second = _countable_symbols(pattern)
    for text, label in zip(pdf.charts, pdf.labels, strict=True):
        assert text.count(first) == _in_window(pattern, label, 0), label
        assert text.count(second) == _in_window(pattern, label, 1), label


def test_a_bigger_sheet_needs_fewer_chart_pages() -> None:
    pattern = _corners(300, 300)
    on_a5 = _read(render_pdf(pattern, paper="A5", orientation="portrait"))
    on_a3 = _read(render_pdf(pattern, paper="A3", orientation="portrait"))
    assert len(on_a3.charts) < len(on_a5.charts)


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_column_numbers_on_a_later_page_count_from_the_pattern_edge(
    paper: Paper, orientation: Orientation
) -> None:
    columns, _ = chart_capacity(paper, orientation)
    width = 2 * columns - OVERLAP
    pdf = _read(render_pdf(_corners(width, 5), paper=paper, orientation=orientation))
    first, last = pdf.labels[1][0], pdf.labels[1][1]
    numbers = _numbers(pdf.charts[1])
    assert {n for n in range(10, last + 1, 10) if n >= first} <= numbers
    assert not set(range(10, first, 10)) & numbers, "numbers counted from the page edge"


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_row_numbers_on_a_later_page_count_from_the_pattern_edge(
    paper: Paper, orientation: Orientation
) -> None:
    _, rows = chart_capacity(paper, orientation)
    height = 2 * rows - OVERLAP
    pdf = _read(render_pdf(_corners(5, height), paper=paper, orientation=orientation))
    first, last = pdf.labels[1][2], pdf.labels[1][3]
    numbers = _numbers(pdf.charts[1])
    assert {n for n in range(10, last + 1, 10) if n >= first} <= numbers
    assert not set(range(10, first, 10)) & numbers, "numbers counted from the page edge"


# Choices refused


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("variant", "sepia"),
        ("variant", "grey"),
        ("paper", "A6"),
        ("paper", "Letter"),
        ("orientation", "diagonal"),
    ],
)
def test_an_unknown_choice_is_refused_naming_it(argument: str, value: str) -> None:
    options: dict[str, Any] = {argument: value}
    with pytest.raises(ValueError, match=re.escape(value)):
        render_pdf(_two_colour(10, 10, 6), **options)


def test_a_pdf_of_a_101_entry_key_is_refused_naming_the_limit() -> None:
    threads = dmc_threads()[: LIMIT + 1]
    pattern = build_pattern(_cells([list(range(LIMIT + 1))]), threads, 14.0)
    assert len(pattern.key) == LIMIT + 1
    with pytest.raises(ValueError, match="100"):
        render_pdf(pattern)


# Cover and key


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_a_100_entry_key_is_on_the_cover_in_key_order(
    paper: Paper, orientation: Orientation
) -> None:
    pattern = _hundred_threads()
    pdf = _read(render_pdf(pattern, paper=paper, orientation=orientation))
    lines = [line for text in pdf.covers for line in text.splitlines()]
    previous = -1
    for index, entry in enumerate(pattern.key):
        row = next(
            (n for n in range(previous + 1, len(lines)) if _is_key_row(lines[n], entry)), None
        )
        assert row is not None, f"key entry {index} ({entry.thread.code}) missing or out of order"
        previous = row
    cover_text = "\n".join(pdf.covers)
    position = -1
    countable = [
        (index, symbol)
        for index, symbol in enumerate(pattern_symbols(pattern))
        if symbol in COUNTABLE
    ]
    assert len(countable) > 50
    for index, symbol in countable:
        position = cover_text.find(symbol, position + 1)
        assert position >= 0, f"symbol {index} (U+{ord(symbol):04X}) missing or out of order"


@pytest.mark.parametrize("orientation", ORIENTATIONS)
def test_a_long_key_continues_on_more_cover_pages_counted_in_the_document(
    orientation: Orientation,
) -> None:
    pattern = _hundred_threads()
    pdf = _read(render_pdf(pattern, paper="A5", orientation=orientation))
    same_size = _read(render_pdf(_corners(101, 50), paper="A5", orientation=orientation))
    assert len(pdf.covers) >= 2
    assert len(pdf.charts) == len(same_size.charts)
    assert len(pdf.reader.pages) == len(pdf.covers) + len(same_size.charts)


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_every_entry_of_a_100_entry_key_has_its_own_symbol_on_the_chart(
    paper: Paper, orientation: Orientation
) -> None:
    pattern = _hundred_threads()
    pdf = _read(render_pdf(pattern, paper=paper, orientation=orientation))
    # Non-ASCII symbols only (ASCII ones also occur in labels and numbers); the
    # multiplication sign is left out too, in case a page writes a size as "w x h" with it.
    countable = [
        (index, symbol)
        for index, symbol in enumerate(pattern_symbols(pattern))
        if symbol in COUNTABLE
    ]
    assert len(countable) > 50
    for text, label in zip(pdf.charts, pdf.labels, strict=True):
        for index, symbol in countable:
            expected = _in_window(pattern, label, index)
            assert text.count(symbol) == expected, (label, index, f"U+{ord(symbol):04X}")


def test_the_cover_states_size_fabric_total_and_finished_size() -> None:
    # 41 x 23 on 16-count: 2.5625 x 1.4375 in, 6.50875 x 3.65125 cm; 300 + 217 stitches.
    cells = np.full(41 * 23, EMPTY, dtype=np.intp)
    cells[:300] = 0
    cells[300:517] = 1
    pattern = build_pattern(cells.reshape(23, 41), [BLACK, RED], 16.0)
    cover_text = "\n".join(_read(render_pdf(pattern)).covers)
    for fragment in ["41", "23", r"16(?:\.0)?", "517", r"2\.6", r"1\.4", r"6\.5", r"3\.7"]:
        assert _number(fragment).search(cover_text), fragment


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_each_half_shows_its_own_symbol_once_per_stitch(
    paper: Paper, orientation: Orientation
) -> None:
    pattern = _two_colour(13, 7, 7)
    assert [entry.stitches for entry in pattern.key] == [49, 42]
    pdf = _read(render_pdf(pattern, paper=paper, orientation=orientation))
    assert len(pdf.charts) == 1
    chart = pdf.charts[0]
    symbols = _countable_symbols(pattern)
    assert chart.count(symbols[0]) == pattern.key[0].stitches
    assert chart.count(symbols[1]) == pattern.key[1].stitches
    assert not [symbol for symbol in COUNTABLE if symbol not in symbols and symbol in chart]


def test_an_all_bare_pattern_renders_with_no_key_rows_and_no_symbols() -> None:
    pattern = build_pattern(np.full((10, 10), EMPTY, dtype=np.intp), [BLACK], 14.0)
    assert not pattern.key
    pdf = _read(render_pdf(pattern))
    assert pdf.labels == [(1, 10, 1, 10)]
    cover_text = "\n".join(pdf.covers)
    assert BLACK.name not in cover_text
    assert not _word(BLACK.code).search(cover_text)
    for text in pdf.covers + pdf.charts:
        assert not [symbol for symbol in COUNTABLE if symbol in text]


def test_a_converted_image_shows_one_symbol_per_stitched_cell() -> None:
    # 6 x 4: two columns black, two transparent (bare), two bright red (DMC 666 exactly).
    image = Image.new("RGBA", (6, 4), (0, 0, 0, 0))
    for y in range(4):
        for x in (0, 1):
            image.putpixel((x, y), (0, 0, 0, 255))
        for x in (4, 5):
            image.putpixel((x, y), (227, 29, 66, 255))
    pattern = convert_image(image, width=6, max_colours=2)
    assert pattern.total_stitches == 16
    assert len(pattern.key) == 2
    chart = _read(render_pdf(pattern)).charts[0]
    symbols = _countable_symbols(pattern)
    assert chart.count(symbols[0]) == pattern.key[0].stitches
    assert chart.count(symbols[1]) == pattern.key[1].stitches


# Variants


def test_the_colour_variant_fills_with_each_thread_colour() -> None:
    pattern = _five_colours()
    fills = _fills(_read(render_pdf(pattern, variant="colour")))
    for entry in pattern.key:
        target = [component / 255 for component in entry.thread.rgb]
        assert any(
            all(abs(got - want) <= COLOUR_TOLERANCE for got, want in zip(fill, target, strict=True))
            for fill in fills
            if len(fill) == 3
        ), f"no fill of {entry.thread.code} {entry.thread.rgb}"


def test_the_black_and_white_variant_sets_only_greys() -> None:
    pdf = _read(render_pdf(_five_colours(), variant="bw"))
    for number, page in enumerate(pdf.reader.pages, start=1):
        parts = _parts(pdf.reader, page)
        for operands, operator in parts.operations:
            assert operator not in NON_GREY_OPERATORS, (number, operator)
            if operator in (b"rg", b"RG"):
                red, green, blue = (float(value) for value in operands)
                assert red == green == blue, (number, operator, operands)
            if operator == b"INLINE IMAGE":
                settings = operands["settings"]
                space = settings.get("/CS", settings.get("/ColorSpace"))
                assert space in ("/G", "/DeviceGray"), (number, space)
        for image in parts.images:
            space = str(image["/ColorSpace"])
            assert space == "/DeviceGray", (number, space)


# Determinism


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_the_same_pattern_twice_gives_identical_bytes(
    paper: Paper, orientation: Orientation, variant: Variant
) -> None:
    first = render_pdf(_five_colours(), variant=variant, paper=paper, orientation=orientation)
    second = render_pdf(_five_colours(), variant=variant, paper=paper, orientation=orientation)
    assert first == second


def test_both_variants_give_each_entry_the_same_symbol() -> None:
    pattern = _five_colours()
    colour = _read(render_pdf(pattern, variant="colour"))
    bw = _read(render_pdf(pattern, variant="bw"))
    colour_cover, bw_cover = "\n".join(colour.covers), "\n".join(bw.covers)
    # Only symbols no label, name or number can contain can be counted in page text.
    countable = [symbol for symbol in pattern_symbols(pattern) if symbol in COUNTABLE]
    assert len(countable) >= 2
    for symbol in countable:
        assert symbol in colour_cover
        assert colour_cover.count(symbol) == bw_cover.count(symbol)
        for colour_text, bw_text in zip(colour.charts, bw.charts, strict=True):
            assert colour_text.count(symbol) == bw_text.count(symbol)


def test_the_two_variants_differ() -> None:
    pattern = _five_colours()
    assert render_pdf(pattern, variant="colour") != render_pdf(pattern, variant="bw")


def _today() -> set[bytes]:
    return {
        moment.strftime("%Y%m%d").encode()
        for moment in (datetime.now().astimezone(), datetime.now(UTC))
    }


def test_the_pdf_carries_no_date_of_rendering() -> None:
    before = _today()
    data = render_pdf(_five_colours())
    for stamp in before | _today():
        assert stamp not in data, stamp


# Every chart is split by these numbers: a change re-splits every chart, so it must be
# deliberate (and the docstring of `chart_capacity` updated with it).
PINNED_CAPACITIES: dict[tuple[str, str], tuple[int, int]] = {
    ("A2", "portrait"): (130, 185),
    ("A2", "landscape"): (188, 127),
    ("A3", "portrait"): (89, 127),
    ("A3", "landscape"): (130, 86),
    ("A4", "portrait"): (60, 86),
    ("A4", "landscape"): (89, 57),
    ("A5", "portrait"): (39, 57),
    ("A5", "landscape"): (60, 36),
}


@pytest.mark.parametrize(("paper", "orientation"), LAYOUTS, ids=LAYOUT_IDS)
def test_each_layout_holds_its_pinned_capacity(paper: Paper, orientation: Orientation) -> None:
    assert chart_capacity(paper, orientation) == PINNED_CAPACITIES[(paper, orientation)]


# Rec. 601 luminance 0.299 R + 0.587 G + 0.114 B: below 140 the symbol is white, else black.
@pytest.mark.parametrize(
    ("rgb", "ink"),
    [
        ((0, 0, 0), "white"),  # DMC 310
        ((252, 251, 248), "black"),  # DMC Blanc
        ((199, 43, 59), "white"),  # DMC 321, luminance about 91.5
        ((140, 140, 140), "black"),  # exactly 140
        ((139, 139, 139), "white"),  # just below
    ],
)
def test_symbol_ink_follows_the_luminance_of_the_thread(
    rgb: tuple[int, int, int], ink: str
) -> None:
    assert symbol_ink(rgb) == ink
