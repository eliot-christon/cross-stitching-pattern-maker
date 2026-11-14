"""Confetti cleanup: clusters of at most `max_size` cells merged into their surroundings.

Patterns are drawn as rows of letters, each letter a thread of the legend and "." bare
fabric, and built with `build_pattern`. A cluster is a set of same-entry cells joined
through their 8 neighbours. Expected grids are written out cell for cell. Where a case
depends on a CIEDE2000 order or a key order, the test asserts that premise first (the
distances with `delta_e_2000`), so a choice of threads that stops meeting it fails loudly
instead of passing for the wrong reason. The post-condition is checked by a breadth-first
search written here, never by the code under test.
"""

import itertools
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence

import numpy as np
import pytest

from cross_stitch.colour import delta_e_2000, srgb_to_lab
from cross_stitch.pattern import EMPTY, Pattern, build_pattern, isolated_stitches, remove_confetti
from cross_stitch.threads import Thread, dmc_thread

type Cell = tuple[int, int]
type Legend = Mapping[str, Thread]
type Make = Callable[[], Pattern]

BARE = "."
FABRIC = 16.0


# ------------------------------------------------------------------------------ drawing


def _dmc(**codes: str) -> dict[str, Thread]:
    """A legend of DMC threads, letter -> code."""
    return {letter: dmc_thread(code) for letter, code in codes.items()}


def _build(rows: Sequence[str], legend: Legend) -> Pattern:
    """The pattern drawn by `rows`: each letter the legend's thread, "." bare fabric."""
    index = {BARE: EMPTY} | {letter: position for position, letter in enumerate(legend)}
    cells = np.array([[index[char] for char in row] for row in rows], dtype=np.intp)
    return build_pattern(cells, list(legend.values()), FABRIC)


def _drawn(pattern: Pattern, legend: Legend) -> list[str]:
    """The grid as rows of letters, the inverse of `_build` for the same legend."""
    letter_of = {thread: letter for letter, thread in legend.items()}
    # EMPTY is -1, so bare cells pick the last symbol.
    symbols = np.array([*(letter_of[entry.thread] for entry in pattern.key), BARE])
    return ["".join(row) for row in symbols[pattern.grid].tolist()]


def _field(shape: Cell, marks: Mapping[Cell, str]) -> list[str]:
    """A field of A cells of `shape` (height, width), with the letters of `marks` placed
    at their (row, column)."""
    height, width = shape
    return ["".join(marks.get((row, col), "A") for col in range(width)) for row in range(height)]


def _counts(pattern: Pattern) -> list[tuple[str, int]]:
    """The key as (code, stitches), in key order."""
    return [(entry.thread.code, entry.stitches) for entry in pattern.key]


def _code_at(pattern: Pattern, cell: Cell) -> str:
    return pattern.key[int(pattern.grid[cell])].thread.code


def _delta(first: str, second: str) -> tuple[float, float]:
    """CIEDE2000 between two DMC threads, measured both ways round."""
    lab = {code: srgb_to_lab(dmc_thread(code).rgb) for code in (first, second)}
    there = float(delta_e_2000(lab[first], lab[second]))
    back = float(delta_e_2000(lab[second], lab[first]))
    return there, back


def _assert_nearer(target: str, *, near: str, far: str) -> None:
    """The premise of a case: DMC `near` is closer to `target` than `far` is, in CIEDE2000,
    whichever way round each distance is measured."""
    assert max(_delta(target, near)) < min(_delta(target, far)), (target, near, far)


# ------------------------------------------------------------------- independent checks


def _around(cell: Cell, shape: Cell) -> Iterator[Cell]:
    """The 8-neighbours of `cell` that lie inside a grid of `shape`."""
    for d_row, d_col in itertools.product((-1, 0, 1), repeat=2):
        row, col = cell[0] + d_row, cell[1] + d_col
        if (d_row, d_col) != (0, 0) and 0 <= row < shape[0] and 0 <= col < shape[1]:
            yield row, col


