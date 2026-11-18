"""edit_pattern: replacements, strokes, rectangles and fills applied in order, each entry
counting the cells whose value it changed.

Patterns are drawn as rows of letters with `cleanup_helpers.drawn`, (x, y) being (column,
row). The expected pattern of each case is drawn again with `drawn`, so `build_pattern`
(merge, re-sort, skeins) is the reference, never `edit_pattern` itself. The replacement
cases on their own are in `test_replace_threads.py`.
"""

import itertools
import tracemalloc
from collections.abc import Callable, Sequence

import numpy as np
import pytest
from cleanup_helpers import (
    SHADES,
    Cell,
    all_bare,
    assert_counts_add_up,
    assert_equal_patterns,
    code_grid,
    counted,
    drawn,
    one_cell,
    speckled,
)

from cross_stitch.pattern import (
    Change,
    Edited,
    Fill,
    Pattern,
    Rect,
    Replace,
    Stroke,
    edit_pattern,
    skeins_needed,
)
from cross_stitch.threads import Thread, dmc_thread

type Size = tuple[int, int]

# The background of most cases, and the thread painted on it.
WHITE = {"A": "Blanc"}
PAINTED = {"A": "Blanc", "B": "310"}


def _thread(code: str | None) -> Thread | None:
    return None if code is None else dmc_thread(code)


def _plain(width: int, height: int) -> Pattern:
    """`width` x `height` cells, all Blanc."""
    return drawn(["A" * width] * height, WHITE)


def _stroke(code: str | None, points: Sequence[Cell], grid: Size, brush: int = 1) -> Stroke:
    return Stroke(thread=_thread(code), brush=brush, grid=grid, points=tuple(points))


def _rect(code: str | None, start: Cell, end: Cell, grid: Size) -> Rect:
    return Rect(thread=_thread(code), grid=grid, start=start, end=end)


def _fill(code: str | None, at: Cell, grid: Size) -> Fill:
    return Fill(thread=_thread(code), grid=grid, at=at)


def _size(pattern: Pattern) -> Size:
    return (pattern.width, pattern.height)


def _cells_on(pattern: Pattern, code: str) -> set[Cell]:
    """The (x, y) of every cell on the thread `code`."""
    index = [entry.thread.code for entry in pattern.key].index(code)
    rows, columns = np.nonzero(pattern.grid == index)
    return {(int(x), int(y)) for x, y in zip(columns, rows, strict=True)}


# ---------------------------------------------------------------------------- nothing


def test_no_entries_give_the_same_grid_and_key_and_no_counts() -> None:
    pattern = drawn(["AB.", "BBA"], PAINTED)
    result = edit_pattern(pattern, [])
    assert isinstance(result, Edited)
    assert_equal_patterns(result.pattern, pattern)
    assert isinstance(result.changed, tuple)
    assert not result.changed


# ----------------------------------------------------------------------------- strokes


def test_x_is_the_column_and_y_the_row() -> None:
    pattern = _plain(3, 2)
    result = edit_pattern(pattern, [_stroke("310", [(2, 0)], (3, 2))])
    assert_equal_patterns(result.pattern, drawn(["AAB", "AAA"], PAINTED))
    assert result.changed == (1,)


def test_a_one_point_stroke_of_brush_1_paints_one_cell() -> None:
    pattern = _plain(3, 3)
    result = edit_pattern(pattern, [_stroke("310", [(1, 1)], (3, 3))])
    assert counted(result.pattern) == [("Blanc", 8), ("310", 1)]
    assert_equal_patterns(result.pattern, drawn(["AAA", "ABA", "AAA"], PAINTED))
    assert result.changed == (1,)


@pytest.mark.parametrize("brush", [3, 5, 9])
def test_a_brush_wider_than_the_pattern_centred_in_it_paints_every_cell(brush: int) -> None:
    result = edit_pattern(_plain(3, 3), [_stroke("310", [(1, 1)], (3, 3), brush)])
    assert counted(result.pattern) == [("310", 9)]
    assert result.changed == (9,)


