"""Chart layout settings of `render_pdf`: split by cells or by pages, overlap, centre lines,
section names and the section plan."""

import io
import re

import pytest
from pdf_helpers import (
    LABEL,
    NON_GREY_OPERATORS,
    _chart_pages,
    _corners,
    _countable_symbols,
    _hundred_threads,
    _in_window,
    _parts,
    _read,
    _speckled,
    _two_colour,
)
from PIL import Image
from pypdf import PdfReader

from cross_stitch.export import (
    MAX_PAGES,
    Orientation,
    chart_layout,
    page_options,
    render_pdf,
    section_name,
)


def _labels(data: bytes) -> list[tuple[int, int, int, int]]:
    return _read(data).labels


def test_cells_mode_takes_the_overlap() -> None:
    pattern = _corners(61, 3)

    assert _labels(render_pdf(pattern, overlap=0)) == [(1, 60, 1, 3), (61, 61, 1, 3)]
    assert _labels(render_pdf(pattern, overlap=5)) == [(1, 60, 1, 3), (56, 61, 1, 3)]


def test_the_defaults_are_the_cells_split_and_pages_play_no_part_in_it() -> None:
    pattern = _corners(130, 100)
    default = render_pdf(pattern)

    assert default == render_pdf(pattern, split="cells", overlap=2, centre_lines=False)
    assert default == render_pdf(pattern, split="cells", pages_across=5, pages_down=7)


def test_two_by_two_pages_split_equal_bands_sharing_the_overlap() -> None:
    pattern = _corners(100, 100)

    assert _labels(render_pdf(pattern, split="pages")) == [
        (1, 51, 1, 51),
        (50, 100, 1, 51),
        (1, 51, 50, 100),
        (50, 100, 50, 100),
    ]
    assert chart_layout(100, 100, split="pages").cell_mm == 3.5


def test_earlier_bands_take_the_extra_cell_and_the_cell_follows_the_widest() -> None:
    pattern = _corners(100, 30)
    labels = _labels(render_pdf(pattern, split="pages", pages_across=3, pages_down=1))

    assert labels == [(1, 35, 1, 30), (34, 68, 1, 30), (67, 100, 1, 30)]
    assert chart_layout(100, 30, split="pages", pages_across=3, pages_down=1).cell_mm == 5.1


def test_a_small_pattern_on_one_page_gets_the_largest_cell_and_symbols_to_match() -> None:
    pattern = _corners(10, 10)
    pages = render_pdf(pattern, split="pages", pages_across=1, pages_down=1)
    cells = render_pdf(pattern)

    assert _labels(pages) == [(1, 10, 1, 10)]
    assert chart_layout(10, 10, split="pages", pages_across=1, pages_down=1).cell_mm == 6.0
    assert 13.0 in _symbol_font_sizes(pages)
    assert 6.5 not in _symbol_font_sizes(pages)
    assert 6.5 in _symbol_font_sizes(cells)
    assert 13.0 not in _symbol_font_sizes(cells)


def _symbol_font_sizes(data: bytes) -> set[float]:
    """Every font size the chart pages set (symbols, label, numbers alike)."""
    pdf = _read(data)
    sizes: set[float] = set()
    for page in _chart_pages(pdf):
        for operands, operator in _parts(pdf.reader, page).operations:
            if operator == b"Tf":
                sizes.add(float(operands[1]))
    return sizes


def test_a_1000_cell_pattern_needs_at_least_12_by_8_pages_at_2_mm() -> None:
    layout = chart_layout(1000, 1000, split="pages", pages_across=12, pages_down=8)
    assert layout.cell_mm == 2.0
    assert len(layout.columns) * len(layout.rows) == 96

    for across, down in [(11, 8), (12, 7)]:
        with pytest.raises(ValueError, match=r"2\.0 mm") as raised:
            chart_layout(1000, 1000, split="pages", pages_across=across, pages_down=down)
        assert "12" in str(raised.value)
        assert "8" in str(raised.value)


def test_a_pattern_narrower_than_its_pages_and_overlap_is_refused() -> None:
    with pytest.raises(ValueError):
        render_pdf(_corners(5, 3), split="pages", pages_across=4, pages_down=1)

    data = render_pdf(_corners(6, 3), split="pages", pages_across=4, pages_down=1)
    assert len(_labels(data)) == 4


