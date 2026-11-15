"""replace_threads: thread swaps applied in sequence, rebuilt with the model's counts.

Patterns are drawn with `cleanup_helpers.drawn`; the expected pattern of each case is drawn
again with the swapped threads in the legend, so `build_pattern` (merge, re-sort, skeins) is
the reference, never `replace_threads` itself.
"""

import numpy as np
import pytest
from cleanup_helpers import (
    BARE,
    FABRIC_COUNT,
    SHADES,
    assert_equal_patterns,
    counted,
    drawn,
    speckled,
)

from cross_stitch.pattern import EMPTY, Pattern, Replaced, replace_threads, skeins_needed
from cross_stitch.threads import Thread, dmc_thread


def _pairs(*codes: tuple[str, str]) -> list[tuple[Thread, Thread]]:
    return [(dmc_thread(source), dmc_thread(target)) for source, target in codes]


def _code_grid(pattern: Pattern) -> list[list[str | None]]:
    """The grid as thread codes, None for bare fabric."""
    return [
        [None if index == EMPTY else pattern.key[int(index)].thread.code for index in row]
        for row in pattern.grid
    ]


# Two threads: A 6 cells, B 3 cells, bare fabric in the last row.
TWO = ["AAAB", "AAAB", "B..."]
TWO_LEGEND = {"A": "310", "B": "Blanc"}

# Three threads: A 2 cells, B 5, C 4.
THREE = ["AABBBBB", "CCCC..."]
THREE_LEGEND = {"A": "310", "B": "Blanc", "C": "321"}

# Three threads of distinct counts, for the sequence cases: A 4, B 3, C 2.
SEQ = ["AAAB", "ABBC", "C..."]
SEQ_LEGEND = {"A": "310", "B": "321", "C": "Blanc"}


def test_no_pairs_gives_the_same_grid_and_key_and_ignores_nothing() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, [])
    assert isinstance(result, Replaced)
    assert_equal_patterns(result.pattern, pattern)
    assert not result.ignored


def test_a_thread_not_in_the_key_as_target_moves_its_cells_whole() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, _pairs(("310", "321")))
    assert counted(result.pattern) == [("321", 6), ("Blanc", 3)]
    assert_equal_patterns(result.pattern, drawn(TWO, {"A": "321", "B": "Blanc"}))
    assert _code_grid(result.pattern) == [
        ["321", "321", "321", "Blanc"],
        ["321", "321", "321", "Blanc"],
        ["Blanc", None, None, None],
    ]
    assert not result.ignored


def test_a_target_already_in_the_key_merges_the_entries() -> None:
    fabric_count = 18.0
    pattern = drawn(TWO, TWO_LEGEND, fabric_count)
    result = replace_threads(pattern, _pairs(("310", "Blanc")))
    assert counted(result.pattern) == [("Blanc", 9)]
    assert result.pattern.key[0].skeins == skeins_needed(9, fabric_count)
    assert result.pattern.total_stitches == pattern.total_stitches == 9
    assert result.pattern.fabric_count == fabric_count
    assert not result.ignored


def test_a_merge_re_sorts_the_key_by_stitches() -> None:
    pattern = drawn(THREE, THREE_LEGEND)
    assert counted(pattern) == [("Blanc", 5), ("321", 4), ("310", 2)]
    result = replace_threads(pattern, _pairs(("310", "321")))
    assert counted(result.pattern) == [("321", 6), ("Blanc", 5)]
    assert_equal_patterns(result.pattern, drawn(THREE, {"A": "321", "B": "Blanc", "C": "321"}))


def test_pairs_apply_in_sequence_so_a_later_pair_sees_an_earlier_target() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    result = replace_threads(pattern, _pairs(("310", "321"), ("321", "797")))
    assert_equal_patterns(result.pattern, drawn(SEQ, {"A": "797", "B": "797", "C": "Blanc"}))
    assert counted(result.pattern) == [("797", 7), ("Blanc", 2)]
    assert not result.ignored


def test_the_order_of_the_pairs_matters() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    result = replace_threads(pattern, _pairs(("321", "797"), ("310", "321")))
    assert_equal_patterns(result.pattern, drawn(SEQ, {"A": "321", "B": "797", "C": "Blanc"}))
    assert counted(result.pattern) == [("321", 4), ("797", 3), ("Blanc", 2)]
    assert not result.ignored


def test_a_from_thread_outside_the_key_changes_nothing_and_is_reported() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, _pairs(("797", "321")))
    assert_equal_patterns(result.pattern, pattern)
    assert result.ignored == (0,)


def test_a_from_thread_gone_by_an_earlier_pair_is_ignored() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, _pairs(("310", "321"), ("310", "797")))
    assert_equal_patterns(result.pattern, drawn(TWO, {"A": "321", "B": "Blanc"}))
    assert result.ignored == (1,)


def test_only_the_ignored_positions_are_reported_in_ascending_order() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(
        pattern, _pairs(("797", "321"), ("310", "321"), ("310", "3865"), ("Blanc", "797"))
    )
    assert result.ignored == (0, 2)
    assert counted(result.pattern) == [("321", 6), ("797", 3)]


def test_a_thread_replaced_by_itself_is_unchanged_and_not_ignored_when_present() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, _pairs(("310", "310")))
    assert_equal_patterns(result.pattern, pattern)
    assert not result.ignored