@pytest.mark.parametrize(
    ("at", "rows"),
    [
        ((0, 0), ["BBA", "BBA", "AAA"]),
        ((2, 0), ["ABB", "ABB", "AAA"]),
        ((2, 2), ["AAA", "ABB", "ABB"]),
        ((0, 2), ["AAA", "BBA", "BBA"]),
    ],
)
def test_a_brush_3_at_a_corner_paints_the_4_cells_in_reach(at: Cell, rows: list[str]) -> None:
    result = edit_pattern(_plain(3, 3), [_stroke("310", [at], (3, 3), brush=3)])
    assert_equal_patterns(result.pattern, drawn(rows, PAINTED))
    assert result.changed == (4,)


def test_a_brush_5_is_a_5_by_5_square_centred_on_the_cell() -> None:
    result = edit_pattern(_plain(7, 6), [_stroke("310", [(3, 2)], (7, 6), brush=5)])
    rows = ["ABBBBBA", "ABBBBBA", "ABBBBBA", "ABBBBBA", "ABBBBBA", "AAAAAAA"]
    assert_equal_patterns(result.pattern, drawn(rows, PAINTED))
    assert result.changed == (25,)


def test_a_point_off_the_grid_paints_the_cells_its_brush_reaches() -> None:
    result = edit_pattern(_plain(3, 3), [_stroke("310", [(-1, -1)], (3, 3), brush=3)])
    assert_equal_patterns(result.pattern, drawn(["BAA", "AAA", "AAA"], PAINTED))
    assert result.changed == (1,)


@pytest.mark.parametrize("point", [(-2, -2), (5, 1), (1, 4), (-2, 1)])
def test_a_brush_wholly_off_the_grid_changes_nothing(point: Cell) -> None:
    pattern = _plain(3, 3)
    result = edit_pattern(pattern, [_stroke("310", [point], (3, 3), brush=3)])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


def test_two_points_on_a_row_paint_every_cell_between_them_and_no_more() -> None:
    result = edit_pattern(_plain(6, 2), [_stroke("310", [(0, 0), (4, 0)], (6, 2))])
    assert_equal_patterns(result.pattern, drawn(["BBBBBA", "AAAAAA"], PAINTED))
    assert result.changed == (5,)


def test_two_points_on_a_column_paint_every_cell_between_them() -> None:
    result = edit_pattern(_plain(3, 4), [_stroke("310", [(1, 3), (1, 0)], (3, 4))])
    assert_equal_patterns(result.pattern, drawn(["ABA", "ABA", "ABA", "ABA"], PAINTED))
    assert result.changed == (4,)


@pytest.mark.parametrize("points", [[(0, 0), (3, 3)], [(3, 3), (0, 0)]])
def test_a_diagonal_paints_only_its_diagonal_cells(points: list[Cell]) -> None:
    result = edit_pattern(_plain(4, 4), [_stroke("310", points, (4, 4))])
    assert_equal_patterns(result.pattern, drawn(["BAAA", "ABAA", "AABA", "AAAB"], PAINTED))
    assert result.changed == (4,)


def test_a_steep_line_is_an_8_connected_path_of_max_dx_dy_plus_1_cells() -> None:
    result = edit_pattern(_plain(8, 4), [_stroke("310", [(0, 0), (7, 3)], (8, 4))])

    cells = _cells_on(result.pattern, "310")
    assert result.changed == (8,)
    assert len(cells) == 8
    assert {(0, 0), (7, 3)} <= cells
    # Eight cells over eight columns: one per column, each step to an 8-neighbour.
    rows = [y for _, y in sorted(cells)]
    assert sorted(x for x, _ in cells) == list(range(8))
    assert all(0 <= after - before <= 1 for before, after in itertools.pairwise(rows))