@pytest.mark.parametrize(
    ("options", "name"),
    [
        ({"split": "rows"}, "split"),
        ({"overlap": 6}, "overlap"),
        ({"overlap": -1}, "overlap"),
        ({"split": "pages", "pages_across": 0}, "pages_across"),
        ({"split": "pages", "pages_down": 21}, "pages_down"),
    ],
)
def test_out_of_range_settings_are_refused_naming_them(
    options: dict[str, object], name: str
) -> None:
    with pytest.raises(ValueError, match=name):
        render_pdf(_corners(20, 20), **options)  # type: ignore[arg-type]


def test_a_pages_split_covers_every_cell_with_its_own_symbol() -> None:
    pattern = _speckled(130, 100)
    pdf = _read(render_pdf(pattern, split="pages", pages_across=3, pages_down=2, overlap=1))
    first, second = _countable_symbols(pattern)

    assert len(pdf.labels) == 6
    covered_columns = {c for label in pdf.labels for c in range(label[0], label[1] + 1)}
    covered_rows = {r for label in pdf.labels for r in range(label[2], label[3] + 1)}
    assert covered_columns == set(range(1, 131))
    assert covered_rows == set(range(1, 101))
    for text, label in zip(pdf.charts, pdf.labels, strict=True):
        assert text.count(first) == _in_window(pattern, label, 0), label
        assert text.count(second) == _in_window(pattern, label, 1), label


def _red_strokes(data: bytes) -> list[bool]:
    """For each chart page, whether it sets a pure red stroking colour."""
    pdf = _read(data)
    found = []
    for page in _chart_pages(pdf):
        operations = _parts(pdf.reader, page).operations
        found.append(
            any(
                operator == b"RG" and [float(v) for v in operands] == [1.0, 0.0, 0.0]
                for operands, operator in operations
            )
        )
    return found


def test_centre_lines_are_red_on_the_pages_that_hold_the_centre_only() -> None:
    pattern = _corners(130, 100)

    with_lines = _red_strokes(render_pdf(pattern, centre_lines=True))
    assert with_lines[1]  # B1 holds column 65 and row 50
    assert not with_lines[5]  # C2 holds neither
    assert not any(_red_strokes(render_pdf(pattern)))


def test_black_and_white_centre_lines_stay_grey() -> None:
    pattern = _corners(130, 100)
    with_lines = render_pdf(pattern, variant="bw", centre_lines=True)
    pdf = _read(with_lines)

    for page in _chart_pages(pdf):
        operators = {op for _, op in _parts(pdf.reader, page).operations}
        assert not operators & NON_GREY_OPERATORS
        assert b"RG" not in operators
        assert b"rg" not in operators
    assert with_lines != render_pdf(pattern, variant="bw")


NAMES = ["A1", "B1", "C1", "A2", "B2", "C2"]


def _headed(text: str, name: str) -> bool:
    return re.search(rf"\b{name} - Columns\s+\d", text) is not None


def test_chart_pages_are_headed_by_their_section_in_reading_order() -> None:
    pdf = _read(render_pdf(_corners(130, 100)))

    assert len(pdf.charts) == 6
    for text, name in zip(pdf.charts, NAMES, strict=True):
        assert _headed(text, name), name


def test_a_section_plan_page_names_every_section_once_before_the_chart() -> None:
    pdf = _read(render_pdf(_corners(130, 100)))

    assert len(pdf.covers) == 2
    plan = pdf.covers[1]
    assert "Section plan" in plan
    for name in NAMES:
        assert len(re.findall(rf"\b{name}\b", plan)) == 1, name
    assert not LABEL.search(plan)


def test_a_one_section_chart_has_no_plan_page() -> None:
    pdf = _read(render_pdf(_two_colour(10, 10, 6)))

    assert len(pdf.reader.pages) == 2
    assert _headed(pdf.charts[0], "A1")
    assert "A1 - Columns 1-10, rows 1-10" in pdf.charts[0]
    assert not any("Section plan" in text for text in pdf.covers + pdf.charts)


def test_columns_past_z_are_named_aa() -> None:
    pdf = _read(render_pdf(_corners(923, 3), paper="A5", overlap=5))

    assert len(pdf.charts) == 27
    assert _headed(pdf.charts[25], "Z1")
    assert _headed(pdf.charts[26], "AA1")
    assert section_name(27, 0) == "AB1"


def test_the_plan_comes_after_the_last_thread_key_page() -> None:
    pdf = _read(render_pdf(_hundred_threads(), paper="A5"))

    assert len(pdf.covers) >= 3
    assert "Section plan" in pdf.covers[-1]
    assert "Thread key" in pdf.covers[-2]