def _clusters(pattern: Pattern) -> list[list[Cell]]:
    """Every cluster of the grid (same-entry stitched cells joined through their 8
    neighbours), found by breadth-first search from each cell in reading order."""
    grid: list[list[int]] = pattern.grid.tolist()
    shape = (pattern.height, pattern.width)
    seen: set[Cell] = set()
    clusters: list[list[Cell]] = []
    for start in itertools.product(range(shape[0]), range(shape[1])):
        if start in seen or grid[start[0]][start[1]] == EMPTY:
            continue
        entry = grid[start[0]][start[1]]
        seen.add(start)
        members: list[Cell] = []
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            members.append(cell)
            for other in _around(cell, shape):
                if other not in seen and grid[other[0]][other[1]] == entry:
                    seen.add(other)
                    queue.append(other)
        clusters.append(members)
    return clusters


def _stitched_around(pattern: Pattern, cluster: Sequence[Cell]) -> set[Cell]:
    """The cluster's neighbours: stitched cells outside it next to one of its cells."""
    inside = set(cluster)
    shape = (pattern.height, pattern.width)
    return {
        other
        for cell in cluster
        for other in _around(cell, shape)
        if other not in inside and pattern.grid[other] != EMPTY
    }


def _assert_settled(pattern: Pattern, max_size: int) -> None:
    """The contract's post-condition: no cluster of at most `max_size` cells has a stitched
    neighbour (which is then necessarily of another entry)."""
    for cluster in _clusters(pattern):
        if len(cluster) <= max_size:
            assert not _stitched_around(pattern, cluster), cluster


def _assert_well_formed(result: Pattern, original: Pattern) -> None:
    """What cleanup keeps: shape, fabric, the bare-fabric cells and the total; threads taken
    only from the input's key; and a key exactly as `build_pattern` derives it from the
    result's own grid (counts, skeins, order, no unused or doubled entry)."""
    assert result.grid.shape == original.grid.shape
    assert result.grid.dtype == np.intp
    assert result.fabric_count == original.fabric_count
    assert (result.grid == EMPTY).tolist() == (original.grid == EMPTY).tolist()
    assert result.total_stitches == original.total_stitches
    threads = [entry.thread for entry in result.key]
    assert set(threads) <= {entry.thread for entry in original.key}
    rebuilt = build_pattern(result.grid, threads, result.fabric_count)
    assert rebuilt.grid.tolist() == result.grid.tolist()
    assert rebuilt.key == result.key
    assert not result.grid.flags.writeable


def _same(first: Pattern, second: Pattern) -> None:
    assert first.grid.tolist() == second.grid.tolist()
    assert first.grid.dtype == second.grid.dtype
    assert (first.fabric_count, first.key) == (second.fabric_count, second.key)


# ----------------------------------------------------------------------------- legends

# A royal blue, B red, C bright red (near B), D green: C is nearer to B than A is.
BLUE = _dmc(A="797", B="321", C="666", D="699")
# The same with A and C swapped: A is nearer to B than C is.
RED = _dmc(A="666", B="321", C="797", D="699")
# Two lone stitches: C (321) comes before B (797) in the key, by code order.
LONE = _dmc(B="797", C="321")

GREY = (120, 120, 120)


def _greys(first: str, second: str) -> dict[str, Thread]:
    """A and C two test threads of one grey (so exactly as far from B), B a test red."""
    return {
        "A": Thread(first, f"test grey {first}", GREY),
        "B": Thread("9", "test red", (200, 40, 40)),
        "C": Thread(second, f"test grey {second}", GREY),
    }


# ----------------------------------------------------------------------------- layouts

# B at (2, 2) with 5 A and 3 C neighbours; A 12 cells, C 17.
VOTE_ROWS = ("AAAACC", "AAAACC", "AABCCC", "AACCCC", "CCCCCC")

# B at (2, 2) with 4 A and 4 C neighbours; A 14 cells, C 10.
TIE_ROWS = ("AAAAA", "AAACC", "AABCC", "AACCC", "AACCC")

# The same neighbourhood with A 12 cells and C 12.
EVEN_TIE_ROWS = ("AAACC", "AAACC", "AABCC", "AACCC", "AACCC")

# A B domino at (2, 2)-(2, 3). Its 10 neighbour cells: 4 A, each next to both B cells, and
# 6 C, each next to one. A is one cluster of 22, C two columns of 3.
COUNT_ONCE_ROWS = ("AAAAAA", "ACAACA", "ACBBCA", "ACAACA", "AAAAAA")