@pytest.mark.parametrize("points", [[(0, 0), (7, 3)], [(7, 3), (0, 0)]])
def test_a_line_keeps_within_half_a_cell_of_the_straight_line(points: list[Cell]) -> None:
    result = edit_pattern(_plain(8, 4), [_stroke("310", points, (8, 4))])
    # The straight line from (0, 0) to (7, 3) is y = 3x / 7; no cell centre ties.
    assert sorted(_cells_on(result.pattern, "310")) == [
        (0, 0),
        (1, 0),
        (2, 1),
        (3, 1),
        (4, 2),
        (5, 2),
        (6, 3),
        (7, 3),
    ]


def test_successive_points_join_into_one_path_and_the_joint_counts_once() -> None:
    result = edit_pattern(_plain(3, 3), [_stroke("310", [(0, 0), (2, 0), (2, 2)], (3, 3))])
    assert_equal_patterns(result.pattern, drawn(["BBB", "AAB", "AAB"], PAINTED))
    assert result.changed == (5,)


def test_a_line_from_off_the_grid_is_clipped_to_it() -> None:
    result = edit_pattern(_plain(3, 2), [_stroke("310", [(-2, 0), (2, 0)], (3, 2))])
    assert_equal_patterns(result.pattern, drawn(["BBB", "AAA"], PAINTED))
    assert result.changed == (3,)


def test_a_long_zig_zag_off_the_grid_costs_only_what_crosses_it() -> None:
    # 20 000 lines of 4000 steps each, all but the 5 diagonal cells off a 5 x 5 grid:
    # 80 million cells if every step were generated, a few kilobytes when clipped first.
    pattern = _plain(5, 5)
    corners = ((-2000, -2000), (2000, 2000))
    stroke = Stroke(dmc_thread("310"), brush=1, grid=(5, 5), points=corners * 10_000)
    tracemalloc.start()
    try:
        result = edit_pattern(pattern, [stroke])
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert result.changed == (5,)
    assert [code_grid(result.pattern)[i][i] for i in range(5)] == ["310"] * 5
    assert peak < 64 * 1024 * 1024


def test_a_repeated_point_counts_its_cell_once() -> None:
    result = edit_pattern(_plain(3, 3), [_stroke("310", [(1, 1), (1, 1), (2, 1)], (3, 3))])
    assert_equal_patterns(result.pattern, drawn(["AAA", "ABB", "AAA"], PAINTED))
    assert result.changed == (2,)


def test_a_stroke_counts_only_the_cells_not_already_on_its_thread() -> None:
    pattern = drawn(["ABBAA"], PAINTED)
    result = edit_pattern(pattern, [_stroke("310", [(0, 0), (4, 0)], (5, 1))])
    assert_equal_patterns(result.pattern, drawn(["BBBBB"], PAINTED))
    assert result.changed == (3,)


def test_a_stroke_over_cells_all_on_its_thread_counts_zero_and_changes_nothing() -> None:
    pattern = drawn(["ABBAA"], PAINTED)
    result = edit_pattern(pattern, [_stroke("310", [(1, 0), (2, 0)], (5, 1))])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


def test_an_eraser_stroke_leaves_its_cells_bare_and_the_total_drops_by_its_count() -> None:
    pattern = drawn(["AAB.", "AAAA"], PAINTED)
    result = edit_pattern(pattern, [_stroke(None, [(0, 0), (3, 0)], (4, 2))])
    assert_equal_patterns(result.pattern, drawn(["....", "AAAA"], PAINTED))
    assert result.changed == (3,)
    assert result.pattern.total_stitches == pattern.total_stitches - 3


def test_erasing_bare_cells_counts_zero() -> None:
    pattern = drawn(["AA..", "AAAA"], PAINTED)
    result = edit_pattern(pattern, [_stroke(None, [(2, 0), (3, 0)], (4, 2))])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


