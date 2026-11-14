"""Pattern cleanup: merging near-identical threads.

Every case asserts the distances and counts it relies on, so a choice of threads that
stops meeting a case's conditions fails loudly instead of passing for the wrong reason.
Drawing helpers and sample patterns: `cleanup_helpers.py`.
"""

import itertools
import math

import numpy as np
import pytest
from cleanup_helpers import (
    EVEN_PAIR,
    FABRIC_COUNT,
    NEAR,
    Legend,
    PatternFactory,
    all_bare,
    assert_cleaned_from,
    assert_equal_patterns,
    chain_distance,
    closest_pair,
    codes_of,
    counted,
    distance,
    drawing,
    drawn,
    near_uneven,
    one_cell,
    ramp_with_bare_fabric,
    shades,
    single_thread,
)

from cross_stitch.pattern import (
    EMPTY,
    build_pattern,
    merge_similar_threads,
    stitches_per_skein,
)
from cross_stitch.threads import Thread, dmc_thread

# ------------------------------------------------------------------------- distance 0


@pytest.mark.parametrize(
    "make",
    [near_uneven, ramp_with_bare_fabric, all_bare, single_thread, one_cell, shades],
    ids=["near-pair", "ramp-with-bare-fabric", "all-bare", "single-thread", "1x1", "shades"],
)
def test_merge_distance_zero_returns_the_input_unchanged(make: PatternFactory) -> None:
    original = make()
    assert_equal_patterns(merge_similar_threads(original, merge_distance=0.0), make())


# -------------------------------------------------------------------------- one pair


def test_a_close_pair_merges_into_the_entry_with_more_stitches() -> None:
    original = near_uneven()
    merge_distance = distance("3799", "844") + 0.01
    result = merge_similar_threads(original, merge_distance=merge_distance)
    assert counted(result) == [("3799", 60)]
    assert [entry.thread for entry in result.key] == [dmc_thread("3799")]
    former_b = original.grid == 1
    assert np.count_nonzero(former_b) == 10
    assert np.all(result.grid[former_b] == 0)
    assert drawing(result, NEAR) == ["A" * 10] * 6
    assert_cleaned_from(result, original)


def test_a_merge_distance_equal_to_the_pair_distance_leaves_the_pattern_unchanged() -> None:
    original = near_uneven()
    result = merge_similar_threads(original, merge_distance=distance("3799", "844"))
    assert_equal_patterns(result, near_uneven())


@pytest.mark.parametrize(
    "legend",
    [{"A": "3799", "B": "844"}, {"A": "844", "B": "3799"}],
    ids=["3799-listed-first", "844-listed-first"],
)
def test_equal_counts_go_to_the_earlier_key_entry(legend: Legend) -> None:
    original = drawn(EVEN_PAIR, legend)
    # Numeric code order puts 844 first; string order would put "3799" first.
    assert counted(original) == [("844", 20), ("3799", 20)]
    result = merge_similar_threads(original, merge_distance=distance("844", "3799") + 0.01)
    assert counted(result) == [("844", 40)]
    assert np.array_equal(result.grid, np.zeros((4, 10), dtype=np.intp))
    assert_cleaned_from(result, original)


def test_a_merged_entry_takes_its_skeins_from_the_merged_count() -> None:
    # 1000 and 100 stitches need one skein each; merged, 1100 still need only one.
    assert stitches_per_skein(FABRIC_COUNT) >= 1100
    original = drawn(["A" * 100] * 10 + ["B" * 100], NEAR)
    assert [(entry.stitches, entry.skeins) for entry in original.key] == [(1000, 1), (100, 1)]
    result = merge_similar_threads(original, merge_distance=distance("3799", "844") + 0.01)
    assert [(e.thread.code, e.stitches, e.skeins) for e in result.key] == [("3799", 1100, 1)]


# ------------------------------------------------------------------------ three threads


def test_a_chain_merges_into_the_middle_entry_when_it_has_the_most_stitches() -> None:
    legend = {"A": "3799", "B": "413", "C": "317"}
    original = drawn(
        ["AAAAABBB", "AAAAABBB", "BBBBBBBB", "BBBBBBBB", "BBCCCCCC", "CCCCCCCC"], legend
    )
    assert counted(original) == [("413", 24), ("317", 14), ("3799", 10)]
    result = merge_similar_threads(original, merge_distance=chain_distance("3799", "413", "317"))
    assert counted(result) == [("413", 48)]
    assert drawing(result, legend) == ["B" * 8] * 6
    assert_cleaned_from(result, original)