# B at (2, 2) and D at (2, 3), both lone. Around B: 4 A, 3 C and D. Around D: 1 A, 6 C and
# B. D always becomes C; B sees 4 A to 3 C if handled first, 4 A to 4 C (a tie that C, the
# nearer to B, wins) if D has already become C.
ORDER_ROWS = ("AAACCC", "AAACCC", "AABDCC", "AACCCC", "AACCCC")

# A B domino at (2, 2)-(2, 3), first in reading order, and a lone D at (3, 4). Around the
# domino: 5 A, 4 C and D. Around D: 7 C and one B. D, the smaller, is handled first and
# becomes C; the domino then sees 5 A to 5 C, a tie that C, the nearer to B, wins.
SIZE_ROWS = ("AAAACC", "AAAACC", "AABBCC", "AACCDC", "AACCCC")

# A 6 cells, owning the first cell; B 4 cells.
SIZE_PAIR = ("AAABB", "AAABB")

NOISY_CODES = ("310", "Blanc", "321", "797", "699", "3799")


# ---------------------------------------------------------------------------- factories


def _lone_in_field() -> Pattern:
    return _build(_field((5, 5), {(2, 2): "B"}), BLUE)


def _checkerboard() -> Pattern:
    return _build(["ABABAB", "BABABA"] * 3, BLUE)


def _bare_only() -> Pattern:
    return _build(["...", "..."], BLUE)


def _one_stitch() -> Pattern:
    return _build(["B"], BLUE)


def _lone_on_bare() -> Pattern:
    return _build(["...", ".B.", "..."], BLUE)


def _noisy(seed: int = 5) -> Pattern:
    """40 x 40: 2 x 2 blocks of bare fabric or one of six threads, then about a fifth of the
    cells redrawn at random, so the grid holds large clusters and confetti side by side."""
    rng = np.random.default_rng(seed)
    coarse = rng.integers(EMPTY, len(NOISY_CODES), size=(20, 20))
    blocks = coarse.repeat(2, axis=0).repeat(2, axis=1)
    redrawn = rng.integers(EMPTY, len(NOISY_CODES), size=blocks.shape)
    cells = np.where(rng.random(blocks.shape) < 0.2, redrawn, blocks).astype(np.intp)
    return build_pattern(cells, [dmc_thread(code) for code in NOISY_CODES], FABRIC)


# --------------------------------------------------------------------- isolated stitches


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (["B"], 1),
        (["AA"], 0),
        (["AB"], 2),
        (["AAB"], 1),
        (["A.A"], 2),
        (["A.", ".A"], 0),
        ([".A", "A."], 0),
        (["A..", "..A"], 2),
        (["AB", "CD"], 4),
        (["ABA", "BAB"], 0),
        (["...", ".B.", "..."], 1),
        (["....", "...."], 0),
        (_field((5, 5), {(2, 2): "B"}), 1),
        (_field((6, 6), {(2, 2): "B", (2, 3): "B"}), 0),
    ],
    ids=[
        "1x1",
        "pair",
        "two-entries",
        "at-the-edge",
        "split-by-bare",
        "diagonal-down",
        "diagonal-up",
        "far-apart",
        "four-entries",
        "zigzag",
        "on-bare-fabric",
        "all-bare",
        "lone-in-field",
        "domino-in-field",
    ],
)
def test_isolated_stitches_counts_stitched_cells_with_no_same_entry_neighbour(
    rows: list[str], expected: int
) -> None:
    count = isolated_stitches(_build(rows, BLUE))
    assert isinstance(count, int)
    assert count == expected


def test_isolated_stitches_counts_the_single_cell_clusters_of_a_noisy_grid() -> None:
    pattern = _noisy()
    count = isolated_stitches(pattern)
    assert count > 0
    assert count == sum(1 for cluster in _clusters(pattern) if len(cluster) == 1)


# ------------------------------------------------------------------------------ max size 0


@pytest.mark.parametrize(
    "make",
    [_lone_in_field, _checkerboard, _noisy, _bare_only, _one_stitch, _lone_on_bare],
    ids=["lone-in-field", "checkerboard", "noisy", "all-bare", "1x1", "lone-on-bare"],
)
def test_max_size_zero_returns_a_pattern_equal_to_the_input(make: Make) -> None:
    _same(remove_confetti(make(), max_size=0), make())


# ---------------------------------------------------------------------- cluster sizes


