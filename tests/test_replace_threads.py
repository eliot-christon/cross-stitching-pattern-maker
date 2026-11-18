"""edit_pattern with `Replace` entries: thread swaps applied in sequence, rebuilt with the
model's counts, each entry counting the stitches it moved.

Patterns are drawn with `cleanup_helpers.drawn`; the expected pattern of each case is drawn
again with the swapped threads in the legend, so `build_pattern` (merge, re-sort, skeins) is
the reference, never `edit_pattern` itself. An entry that did nothing (its `old` thread is
not in the pattern at that point, or `old` is `new`) counts 0.
"""

import numpy as np
import pytest
from cleanup_helpers import (
    BARE,
    FABRIC_COUNT,
    SHADES,
    assert_counts_add_up,
    assert_equal_patterns,
    code_grid,
    counted,
    drawn,
    speckled,
)

from cross_stitch.pattern import (
    EMPTY,
    Edited,
    Replace,
    edit_pattern,
    skeins_needed,
)
from cross_stitch.threads import dmc_thread


def _replaces(*codes: tuple[str, str]) -> list[Replace]:
    return [Replace(old=dmc_thread(source), new=dmc_thread(target)) for source, target in codes]


def _removal(code: str) -> Replace:
    return Replace(old=dmc_thread(code), new=None)


def _did_nothing(result: Edited) -> list[int]:
    """The positions of the entries that changed no cell."""
    return [position for position, count in enumerate(result.changed) if count == 0]


# Two threads: A 6 cells, B 3 cells, bare fabric in the last row.
TWO = ["AAAB", "AAAB", "B..."]
TWO_LEGEND = {"A": "310", "B": "Blanc"}

# Three threads: A 2 cells, B 5, C 4.
THREE = ["AABBBBB", "CCCC..."]
THREE_LEGEND = {"A": "310", "B": "Blanc", "C": "321"}

# Three threads of distinct counts, for the sequence cases: A 4, B 3, C 2.
SEQ = ["AAAB", "ABBC", "C..."]
SEQ_LEGEND = {"A": "310", "B": "321", "C": "Blanc"}


def test_a_thread_not_in_the_key_as_target_moves_its_cells_whole() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(pattern, _replaces(("310", "321")))
    assert counted(result.pattern) == [("321", 6), ("Blanc", 3)]
    assert_equal_patterns(result.pattern, drawn(TWO, {"A": "321", "B": "Blanc"}))
    assert code_grid(result.pattern) == [
        ["321", "321", "321", "Blanc"],
        ["321", "321", "321", "Blanc"],
        ["Blanc", None, None, None],
    ]
    assert result.changed == (6,)


def test_a_target_already_in_the_key_merges_the_entries() -> None:
    fabric_count = 18.0
    pattern = drawn(TWO, TWO_LEGEND, fabric_count)
    result = edit_pattern(pattern, _replaces(("310", "Blanc")))
    assert counted(result.pattern) == [("Blanc", 9)]
    assert result.pattern.key[0].skeins == skeins_needed(9, fabric_count)
    assert result.pattern.total_stitches == pattern.total_stitches == 9
    assert result.pattern.fabric_count == fabric_count
    assert result.changed == (6,)


def test_a_merge_re_sorts_the_key_by_stitches() -> None:
    pattern = drawn(THREE, THREE_LEGEND)
    assert counted(pattern) == [("Blanc", 5), ("321", 4), ("310", 2)]
    result = edit_pattern(pattern, _replaces(("310", "321")))
    assert counted(result.pattern) == [("321", 6), ("Blanc", 5)]
    assert_equal_patterns(result.pattern, drawn(THREE, {"A": "321", "B": "Blanc", "C": "321"}))
    assert result.changed == (2,)


def test_entries_apply_in_sequence_so_a_later_one_sees_an_earlier_target() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    result = edit_pattern(pattern, _replaces(("310", "321"), ("321", "797")))
    assert_equal_patterns(result.pattern, drawn(SEQ, {"A": "797", "B": "797", "C": "Blanc"}))
    assert counted(result.pattern) == [("797", 7), ("Blanc", 2)]
    # The second entry moves the 3 cells of 321 and the 4 the first one moved onto it.
    assert result.changed == (4, 7)


def test_the_order_of_the_entries_matters() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    result = edit_pattern(pattern, _replaces(("321", "797"), ("310", "321")))
    assert_equal_patterns(result.pattern, drawn(SEQ, {"A": "321", "B": "797", "C": "Blanc"}))
    assert counted(result.pattern) == [("321", 4), ("797", 3), ("Blanc", 2)]
    assert result.changed == (3, 4)


def test_an_old_thread_outside_the_key_changes_nothing_and_counts_zero() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(pattern, _replaces(("797", "321")))
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


def test_an_old_thread_gone_by_an_earlier_entry_counts_zero() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(pattern, _replaces(("310", "321"), ("310", "797")))
    assert_equal_patterns(result.pattern, drawn(TWO, {"A": "321", "B": "Blanc"}))
    assert result.changed == (6, 0)


def test_every_entry_has_its_count_in_order_and_only_those_that_did_nothing_count_zero() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(
        pattern, _replaces(("797", "321"), ("310", "321"), ("310", "3865"), ("Blanc", "797"))
    )
    assert result.changed == (0, 6, 0, 3)
    assert _did_nothing(result) == [0, 2]
    assert counted(result.pattern) == [("321", 6), ("797", 3)]


def test_a_thread_replaced_by_itself_is_unchanged_and_counts_zero_when_present() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(pattern, _replaces(("310", "310")))
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