def test_a_thread_outside_the_key_joins_it_with_its_count_and_skeins() -> None:
    fabric_count = 18.0
    legend = {"A": "Blanc", "B": "310", "C": "321", "D": "3865"}
    pattern = drawn(["AAB", "AAB", "CCC"], legend, fabric_count)

    result = edit_pattern(pattern, [_stroke("3865", [(0, 2), (1, 2)], (3, 3))])

    assert_equal_patterns(result.pattern, drawn(["AAB", "AAB", "DDC"], legend, fabric_count))
    assert counted(result.pattern) == [("Blanc", 4), ("310", 2), ("3865", 2), ("321", 1)]
    entry = result.pattern.key[2]
    assert entry.skeins == skeins_needed(2, fabric_count)
    assert result.changed == (2,)


def test_painting_over_every_cell_of_a_thread_removes_it_from_the_key() -> None:
    legend = {"A": "Blanc", "B": "310", "C": "321"}
    pattern = drawn(["AAC", "AAC"], legend)
    result = edit_pattern(pattern, [_stroke("310", [(2, 0), (2, 1)], (3, 2))])
    assert counted(result.pattern) == [("Blanc", 4), ("310", 2)]
    assert_equal_patterns(result.pattern, drawn(["AAB", "AAB"], legend))


def test_painting_on_a_bare_pattern_gives_it_a_key() -> None:
    pattern = all_bare()
    result = edit_pattern(pattern, [_stroke("310", [(1, 0)], (4, 2), brush=3)])
    assert_equal_patterns(result.pattern, drawn(["BBB.", "BBB."], PAINTED))
    assert result.changed == (6,)


def test_any_brush_on_a_one_cell_pattern_paints_that_cell() -> None:
    result = edit_pattern(one_cell(), [_stroke("310", [(0, 0)], (1, 1), brush=9)])
    assert counted(result.pattern) == [("310", 1)]
    assert result.changed == (1,)


@pytest.mark.parametrize("brush", [0, 2, 4, -1, -3])
def test_a_brush_that_is_not_odd_from_1_is_a_value_error(brush: int) -> None:
    with pytest.raises(ValueError, match="brush"):
        edit_pattern(_plain(3, 3), [_stroke("310", [(1, 1)], (3, 3), brush)])


def test_a_stroke_with_no_points_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="point"):
        edit_pattern(_plain(3, 3), [_stroke("310", [], (3, 3))])


# -------------------------------------------------------------------------- rectangles

RECT_ROWS = ["ABBBA", "ABBBA", "ABBBA", "AAAAA"]


@pytest.mark.parametrize(
    ("start", "end"),
    [((1, 0), (3, 2)), ((3, 2), (1, 0)), ((3, 0), (1, 2)), ((1, 2), (3, 0))],
)
def test_a_rectangle_paints_every_cell_between_its_corners_in_any_order(
    start: Cell, end: Cell
) -> None:
    result = edit_pattern(_plain(5, 4), [_rect("310", start, end, (5, 4))])
    assert_equal_patterns(result.pattern, drawn(RECT_ROWS, PAINTED))
    assert result.changed == (9,)


def test_a_rectangle_of_one_corner_is_one_cell() -> None:
    result = edit_pattern(_plain(5, 4), [_rect("310", (2, 1), (2, 1), (5, 4))])
    assert_equal_patterns(result.pattern, drawn(["AAAAA", "AABAA", "AAAAA", "AAAAA"], PAINTED))
    assert result.changed == (1,)


@pytest.mark.parametrize(
    ("start", "end", "rows"),
    [
        ((-2, -1), (1, 1), ["BBAAA", "BBAAA", "AAAAA", "AAAAA"]),
        ((3, 2), (9, 9), ["AAAAA", "AAAAA", "AAABB", "AAABB"]),
        ((-5, 1), (9, 1), ["AAAAA", "BBBBB", "AAAAA", "AAAAA"]),
    ],
)
def test_a_rectangle_partly_off_the_grid_is_clipped(
    start: Cell, end: Cell, rows: list[str]
) -> None:
    result = edit_pattern(_plain(5, 4), [_rect("310", start, end, (5, 4))])
    assert_equal_patterns(result.pattern, drawn(rows, PAINTED))
    assert result.changed == (sum(row.count("B") for row in rows),)