def test_a_lone_stitch_in_a_field_takes_the_field_thread() -> None:
    original = _lone_in_field()
    assert _counts(original) == [("797", 24), ("321", 1)]
    assert isolated_stitches(original) == 1

    result = remove_confetti(original, max_size=1)

    assert _drawn(result, BLUE) == ["AAAAA"] * 5
    assert _counts(result) == [("797", 25)]
    assert isolated_stitches(result) == 0
    _assert_well_formed(result, original)


@pytest.mark.parametrize(("max_size", "removed"), [(1, False), (2, True), (3, True), (36, True)])
@pytest.mark.parametrize(
    "cells", [((2, 2), (2, 3)), ((2, 2), (3, 2))], ids=["horizontal", "vertical"]
)
def test_a_domino_is_removed_from_max_size_two(
    cells: tuple[Cell, Cell], max_size: int, removed: bool
) -> None:
    rows = _field((6, 6), dict.fromkeys(cells, "B"))
    original = _build(rows, BLUE)
    assert _counts(original) == [("797", 34), ("321", 2)]

    result = remove_confetti(original, max_size=max_size)

    assert _drawn(result, BLUE) == (_field((6, 6), {}) if removed else rows)
    _assert_well_formed(result, original)
    _assert_settled(result, max_size)


@pytest.mark.parametrize("cells", [((1, 1), (2, 2)), ((1, 2), (2, 1))], ids=["down", "up"])
def test_two_stitches_touching_diagonally_are_one_cluster_of_two(
    cells: tuple[Cell, Cell],
) -> None:
    rows = _field((5, 5), dict.fromkeys(cells, "B"))
    original = _build(rows, BLUE)
    assert isolated_stitches(original) == 0

    _same(remove_confetti(original, max_size=1), _build(rows, BLUE))
    assert _drawn(remove_confetti(original, max_size=2), BLUE) == ["AAAAA"] * 5


@pytest.mark.parametrize("max_size", [1, 2, 17])
def test_a_checkerboard_is_two_clusters_joined_through_the_diagonals(max_size: int) -> None:
    original = _checkerboard()
    assert _counts(original) == [("321", 18), ("797", 18)]
    assert isolated_stitches(original) == 0
    _same(remove_confetti(original, max_size=max_size), _checkerboard())


def test_a_checkerboard_at_max_size_18_merges_the_cluster_first_in_reading_order() -> None:
    # Both clusters hold 18 cells. A owns the first cell (0, 0), so it is handled first and
    # takes B's thread, although B (321) comes first in the key by code order.
    original = _checkerboard()
    result = remove_confetti(original, max_size=18)
    assert _counts(result) == [("321", 36)]
    assert _drawn(result, BLUE) == ["BBBBBB"] * 6
    _assert_well_formed(result, original)


@pytest.mark.parametrize("rows", [["AABAA"], ["A", "A", "B", "A", "A"]], ids=["row", "column"])
def test_a_lone_stitch_in_a_one_cell_wide_grid_takes_its_neighbours_thread(
    rows: list[str],
) -> None:
    result = remove_confetti(_build(rows, BLUE), max_size=1)
    assert _drawn(result, BLUE) == [row.replace("B", "A") for row in rows]


@pytest.mark.parametrize(
    "corner",
    [(0, 0), (0, 4), (3, 0), (3, 4)],
    ids=["top-left", "top-right", "bottom-left", "bottom-right"],
)
def test_a_lone_stitch_in_a_corner_takes_its_three_neighbours_thread(corner: Cell) -> None:
    original = _build(_field((4, 5), {corner: "B"}), BLUE)
    result = remove_confetti(original, max_size=1)
    assert _drawn(result, BLUE) == ["AAAAA"] * 4
    assert _counts(result) == [("797", 20)]
    _assert_well_formed(result, original)


# ---------------------------------------------------------------------- neighbour vote


def test_a_cluster_takes_the_entry_most_of_its_neighbours_hold() -> None:
    # 5 A and 3 C around B. C is nearer to B and first in the key, so only the vote gives A.
    _assert_nearer("321", near="666", far="797")
    original = _build(VOTE_ROWS, BLUE)
    assert _counts(original) == [("666", 17), ("797", 12), ("321", 1)]

    result = remove_confetti(original, max_size=1)

    assert _drawn(result, BLUE) == [row.replace("B", "A") for row in VOTE_ROWS]
    assert _counts(result) == [("666", 17), ("797", 13)]
    _assert_well_formed(result, original)