def test_the_closest_pair_merges_first_and_the_far_end_stays() -> None:
    legend = {"A": "3799", "B": "413", "C": "317"}
    assert distance("3799", "413") < distance("413", "317")
    original = drawn(
        ["BBBBBAAA", "BBBBBAAA", "AAAAAAAA", "AAAAAAAA", "AACCCCCC", "CCCCCCCC"], legend
    )
    assert counted(original) == [("3799", 24), ("317", 14), ("413", 10)]
    result = merge_similar_threads(original, merge_distance=chain_distance("3799", "413", "317"))
    # B joins A; A keeps its own colour, which is too far from C, so C stays as it was.
    assert counted(result) == [("3799", 34), ("317", 14)]
    assert drawing(result, legend) == [
        "AAAAAAAA",
        "AAAAAAAA",
        "AAAAAAAA",
        "AAAAAAAA",
        "AACCCCCC",
        "CCCCCCCC",
    ]
    assert np.array_equal(result.grid == 1, original.grid == 1)
    assert_cleaned_from(result, original)


def test_the_closest_pair_merges_first_even_when_another_pair_comes_first_in_the_key() -> None:
    # A is first in the key and within reach of B, but B and C are closer: B joins C, the
    # larger of the two, and the resulting C is too far from A to merge with it.
    legend = {"A": "317", "B": "413", "C": "3799"}
    assert distance("413", "3799") < distance("317", "413")
    original = drawn(
        ["BBBBBAAA", "BBBBBAAA", "AAAAAAAA", "AAAAAAAA", "AACCCCCC", "CCCCCCCC"], legend
    )
    assert counted(original) == [("317", 24), ("3799", 14), ("413", 10)]
    result = merge_similar_threads(original, merge_distance=chain_distance("317", "413", "3799"))
    # 24 each: 317 before 3799 by code order.
    assert counted(result) == [("317", 24), ("3799", 24)]
    assert drawing(result, legend) == [
        "CCCCCAAA",
        "CCCCCAAA",
        "AAAAAAAA",
        "AAAAAAAA",
        "AACCCCCC",
        "CCCCCCCC",
    ]
    assert_cleaned_from(result, original)


def test_the_survivor_is_decided_on_the_counts_after_earlier_merges() -> None:
    # C has the most stitches in the input, but B absorbs A first (the closest pair) and
    # then has more than C, so B absorbs C too.
    legend = {"A": "3799", "B": "413", "C": "317"}
    assert distance("3799", "413") < distance("413", "317")
    original = drawn(["AAAAABBBB", "AAAAABBBB", "BBBBBBBCC", "CCCCCCCCC", "CCCCCCCCC"], legend)
    assert counted(original) == [("317", 20), ("413", 15), ("3799", 10)]
    result = merge_similar_threads(original, merge_distance=chain_distance("3799", "413", "317"))
    assert counted(result) == [("413", 45)]
    assert_cleaned_from(result, original)


def test_a_distance_above_every_pair_leaves_the_entry_holding_most_stitches() -> None:
    # 310 holds more than half the stitches, so it wins every merge it takes part in.
    legend = {"A": "310", "B": "Blanc", "C": "321", "D": "797"}
    original = drawn(
        ["AAAAAAAAAA", "AAAAAAAAAA", "AAAAAAAAAA", "BBBBBCCCCC", "BBBBBCCCCC", "DDDDDDDD.."],
        legend,
    )
    assert counted(original) == [("310", 30), ("321", 10), ("Blanc", 10), ("797", 8)]
    pairs = itertools.combinations(legend.values(), 2)
    merge_distance = max(distance(first, second) for first, second in pairs) + 1.0
    result = merge_similar_threads(original, merge_distance=merge_distance)
    assert counted(result) == [("310", 58)]
    assert drawing(result, legend) == ["AAAAAAAAAA"] * 5 + ["AAAAAAAA.."]
    assert_cleaned_from(result, original)


# ------------------------------------------------------------------------- bare fabric


def test_bare_fabric_cells_stay_bare_after_a_merge() -> None:
    original = drawn([".AAAB.", "AABBA.", "......", "A.AAB."], NEAR, fabric_count=18.0)
    assert counted(original) == [("3799", 9), ("844", 4)]
    result = merge_similar_threads(original, merge_distance=distance("3799", "844") + 0.01)
    assert drawing(result, NEAR) == [".AAAA.", "AAAAA.", "......", "A.AAA."]
    assert np.array_equal(result.grid == EMPTY, original.grid == EMPTY)
    assert result.total_stitches == 13
    assert result.fabric_count == 18.0
    assert_cleaned_from(result, original)