@pytest.mark.parametrize(
    ("start", "end"),
    [((5, 0), (9, 3)), ((-3, -3), (-1, -1)), ((0, 4), (4, 6)), ((-1, 0), (-4, 3))],
)
def test_a_rectangle_wholly_off_the_grid_counts_zero(start: Cell, end: Cell) -> None:
    pattern = _plain(5, 4)
    result = edit_pattern(pattern, [_rect("310", start, end, (5, 4))])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


def test_an_eraser_rectangle_counts_only_the_stitched_cells_it_bares() -> None:
    pattern = drawn(["AB.", "AAA"], PAINTED)
    result = edit_pattern(pattern, [_rect(None, (2, 0), (0, 0), (3, 2))])
    assert_equal_patterns(result.pattern, drawn(["...", "AAA"], PAINTED))
    assert result.changed == (2,)


# ------------------------------------------------------------------------------- fills


def test_a_fill_takes_the_cells_joined_by_a_side_not_those_joined_by_a_corner() -> None:
    legend = {"A": "Blanc", "B": "310", "C": "321"}
    pattern = drawn(["AAB", "ABA", "BAA"], legend)
    result = edit_pattern(pattern, [_fill("321", (0, 0), (3, 3))])
    assert_equal_patterns(result.pattern, drawn(["CCB", "CBA", "BAA"], legend))
    assert result.changed == (3,)


def test_a_fill_on_bare_fabric_stitches_that_zone_only() -> None:
    pattern = drawn(["..A..", "..A..", "..A.."], PAINTED)
    result = edit_pattern(pattern, [_fill("310", (0, 0), (5, 3))])
    assert_equal_patterns(result.pattern, drawn(["BBA..", "BBA..", "BBA.."], PAINTED))
    assert result.changed == (6,)


def test_an_eraser_fill_bares_the_zone() -> None:
    pattern = drawn(["AAB", "AAB"], PAINTED)
    result = edit_pattern(pattern, [_fill(None, (1, 1), (3, 2))])
    assert_equal_patterns(result.pattern, drawn(["..B", "..B"], PAINTED))
    assert result.changed == (4,)
    assert result.pattern.total_stitches == 2


def test_a_fill_of_a_whole_bare_pattern_stitches_every_cell() -> None:
    result = edit_pattern(all_bare(), [_fill("310", (3, 1), (4, 2))])
    assert counted(result.pattern) == [("310", 8)]
    assert result.changed == (8,)


@pytest.mark.parametrize(("code", "at"), [("Blanc", (0, 0)), (None, (3, 0)), ("310", (2, 0))])
def test_a_fill_with_the_zone_s_own_value_counts_zero(code: str | None, at: Cell) -> None:
    pattern = drawn(["AAB.", "AAB."], PAINTED)
    result = edit_pattern(pattern, [_fill(code, at, (4, 2))])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


@pytest.mark.parametrize("at", [(-1, 0), (0, -1), (5, 1), (1, 3), (5, 3)])
def test_a_fill_off_the_grid_counts_zero(at: Cell) -> None:
    pattern = drawn(["AAB..", "AAB..", "AAB.."], PAINTED)
    result = edit_pattern(pattern, [_fill("321", at, (5, 3))])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


# ----------------------------------------------------------------- the grid drawn on

type HandEdit = Callable[[Size], Change]

HAND_EDITS: dict[str, HandEdit] = {
    "stroke": lambda grid: _stroke("310", [(0, 0), (2, 1)], grid),
    "eraser": lambda grid: _stroke(None, [(1, 1)], grid, brush=3),
    "rect": lambda grid: _rect("310", (0, 0), (1, 1), grid),
    "fill": lambda grid: _fill("321", (0, 0), grid),
}