def test_each_neighbour_cell_is_counted_once_for_the_whole_cluster() -> None:
    # Counted once per cell, C wins 6 to 4; counted once per adjacency, A would win 8 to 6.
    # A is also nearer to B and first in the key, so only the per-cell vote gives C.
    _assert_nearer("321", near="666", far="797")
    original = _build(COUNT_ONCE_ROWS, RED)
    assert _counts(original) == [("666", 22), ("797", 6), ("321", 2)]

    result = remove_confetti(original, max_size=2)

    assert _drawn(result, RED) == [*COUNT_ONCE_ROWS[:2], "ACCCCA", *COUNT_ONCE_ROWS[3:]]
    assert _counts(result) == [("666", 22), ("797", 8)]
    _assert_well_formed(result, original)


@pytest.mark.parametrize(
    ("legend", "winner"),
    [(BLUE, "C"), (RED, "A")],
    ids=["nearer-is-later-in-key", "nearer-is-first-in-key"],
)
def test_a_tied_vote_goes_to_the_entry_nearest_the_cluster_thread(
    legend: Legend, winner: str
) -> None:
    _assert_nearer("321", near="666", far="797")
    assert legend[winner].code == "666"
    original = _build(TIE_ROWS, legend)
    assert _counts(original) == [(legend["A"].code, 14), (legend["C"].code, 10), ("321", 1)]

    result = remove_confetti(original, max_size=1)

    assert _drawn(result, legend) == [row.replace("B", winner) for row in TIE_ROWS]
    _assert_well_formed(result, original)


@pytest.mark.parametrize(
    ("rows", "codes", "winner"),
    [
        (TIE_ROWS, ("1", "2"), "1"),
        (TIE_ROWS, ("2", "1"), "2"),
        (EVEN_TIE_ROWS, ("1", "2"), "1"),
        (EVEN_TIE_ROWS, ("2", "1"), "1"),
    ],
    ids=[
        "more-stitches-lower-code",
        "more-stitches-higher-code",
        "equal-stitches-a-lower-code",
        "equal-stitches-c-lower-code",
    ],
)
def test_a_tie_at_equal_distance_goes_to_the_earlier_key_entry(
    rows: Sequence[str], codes: tuple[str, str], winner: str
) -> None:
    legend = _greys(*codes)
    original = _build(rows, legend)
    assert len(original.key) == 3
    assert _counts(original)[0][0] == winner

    result = remove_confetti(original, max_size=1)

    letter = "A" if codes[0] == winner else "C"
    assert _drawn(result, legend) == [row.replace("B", letter) for row in rows]
    _assert_well_formed(result, original)


# --------------------------------------------------------------------------- the order


@pytest.mark.parametrize(
    ("rows", "expected", "code"),
    [
        (["....", ".BC.", "...."], ["....", ".CC.", "...."], "321"),
        (["....", ".CB.", "...."], ["....", ".BB.", "...."], "797"),
        (["....", "..B.", ".C..", "...."], ["....", "..C.", ".C..", "...."], "321"),
    ],
    ids=["b-left", "c-left", "b-row-above-c-column-before"],
)
def test_of_two_lone_stitches_side_by_side_the_first_in_reading_order_moves(
    rows: list[str], expected: list[str], code: str
) -> None:
    # Each is the other's only neighbour. The first handled takes the other's thread; the
    # other then sits in a cluster of 2, above max_size, and stays.
    original = _build(rows, LONE)
    assert _counts(original) == [("321", 1), ("797", 1)]

    result = remove_confetti(original, max_size=1)

    assert _drawn(result, LONE) == expected
    assert _counts(result) == [(code, 2)]
    _assert_well_formed(result, original)