def test_a_thread_replaced_by_itself_counts_zero_when_absent() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(pattern, _replaces(("321", "321")))
    assert_equal_patterns(result.pattern, pattern)
    assert result.changed == (0,)


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
    result = edit_pattern(pattern, _replaces(*codes))
    assert result.pattern.grid.shape == pattern.grid.shape
    assert np.array_equal(result.pattern.grid == EMPTY, pattern.grid == EMPTY)
    assert np.count_nonzero(result.pattern.grid == EMPTY) == sum(row.count(BARE) for row in TWO)
    assert result.pattern.total_stitches == pattern.total_stitches == 9


@pytest.mark.parametrize("seed", range(6))
def test_counts_add_up_after_any_sequence(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pattern = speckled(SHADES[:8], (12, 15), seed=seed)
    sequence = _replaces(
        *[
            (str(SHADES[rng.integers(len(SHADES))]), str(SHADES[rng.integers(len(SHADES))]))
            for _ in range(int(rng.integers(1, 8)))
        ]
    )
    result = edit_pattern(pattern, sequence)
    after = result.pattern

    assert_counts_add_up(after, pattern)
    assert after.total_stitches == pattern.total_stitches
    assert after.fabric_count == FABRIC_COUNT
    threads = [entry.thread for entry in after.key]
    allowed = {entry.thread for entry in pattern.key} | {entry.new for entry in sequence}
    assert set(threads) <= allowed
    assert len(result.changed) == len(sequence)


@pytest.mark.parametrize("seed", range(6))
def test_each_count_is_the_stitches_its_old_thread_had_when_it_applied(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pattern = speckled(SHADES[:8], (12, 15), seed=seed)
    sequence = _replaces(
        *[
            (str(SHADES[rng.integers(8)]), str(SHADES[rng.integers(len(SHADES))]))
            for _ in range(int(rng.integers(1, 8)))
        ]
    )
    result = edit_pattern(pattern, sequence)

    for position, entry in enumerate(sequence):
        before = edit_pattern(pattern, sequence[:position]).pattern
        stitches = {key_entry.thread: key_entry.stitches for key_entry in before.key}
        expected = 0 if entry.new == entry.old else stitches.get(entry.old, 0)
        assert result.changed[position] == expected, position


def test_the_input_pattern_is_not_modified() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    grid_before = pattern.grid.copy()
    key_before = pattern.key
    edit_pattern(pattern, _replaces(("310", "321"), ("321", "797"), ("Blanc", "310")))
    assert np.array_equal(pattern.grid, grid_before)
    assert pattern.key == key_before
    assert not pattern.grid.flags.writeable


def test_the_result_grid_is_read_only() -> None:
    result = edit_pattern(drawn(TWO, TWO_LEGEND), _replaces(("310", "321")))
    assert not result.pattern.grid.flags.writeable
    assert result.pattern.grid.dtype == np.intp


def test_the_same_input_twice_gives_the_same_pattern_and_counts() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    entries = _replaces(("321", "797"), ("310", "321"))
    first = edit_pattern(pattern, entries)
    second = edit_pattern(pattern, entries)
    assert_equal_patterns(first.pattern, second.pattern)
    assert first.changed == second.changed


# --------------------------------------------------------------------------- removal


def test_removing_a_thread_leaves_its_cells_bare_and_the_rest_as_they_were() -> None:
    pattern = drawn(THREE, THREE_LEGEND)
    result = edit_pattern(pattern, [_removal("321")])

    expected = drawn(["AABBBBB", "......."], {"A": "310", "B": "Blanc"})
    assert_equal_patterns(result.pattern, expected)
    assert result.pattern.total_stitches == pattern.total_stitches - 4
    assert result.changed == (4,)


def test_a_removed_thread_is_no_longer_there_for_a_later_entry() -> None:
    pattern = drawn(THREE, THREE_LEGEND)
    entries = [_removal("321"), Replace(old=dmc_thread("321"), new=dmc_thread("797"))]

    result = edit_pattern(pattern, entries)

    assert result.changed == (4, 0)
    assert counted(result.pattern) == [("Blanc", 5), ("310", 2)]


def test_a_thread_moved_onto_a_removed_one_is_removed_with_it_only_if_it_comes_first() -> None:
    pattern = drawn(SEQ, SEQ_LEGEND)
    merged_then_removed = [*_replaces(("310", "321")), _removal("321")]
    removed_then_moved = [_removal("321"), *_replaces(("310", "321"))]

    merged = edit_pattern(pattern, merged_then_removed)
    moved = edit_pattern(pattern, removed_then_moved)

    assert counted(merged.pattern) == [("Blanc", 2)]
    assert merged.changed == (4, 7)
    assert counted(moved.pattern) == [("321", 4), ("Blanc", 2)]
    assert moved.changed == (3, 4)


def test_removing_every_thread_leaves_bare_fabric_and_an_empty_key() -> None:
    pattern = drawn(TWO, TWO_LEGEND)
    result = edit_pattern(pattern, [_removal("310"), _removal("Blanc")])

    assert not result.pattern.key
    assert np.all(result.pattern.grid == EMPTY)
    assert result.pattern.grid.shape == pattern.grid.shape
    assert result.changed == (6, 3)


def test_a_removal_keeps_the_skeins_derived_from_the_counts() -> None:
    pattern = speckled(SHADES[:6], (20, 30), seed=4)
    result = edit_pattern(pattern, [Replace(old=pattern.key[0].thread, new=None)])

    for entry in result.pattern.key:
        assert entry.skeins == skeins_needed(entry.stitches, FABRIC_COUNT)
    assert pattern.key[0].thread not in [entry.thread for entry in result.pattern.key]
    assert result.changed == (pattern.key[0].stitches,)