@pytest.mark.parametrize("kind", list(HAND_EDITS))
@pytest.mark.parametrize("grid", [(2, 3), (4, 2), (3, 3), (3, 1), (0, 0)])
def test_a_hand_edit_drawn_on_another_grid_size_counts_zero(kind: str, grid: Size) -> None:
    pattern = drawn(["AAB", "A.A"], PAINTED)
    assert _size(pattern) == (3, 2)
    result = edit_pattern(pattern, [HAND_EDITS[kind](grid)])
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


@pytest.mark.parametrize("kind", list(HAND_EDITS))
def test_a_hand_edit_drawn_on_the_pattern_s_size_applies(kind: str) -> None:
    pattern = drawn(["AAB", "A.A"], PAINTED)
    assert edit_pattern(pattern, [HAND_EDITS[kind]((3, 2))]).changed[0] > 0


def test_a_replace_has_no_size_and_applies_after_a_skipped_hand_edit() -> None:
    pattern = _plain(3, 2)
    entries: list[Change] = [
        _stroke("321", [(0, 0)], (2, 3)),
        Replace(old=dmc_thread("Blanc"), new=dmc_thread("310")),
    ]
    result = edit_pattern(pattern, entries)
    assert counted(result.pattern) == [("310", 6)]
    assert result.changed == (0, 6)


# ------------------------------------------------------------------------------- order


def test_a_stroke_then_a_replace_of_its_thread_moves_the_painted_cell_too() -> None:
    entries: list[Change] = [
        _stroke("310", [(0, 0)], (3, 3)),
        Replace(old=dmc_thread("310"), new=dmc_thread("300")),
    ]
    result = edit_pattern(_plain(3, 3), entries)
    assert_equal_patterns(result.pattern, drawn(["BAA", "AAA", "AAA"], {"A": "Blanc", "B": "300"}))
    assert result.changed == (1, 1)


def test_a_replace_then_a_stroke_of_its_old_thread_keeps_the_painted_cell() -> None:
    entries: list[Change] = [
        Replace(old=dmc_thread("310"), new=dmc_thread("300")),
        _stroke("310", [(0, 0)], (3, 3)),
    ]
    result = edit_pattern(_plain(3, 3), entries)
    assert_equal_patterns(result.pattern, drawn(["BAA", "AAA", "AAA"], PAINTED))
    assert result.changed == (0, 1)


def test_a_fill_after_a_stroke_cutting_its_zone_stops_at_the_stroke() -> None:
    entries: list[Change] = [
        _stroke("310", [(2, 0), (2, 2)], (5, 3)),
        _fill("321", (0, 0), (5, 3)),
    ]
    result = edit_pattern(_plain(5, 3), entries)
    legend = {"A": "Blanc", "B": "310", "C": "321"}
    assert_equal_patterns(result.pattern, drawn(["CCBAA", "CCBAA", "CCBAA"], legend))
    assert result.changed == (3, 6)


def test_a_fill_does_not_leak_through_a_diagonal_stroke() -> None:
    entries: list[Change] = [
        _stroke("310", [(3, 0), (0, 3)], (4, 4)),
        _fill("321", (0, 0), (4, 4)),
    ]
    result = edit_pattern(_plain(4, 4), entries)
    legend = {"A": "Blanc", "B": "310", "C": "321"}
    assert_equal_patterns(result.pattern, drawn(["CCCB", "CCBA", "CBAA", "BAAA"], legend))
    assert result.changed == (4, 6)


def test_a_rectangle_over_a_stroke_counts_only_what_it_changes() -> None:
    entries: list[Change] = [
        _stroke("310", [(0, 0), (4, 0)], (5, 2)),
        _rect("310", (0, 0), (4, 1), (5, 2)),
    ]
    result = edit_pattern(_plain(5, 2), entries)
    assert counted(result.pattern) == [("310", 10)]
    assert result.changed == (5, 5)


# ------------------------------------------------------------------- random sequences