def test_two_lone_stitches_side_by_side_in_a_field_both_take_the_field_thread() -> None:
    original = _build(_field((5, 5), {(2, 2): "B", (2, 3): "C"}), BLUE)
    assert isolated_stitches(original) == 2

    result = remove_confetti(original, max_size=1)

    assert _drawn(result, BLUE) == ["AAAAA"] * 5
    assert _counts(result) == [("797", 25)]
    assert isolated_stitches(result) == 0


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (ORDER_ROWS, ["AAACCC", "AAACCC", "AAACCC", "AACCCC", "AACCCC"]),
        (
            [row[::-1] for row in ORDER_ROWS],
            ["CCCAAA", "CCCAAA", "CCCCAA", "CCCCAA", "CCCCAA"],
        ),
    ],
    ids=["b-first", "d-first"],
)
def test_each_cluster_is_voted_on_the_grid_as_earlier_merges_left_it(
    rows: Sequence[str], expected: list[str]
) -> None:
    _assert_nearer("321", near="666", far="797")
    original = _build(rows, BLUE)
    assert _counts(original) == [("666", 16), ("797", 12), ("321", 1), ("699", 1)]

    result = remove_confetti(original, max_size=1)

    assert _drawn(result, BLUE) == expected
    _assert_well_formed(result, original)


@pytest.mark.parametrize(
    ("max_size", "expected"),
    [(3, list(SIZE_PAIR)), (4, ["AAAAA"] * 2), (6, ["AAAAA"] * 2), (1000, ["AAAAA"] * 2)],
    ids=["both-above", "b-only", "both-under", "far-above"],
)
def test_the_smaller_cluster_is_handled_first(max_size: int, expected: list[str]) -> None:
    # A owns the first cell and comes first in the key, but B is smaller: handled first, B
    # takes A's thread and A is left with no neighbour. Handling A first would give all B.
    original = _build(SIZE_PAIR, BLUE)
    assert _counts(original) == [("797", 6), ("321", 4)]

    result = remove_confetti(original, max_size=max_size)

    assert _drawn(result, BLUE) == expected
    _assert_well_formed(result, original)
    _assert_settled(result, max_size)


def test_a_lone_stitch_is_handled_before_a_domino_that_comes_first_in_reading_order() -> None:
    # Handling the domino first would give it A (5 to 4) and leave row 2 as it was.
    _assert_nearer("321", near="666", far="797")
    original = _build(SIZE_ROWS, BLUE)
    assert _counts(original) == [("797", 14), ("666", 13), ("321", 2), ("699", 1)]

    result = remove_confetti(original, max_size=2)

    assert _drawn(result, BLUE) == ["AAAACC", "AAAACC", "AACCCC", "AACCCC", "AACCCC"]
    assert _counts(result) == [("666", 16), ("797", 14)]
    _assert_well_formed(result, original)


# --------------------------------------------------------------------------- bare fabric


@pytest.mark.parametrize("max_size", [1, 2, 8])
@pytest.mark.parametrize(
    ("rows", "isolated"),
    [
        (["B"], 1),
        (["...", ".B.", "..."], 1),
        (["B..", "...", "..A"], 2),
        (["A....", ".....", "..BB.", "....."], 1),
    ],
    ids=["1x1", "lone-on-bare", "two-lone-apart", "domino-and-lone-on-bare"],
)
def test_a_cluster_with_no_stitched_neighbour_stays(
    rows: list[str], isolated: int, max_size: int
) -> None:
    original = _build(rows, BLUE)
    assert isolated_stitches(original) == isolated

    result = remove_confetti(original, max_size=max_size)

    assert _drawn(result, BLUE) == rows
    assert isolated_stitches(result) == isolated


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (["...A", "ABA.", "AAAA"], ["...A", "AAA.", "AAAA"]),
        (["...", ".BA", ".AA"], ["...", ".AA", ".AA"]),
    ],
    ids=["3-bare-5-a", "5-bare-3-a"],
)
def test_bare_fabric_is_never_a_neighbour_and_never_filled(
    rows: list[str], expected: list[str]
) -> None:
    original = _build(rows, BLUE)
    result = remove_confetti(original, max_size=1)
    assert _drawn(result, BLUE) == expected
    assert np.all(result.grid[original.grid == EMPTY] == EMPTY)
    _assert_well_formed(result, original)


@pytest.mark.parametrize("max_size", [0, 1, 10])
def test_a_pattern_with_no_stitch_comes_back_empty(max_size: int) -> None:
    result = remove_confetti(_bare_only(), max_size=max_size)
    assert (result.key, result.total_stitches) == ((), 0)
    assert result.grid.tolist() == [[EMPTY] * 3] * 2
    assert isolated_stitches(result) == 0


# ---------------------------------------------------------------------- post-conditions

NOISY_SIZES = [1, 2, 4]