def test_equally_close_pairs_merge_in_key_order() -> None:
    # Three test threads of one RGB: every pair is at distance 0. Key order is X (5), Y (4),
    # Z (4). The rule merges (X, Y) first, so X absorbs Y and then Z. Taking (Y, Z) first
    # would give Y 8 stitches, enough to absorb X.
    grey = (120, 120, 120)
    threads = [Thread(code, f"test {code}", grey) for code in ("1", "2", "3")]
    cells = np.array([[0] * 5 + [1] * 4 + [2] * 4], dtype=np.intp)
    pattern = build_pattern(cells, threads, FABRIC_COUNT)
    assert counted(pattern) == [("1", 5), ("2", 4), ("3", 4)]

    result = merge_similar_threads(pattern, merge_distance=1.0)

    assert counted(result) == [("1", 13)]
    assert_cleaned_from(result, pattern)


def test_a_pattern_without_stitches_is_returned_empty() -> None:
    original = all_bare()
    result = merge_similar_threads(original, merge_distance=5.0)
    assert not result.key
    assert result.total_stitches == 0
    assert result.grid.shape == (2, 4)
    assert np.all(result.grid == EMPTY)


@pytest.mark.parametrize("make", [single_thread, one_cell], ids=["single-thread", "1x1"])
def test_a_single_thread_has_nothing_to_merge_with(make: PatternFactory) -> None:
    assert_equal_patterns(merge_similar_threads(make(), merge_distance=50.0), make())


# ---------------------------------------------------------------------- post-conditions

MERGING_DISTANCES = [3.0, 5.0, 10.0, 25.0, 60.0]


@pytest.mark.parametrize("merge_distance", MERGING_DISTANCES)
def test_no_two_entries_of_the_result_are_closer_than_the_merge_distance(
    merge_distance: float,
) -> None:
    original = shades()
    assert closest_pair(original) < merge_distance
    result = merge_similar_threads(original, merge_distance=merge_distance)
    assert len(result.key) < len(original.key)
    assert closest_pair(result) >= merge_distance
    assert_cleaned_from(result, original)


@pytest.mark.parametrize("merge_distance", MERGING_DISTANCES)
def test_only_threads_with_a_close_partner_lose_cells_and_survivors_keep_theirs(
    merge_distance: float,
) -> None:
    original = shades()
    before = codes_of(original)
    result = merge_similar_threads(original, merge_distance=merge_distance)
    after = codes_of(result)
    for position, code in enumerate(before):
        if code in after:
            assert np.all(result.grid[original.grid == position] == after.index(code)), code
        else:
            partners = [other for other in before if other != code]
            assert any(distance(code, other) < merge_distance for other in partners), code


# ------------------------------------------------------------------------ invalid input


@pytest.mark.parametrize(
    "merge_distance",
    [-1.0, -1e-9, -math.inf, math.nan, math.inf],
    ids=["minus-1", "tiny-negative", "minus-inf", "nan", "inf"],
)
@pytest.mark.parametrize("make", [near_uneven, all_bare], ids=["near-pair", "all-bare"])
def test_a_negative_or_non_finite_merge_distance_raises_value_error(
    make: PatternFactory, merge_distance: float
) -> None:
    with pytest.raises(ValueError, match="merge distance"):
        merge_similar_threads(make(), merge_distance=merge_distance)


# ------------------------------------------------------------- purity and determinism


def test_the_input_pattern_is_untouched() -> None:
    original = shades()
    grid = original.grid.copy()
    key = original.key
    result = merge_similar_threads(original, merge_distance=10.0)
    assert len(result.key) < len(key)
    assert np.array_equal(original.grid, grid)
    assert original.key == key
    assert not original.grid.flags.writeable
    assert original.fabric_count == FABRIC_COUNT


def test_the_same_call_twice_gives_the_same_pattern() -> None:
    original = shades()
    assert_equal_patterns(
        merge_similar_threads(original, merge_distance=10.0),
        merge_similar_threads(original, merge_distance=10.0),
    )


def test_equal_patterns_built_separately_merge_the_same_way() -> None:
    assert_equal_patterns(
        merge_similar_threads(shades(), merge_distance=10.0),
        merge_similar_threads(shades(), merge_distance=10.0),
    )