def _random_changes(rng: np.random.Generator, size: Size, count: int) -> list[Change]:
    """`count` seeded entries of all four kinds, a few drawn on another size, cells within
    3 of the grid on every side so some are clipped."""
    width, height = size

    def cell() -> Cell:
        return (int(rng.integers(-3, width + 3)), int(rng.integers(-3, height + 3)))

    def thread() -> Thread | None:
        return None if rng.random() < 0.2 else dmc_thread(SHADES[int(rng.integers(len(SHADES)))])

    changes: list[Change] = []
    for _ in range(count):
        grid = size if rng.random() < 0.9 else (width + 1, height)
        kind = int(rng.integers(4))
        if kind == 0:
            changes.append(Replace(old=dmc_thread(SHADES[int(rng.integers(8))]), new=thread()))
        elif kind == 1:
            points = tuple(cell() for _ in range(int(rng.integers(1, 5))))
            brush = int(rng.choice([1, 3, 5]))
            changes.append(Stroke(thread=thread(), brush=brush, grid=grid, points=points))
        elif kind == 2:
            changes.append(Rect(thread=thread(), grid=grid, start=cell(), end=cell()))
        else:
            changes.append(Fill(thread=thread(), grid=grid, at=cell()))
    return changes


@pytest.mark.parametrize("seed", range(8))
def test_counts_add_up_after_a_random_sequence_of_all_four_kinds(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pattern = speckled(SHADES[:6], (10, 12), seed=seed)
    changes = _random_changes(rng, _size(pattern), 20)

    result = edit_pattern(pattern, changes)
    after = result.pattern

    assert_counts_add_up(after, pattern)

    assert len(result.changed) == len(changes)
    assert all(0 <= count <= pattern.width * pattern.height for count in result.changed)
    # A cell that differs at the end was changed by at least one entry.
    before_codes, after_codes = code_grid(pattern), code_grid(after)
    differing = sum(
        first != second
        for row_before, row_after in zip(before_codes, after_codes, strict=True)
        for first, second in zip(row_before, row_after, strict=True)
    )
    assert differing <= sum(result.changed)
    assert abs(after.total_stitches - pattern.total_stitches) <= sum(result.changed)


@pytest.mark.parametrize("seed", range(4))
def test_entries_applied_one_call_at_a_time_give_the_same_pattern_and_counts(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pattern = speckled(SHADES[:6], (10, 12), seed=seed)
    changes = _random_changes(rng, _size(pattern), 12)

    whole = edit_pattern(pattern, changes)

    step = pattern
    counts: list[int] = []
    for change in changes:
        edited = edit_pattern(step, [change])
        step = edited.pattern
        counts.extend(edited.changed)
    assert_equal_patterns(whole.pattern, step)
    assert whole.changed == tuple(counts)


# ------------------------------------------------------------- purity and determinism

MIXED: list[Change] = [
    _stroke("3865", [(0, 0), (3, 1)], (4, 3), brush=3),
    Replace(old=dmc_thread("Blanc"), new=dmc_thread("321")),
    _rect(None, (3, 2), (2, 1), (4, 3)),
    _fill("797", (0, 2), (4, 3)),
]


def test_the_input_pattern_is_not_modified() -> None:
    pattern = drawn(["AAB.", "ABBA", "AAAA"], PAINTED)
    grid_before = pattern.grid.copy()
    key_before = pattern.key
    edit_pattern(pattern, MIXED)
    assert np.array_equal(pattern.grid, grid_before)
    assert pattern.key == key_before
    assert not pattern.grid.flags.writeable


def test_the_result_grid_is_read_only() -> None:
    result = edit_pattern(drawn(["AAB.", "ABBA", "AAAA"], PAINTED), MIXED)
    assert not result.pattern.grid.flags.writeable
    assert result.pattern.grid.dtype == np.intp


def test_the_same_call_twice_gives_the_same_pattern_and_counts() -> None:
    pattern = drawn(["AAB.", "ABBA", "AAAA"], PAINTED)
    first = edit_pattern(pattern, MIXED)
    second = edit_pattern(pattern, MIXED)
    assert_equal_patterns(first.pattern, second.pattern)
    assert first.changed == second.changed
    assert all(count > 0 for count in first.changed)