def test_a_pages_split_names_its_sections_the_same_way() -> None:
    pdf = _read(render_pdf(_corners(130, 100), split="pages", pages_across=3, pages_down=2))

    for text, name in zip(pdf.charts, NAMES, strict=True):
        assert _headed(text, name), name
    assert "Section plan" in pdf.covers[-1]


def test_the_cover_states_the_chart_cell() -> None:
    assert "Chart cell: 3.0 mm" in _read(render_pdf(_corners(100, 100))).covers[0]
    pages = render_pdf(_corners(100, 100), split="pages")
    assert "Chart cell: 3.5 mm" in _read(pages).covers[0]


def test_the_black_and_white_plan_page_is_grey_only() -> None:
    pdf = _read(render_pdf(_corners(130, 100), variant="bw"))
    plan_page = pdf.reader.pages[len(pdf.covers) - 1]

    operators = {op for _, op in _parts(pdf.reader, plan_page).operations}
    assert not operators & NON_GREY_OPERATORS
    assert b"rg" not in operators
    assert b"RG" not in operators


# --------------------------------------------------------------------------- fabric colour


def _cover_thumbnail(data: bytes) -> Image.Image:
    """The thumbnail on the cover: the first image of the first page, one pixel per cell."""
    image = PdfReader(io.BytesIO(data)).get_page(0).images[0].image
    assert image is not None
    return image


def test_bare_cells_of_the_cover_thumbnail_take_the_fabric_colour() -> None:
    pattern = _corners(20, 10)
    thumbnail = _cover_thumbnail(render_pdf(pattern, fabric_rgb=(200, 30, 60)))

    assert thumbnail.size == (20, 10)
    assert thumbnail.convert("RGB").getpixel((5, 5)) == (200, 30, 60)
    assert thumbnail.convert("RGB").getpixel((0, 0)) == (0, 0, 0)


def test_the_black_and_white_thumbnail_shows_the_fabric_in_grey() -> None:
    thumbnail = _cover_thumbnail(
        render_pdf(_corners(20, 10), variant="bw", fabric_rgb=(200, 30, 60))
    )
    grey = round(0.299 * 200 + 0.587 * 30 + 0.114 * 60)
    assert thumbnail.convert("L").getpixel((5, 5)) == grey


def test_white_fabric_is_the_default_and_leaves_the_chart_pages_as_they_are() -> None:
    pattern = _corners(70, 10)
    assert render_pdf(pattern) == render_pdf(pattern, fabric_rgb=(255, 255, 255))
    coloured = _read(render_pdf(pattern, fabric_rgb=(20, 20, 20)))
    plain = _read(render_pdf(pattern))
    assert [p.extract_text() for p in _chart_pages(coloured)] == [
        p.extract_text() for p in _chart_pages(plain)
    ]


# --------------------------------------------------------------------------- page options


@pytest.mark.parametrize("size", [(100, 100), (1000, 700), (30, 300)])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
def test_every_page_option_is_what_chart_layout_gives_or_refuses(
    size: tuple[int, int], orientation: Orientation
) -> None:
    width, height = size
    options = page_options(width, height, paper="A4", orientation=orientation, overlap=2)

    assert len(options) == MAX_PAGES
    for down, row in enumerate(options, start=1):
        assert len(row) == MAX_PAGES
        for across, option in enumerate(row, start=1):
            try:
                layout = chart_layout(
                    width,
                    height,
                    orientation=orientation,
                    split="pages",
                    pages_across=across,
                    pages_down=down,
                )
            except ValueError:
                assert option.cell_mm is None, (across, down)
                continue
            assert option.cell_mm == layout.cell_mm, (across, down)
            assert option.columns == max(band.size for band in layout.columns)
            assert option.rows == max(band.size for band in layout.rows)


def test_the_orientation_changes_the_cell_of_a_split() -> None:
    # 6 pages across, 4 down: the bands are narrow and tall, so the sheet's way matters.
    portrait = page_options(300, 300, orientation="portrait")[3][5]
    landscape = page_options(300, 300, orientation="landscape")[3][5]
    assert portrait.cell_mm is not None and landscape.cell_mm is not None
    assert portrait.cell_mm != landscape.cell_mm


def test_page_options_refuse_an_overlap_out_of_range() -> None:
    with pytest.raises(ValueError, match="overlap"):
        page_options(100, 100, overlap=6)