def test_a_thread_replaced_by_itself_is_ignored_when_absent() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, _pairs(("321", "321")))
    assert_equal_patterns(result.pattern, pattern)
    assert result.ignored == (0,)


@pytest.mark.parametrize(
    "codes",
    [
        [("310", "321")],
        [("310", "Blanc")],
        [("310", "321"), ("321", "Blanc"), ("Blanc", "797")],
        [("797", "310"), ("Blanc", "310")],
    ],
)
def test_bare_fabric_stays_bare_and_is_never_counted(codes: list[tuple[str, str]]) -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, _pairs(*codes))
    assert result.pattern.grid.shape == pattern.grid.shape
    assert np.array_equal(result.pattern.grid == EMPTY, pattern.grid == EMPTY)
    assert np.count_nonzero(result.pattern.grid == EMPTY) == sum(row.count(BARE) for row in TWO)
    assert result.pattern.total_stitches == pattern.total_stitches == 9


@pytest.mark.parametrize("seed", range(6))
def test_counts_add_up_after_any_sequence(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pattern = speckled(SHADES[:8], (12, 15), seed=seed)
    sequence = _pairs(
        *[
            (str(SHADES[rng.integers(len(SHADES))]), str(SHADES[rng.integers(len(SHADES))]))
            for _ in range(int(rng.integers(1, 8)))
        ]
    )
    result = replace_threads(pattern, sequence)
    after = result.pattern

    stitched = int(np.count_nonzero(after.grid != EMPTY))
    assert stitched == pattern.total_stitches
    assert sum(entry.stitches for entry in after.key) == after.total_stitches == stitched
    assert after.fabric_count == pattern.fabric_count == FABRIC_COUNT
    for index, entry in enumerate(after.key):
        assert entry.stitches == int(np.count_nonzero(after.grid == index)) >= 1
        assert entry.skeins == skeins_needed(entry.stitches, after.fabric_count)
    counts = [entry.stitches for entry in after.key]
    assert counts == sorted(counts, reverse=True)
    threads = [entry.thread for entry in after.key]
    assert len(set(threads)) == len(threads)
    allowed = {entry.thread for entry in pattern.key} | {target for _, target in sequence}
    assert set(threads) <= allowed
    assert list(result.ignored) == sorted(set(result.ignored))
    assert all(0 <= position < len(sequence) for position in result.ignored)


def test_the_input_pattern_is_not_modified() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    grid_before = pattern.grid.copy()
    key_before = pattern.key
    replace_threads(pattern, _pairs(("310", "321"), ("321", "797"), ("Blanc", "310")))
    assert np.array_equal(pattern.grid, grid_before)
    assert pattern.key == key_before
    assert not pattern.grid.flags.writeable


def test_the_result_grid_is_read_only() -> None:
    result = replace_threads(drawn(TWO, TWO_LEGEND), _pairs(("310", "321")))
    assert not result.pattern.grid.flags.writeable
    assert result.pattern.grid.dtype == np.intp


def test_the_same_input_twice_gives_the_same_pattern() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    pairs = _pairs(("321", "797"), ("310", "321"))
    assert_equal_patterns(
        replace_threads(pattern, pairs).pattern, replace_threads(pattern, pairs).pattern
    )


# --------------------------------------------------------------------------- removal


def test_removing_a_thread_leaves_its_cells_bare_and_the_rest_as_they_were() -> None:
    pattern = drawn(THREE, THREE_LEGEND)
    result = replace_threads(pattern, [(dmc_thread("321"), None)])

    expected = drawn(["AABBBBB", "......."], {"A": "310", "B": "Blanc"})
    assert_equal_patterns(result.pattern, expected)
    assert result.pattern.total_stitches == pattern.total_stitches - 4
    assert not result.ignored


def test_a_removed_thread_is_no_longer_there_for_a_later_pair() -> None:
    pattern = drawn(THREE, THREE_LEGEND)
    pairs = [(dmc_thread("321"), None), (dmc_thread("321"), dmc_thread("797"))]

    result = replace_threads(pattern, pairs)

    assert result.ignored == (1,)
    assert counted(result.pattern) == [("Blanc", 5), ("310", 2)]


def test_a_thread_moved_onto_a_removed_one_is_removed_with_it_only_if_it_comes_first() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    merged_then_removed = [(dmc_thread("310"), dmc_thread("321")), (dmc_thread("321"), None)]
    removed_then_moved = [(dmc_thread("321"), None), (dmc_thread("310"), dmc_thread("321"))]

    assert counted(replace_threads(pattern, merged_then_removed).pattern) == [("Blanc", 2)]
    assert counted(replace_threads(pattern, removed_then_moved).pattern) == [
        ("321", 4),
        ("Blanc", 2),
    ]


def test_removing_every_thread_leaves_bare_fabric_and_an_empty_key() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = replace_threads(pattern, [(dmc_thread("310"), None), (dmc_thread("Blanc"), None)])

    assert not result.pattern.key
    assert np.all(result.pattern.grid == EMPTY)
    assert result.pattern.grid.shape == pattern.grid.shape


def test_a_removal_keeps_the_skeins_derived_from_the_counts() -> None:
    pattern = speckled(SHADES[:6], (20, 30), seed=4)
    result = replace_threads(pattern, [(pattern.key[0].thread, None)]).pattern

    for entry in result.key:
        assert entry.skeins == skeins_needed(entry.stitches, FABRIC_COUNT)
    assert pattern.key[0].thread not in [entry.thread for entry in result.key]