@pytest.mark.parametrize("max_size", NOISY_SIZES)
def test_a_noisy_grid_is_settled_with_its_outline_and_total_kept(max_size: int) -> None:
    original = _noisy()
    assert len(original.key) == 6
    assert np.any(original.grid == EMPTY)
    stranded = [
        cluster
        for cluster in _clusters(original)
        if len(cluster) == 1 and not _stitched_around(original, cluster)
    ]

    result = remove_confetti(original, max_size=max_size)

    _assert_settled(result, max_size)
    _assert_well_formed(result, original)
    # Every isolated stitch left is one that had no stitched neighbour to begin with.
    assert isolated_stitches(result) == len(stranded)
    assert isolated_stitches(result) < isolated_stitches(original)


@pytest.mark.parametrize("max_size", NOISY_SIZES)
def test_clusters_above_max_size_or_without_neighbours_keep_every_cell(max_size: int) -> None:
    original = _noisy()
    kept = [
        cell
        for cluster in _clusters(original)
        if len(cluster) > max_size or not _stitched_around(original, cluster)
        for cell in cluster
    ]
    assert kept

    result = remove_confetti(original, max_size=max_size)

    assert [_code_at(result, cell) for cell in kept] == [_code_at(original, cell) for cell in kept]


# ------------------------------------------------------------------------ invalid input


@pytest.mark.parametrize("max_size", [-1, -10])
@pytest.mark.parametrize("make", [_lone_in_field, _bare_only], ids=["lone-in-field", "all-bare"])
def test_a_negative_max_size_raises_value_error(make: Make, max_size: int) -> None:
    with pytest.raises(ValueError, match="max size"):
        remove_confetti(make(), max_size=max_size)


# ------------------------------------------------------------- purity and determinism


def test_cleanup_leaves_the_input_pattern_untouched() -> None:
    original = _noisy()
    grid = original.grid.copy()
    key = original.key

    result = remove_confetti(original, max_size=2)
    isolated_stitches(original)

    assert result.grid.tolist() != grid.tolist()
    assert original.grid.tolist() == grid.tolist()
    assert original.key == key
    assert not original.grid.flags.writeable


def test_the_same_cleanup_twice_gives_equal_patterns() -> None:
    original = _noisy()
    _same(remove_confetti(original, max_size=2), remove_confetti(original, max_size=2))


def test_equal_inputs_built_separately_are_cleaned_the_same_way() -> None:
    _same(remove_confetti(_noisy(), max_size=2), remove_confetti(_noisy(), max_size=2))


# ------------------------------------------------------------------- reference cleanup


def _reference_cleanup(pattern: Pattern, max_size: int) -> Pattern:
    """The ticket's rule read literally, slowly: find every cluster of the grid as it stands,
    merge the smallest one with a neighbour (ties: first cell in reading order) by the vote,
    and start again until none is left."""
    grid = pattern.grid.copy()
    lab = srgb_to_lab([entry.thread.rgb for entry in pattern.key])
    while True:
        current = Pattern(grid=grid, key=pattern.key, fabric_count=pattern.fabric_count)
        candidates = [
            cluster
            for cluster in _clusters(current)
            if len(cluster) <= max_size and _stitched_around(current, cluster)
        ]
        if not candidates:
            break
        cluster = min(candidates, key=lambda cells: (len(cells), min(cells)))
        own = int(grid[cluster[0]])
        votes: dict[int, int] = {}
        for cell in _stitched_around(current, cluster):
            votes[int(grid[cell])] = votes.get(int(grid[cell]), 0) + 1
        target = min(
            votes,
            key=lambda entry: (-votes[entry], float(delta_e_2000(lab[own], lab[entry])), entry),
        )
        for cell in cluster:
            grid[cell] = target
    return build_pattern(grid, [entry.thread for entry in pattern.key], pattern.fabric_count)


@pytest.mark.parametrize("max_size", [1, 2, 3, 5])
@pytest.mark.parametrize("seed", range(8))
def test_cleanup_matches_the_rule_applied_one_cluster_at_a_time(seed: int, max_size: int) -> None:
    rng = np.random.default_rng(seed)
    cells = rng.integers(EMPTY, 5, size=(9, 11)).astype(np.intp)
    original = build_pattern(cells, [dmc_thread(code) for code in NOISY_CODES[:5]], FABRIC)

    _same(remove_confetti(original, max_size=max_size), _reference_cleanup(original, max_size))
