"""Pattern cleanup steps: merging near-identical threads and pruning rare ones.

Every case asserts the distances and counts it relies on, so a choice of threads that
stops meeting a case's conditions fails loudly instead of passing for the wrong reason.
Drawing helpers and sample patterns: `cleanup_helpers.py`.
"""

import itertools
import math
from collections.abc import Mapping

import numpy as np
import pytest
from cleanup_helpers import (
    EVEN_PAIR,
    FABRIC_COUNT,
    NEAR,
    RAMP,
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
    stitches_of,
)

from cross_stitch.pattern import (
    EMPTY,
    Pattern,
    build_pattern,
    merge_similar_threads,
    prune_rare_threads,
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


# ===================================================================== rare threads

# A, B and C of the contract: a rare grey B between white and black. B is 3799, a very dark
# grey: nearer to 310 (black) than to Blanc in every layout below.
B_NEAR_C = {"A": "Blanc", "B": "3799", "C": "310"}
B_NEAR_A = {"A": "310", "B": "3799", "C": "Blanc"}

# 16 x 10: A 100 stitches, B 3, C 50, 7 cells of bare fabric. One B sits inside A.
RARE_TRIO = (
    *(["A" * 10] * 9),
    "AAAAAAAABA",
    "ACCCCCCCCC",
    *(["C" * 10] * 4),
    "BCB.......",
)

# 16 x 10: A 100 stitches, C 50, B 5, 5 cells of bare fabric.
FIVE_B_TRIO = (*(["A" * 10] * 10), *(["C" * 10] * 5), "BBBBB.....")

# Two rare mid greys either side of L* 50, much nearer to each other than to black or
# white: 317 (L* about 46) is nearer to 310, 169 (L* about 55) nearer to Blanc.
RARE_PAIR = {"A": "310", "B": "317", "C": "Blanc", "D": "169"}

# 10 x 16: A 100 stitches, C 50, B 3 and D 2 side by side, 5 cells of bare fabric.
RARE_PAIR_ROWS = (
    *(["A" * 16] * 6),
    "AAAA" + "C" * 12,
    *(["C" * 16] * 2),
    "CCCCCCBBBDD.....",
)


def _assert_pruned_from(result: Pattern, original: Pattern, min_stitches: int) -> None:
    """The entries of the result are those of the input with at least `min_stitches`
    stitches, or the input's first entry alone when none has; each kept entry keeps all
    its cells and only gains, and each pruned entry's cells all move to one kept entry."""
    assert_cleaned_from(result, original)
    kept = [code for code, count in counted(original) if count >= min_stitches]
    assert set(codes_of(result)) == set(kept or codes_of(original)[:1])
    after = codes_of(result)
    for position, entry in enumerate(original.key):
        targets = np.unique(result.grid[original.grid == position])
        assert targets.size == 1, entry.thread.code
        if entry.thread.code in after:
            assert after[int(targets[0])] == entry.thread.code
            assert result.key[int(targets[0])].stitches >= entry.stitches


# -------------------------------------------------------------------- min stitches 0, 1


@pytest.mark.parametrize("min_stitches", [0, 1])
@pytest.mark.parametrize(
    "make",
    [near_uneven, ramp_with_bare_fabric, all_bare, single_thread, one_cell, shades],
    ids=["near-pair", "ramp-with-bare-fabric", "all-bare", "single-thread", "1x1", "shades"],
)
def test_min_stitches_zero_or_one_returns_the_input_unchanged(
    make: PatternFactory, min_stitches: int
) -> None:
    original = make()
    assert_equal_patterns(prune_rare_threads(original, min_stitches=min_stitches), make())


# ---------------------------------------------------------------------- the nearest kept


def test_a_rare_entry_moves_to_the_nearest_kept_entry_not_the_largest() -> None:
    assert distance("3799", "310") < distance("3799", "Blanc")
    original = drawn(RARE_TRIO, B_NEAR_C)
    assert counted(original) == [("Blanc", 100), ("310", 50), ("3799", 3)]

    result = prune_rare_threads(original, min_stitches=5)

    assert counted(result) == [("Blanc", 100), ("310", 53)]
    former_b = original.grid == 2
    assert np.count_nonzero(former_b) == 3
    assert np.all(result.grid[former_b] == 1)
    assert drawing(result, B_NEAR_C) == [row.replace("B", "C") for row in RARE_TRIO]
    _assert_pruned_from(result, original, 5)


def test_a_rare_entry_nearest_to_the_largest_entry_moves_to_it() -> None:
    assert distance("3799", "310") < distance("3799", "Blanc")
    original = drawn(RARE_TRIO, B_NEAR_A)
    assert counted(original) == [("310", 100), ("Blanc", 50), ("3799", 3)]

    result = prune_rare_threads(original, min_stitches=5)

    assert counted(result) == [("310", 103), ("Blanc", 50)]
    former_b = original.grid == 2
    assert np.all(result.grid[former_b] == 0)
    assert drawing(result, B_NEAR_A) == [row.replace("B", "A") for row in RARE_TRIO]
    _assert_pruned_from(result, original, 5)


@pytest.mark.parametrize("min_stitches", [4, 5], ids=["one-under", "exactly"])
def test_an_entry_with_exactly_min_stitches_is_kept(min_stitches: int) -> None:
    original = drawn(FIVE_B_TRIO, B_NEAR_C)
    assert counted(original) == [("Blanc", 100), ("310", 50), ("3799", 5)]
    result = prune_rare_threads(original, min_stitches=min_stitches)
    assert_equal_patterns(result, drawn(FIVE_B_TRIO, B_NEAR_C))


@pytest.mark.parametrize(
    ("min_stitches", "expected"),
    [
        (6, [("Blanc", 100), ("310", 55)]),
        (50, [("Blanc", 100), ("310", 55)]),
        (51, [("Blanc", 155)]),
        (100, [("Blanc", 155)]),
        (101, [("Blanc", 155)]),
        (1000, [("Blanc", 155)]),
    ],
    ids=["one-past-b", "exactly-c", "one-past-c", "exactly-a", "one-past-a", "far-past-a"],
)
def test_each_threshold_keeps_exactly_the_entries_at_or_above_it(
    min_stitches: int, expected: list[tuple[str, int]]
) -> None:
    assert distance("3799", "310") < distance("3799", "Blanc")
    original = drawn(FIVE_B_TRIO, B_NEAR_C)
    assert counted(original) == [("Blanc", 100), ("310", 50), ("3799", 5)]
    result = prune_rare_threads(original, min_stitches=min_stitches)
    assert counted(result) == expected
    _assert_pruned_from(result, original, min_stitches)


def test_two_rare_entries_never_go_to_each_other() -> None:
    # B and D are each other's nearest thread, but both are under the threshold, so each
    # goes to its own nearest kept entry: B to A, D to C. Counting as entries are moved
    # would let D join B and lift B to 5, keeping it.
    rare, kept = ("317", "169"), ("310", "Blanc")
    assert distance("317", "169") < min(distance(r, k) for r in rare for k in kept)
    assert distance("317", "310") < distance("317", "Blanc")
    assert distance("169", "Blanc") < distance("169", "310")
    original = drawn(RARE_PAIR_ROWS, RARE_PAIR)
    assert counted(original) == [("310", 100), ("Blanc", 50), ("317", 3), ("169", 2)]

    result = prune_rare_threads(original, min_stitches=5)

    assert counted(result) == [("310", 103), ("Blanc", 52)]
    assert drawing(result, RARE_PAIR)[-1] == "CCCCCCAAACC....."
    assert drawing(result, RARE_PAIR)[:-1] == list(RARE_PAIR_ROWS[:-1])
    _assert_pruned_from(result, original, 5)


@pytest.mark.parametrize("listed", [("1", "2"), ("2", "1")], ids=["1-first", "2-first"])
@pytest.mark.parametrize(
    ("counts", "before", "after"),
    [
        ({"1": 6, "2": 6}, ["1", "2", "3"], [("1", 8), ("2", 6)]),
        ({"1": 6, "2": 9}, ["2", "1", "3"], [("2", 11), ("1", 6)]),
    ],
    ids=["equal-counts", "higher-code-first-in-key"],
)
def test_a_rare_entry_equally_near_two_kept_entries_goes_to_the_earlier_one(
    listed: tuple[str, str],
    counts: Mapping[str, int],
    before: list[str],
    after: list[tuple[str, int]],
) -> None:
    # Two test threads of one grey, so the rare red one is at exactly the same distance
    # from both and only their key positions can decide.
    grey = (120, 120, 120)
    threads = [Thread(code, f"test {code}", grey) for code in listed]
    threads.append(Thread("3", "test 3", (200, 60, 60)))
    row = [index for index, code in enumerate(listed) for _ in range(counts[code])] + [2, 2]
    pattern = build_pattern(np.array([row], dtype=np.intp), threads, FABRIC_COUNT)
    assert codes_of(pattern) == before
    assert pattern.key[2].stitches == 2

    result = prune_rare_threads(pattern, min_stitches=5)

    assert counted(result) == after
    assert_cleaned_from(result, pattern)


# ---------------------------------------------------------------- the first entry stays


def test_a_threshold_above_every_count_leaves_the_first_entry_alone() -> None:
    legend = {"A": "321", "B": "797", "C": "Blanc"}
    original = drawn(["AAAB", "BBCC", "A..."], legend)
    assert counted(original) == [("321", 4), ("797", 3), ("Blanc", 2)]

    result = prune_rare_threads(original, min_stitches=10)

    assert counted(result) == [("321", 9)]
    assert drawing(result, legend) == ["AAAA", "AAAA", "A..."]
    assert_cleaned_from(result, original)


@pytest.mark.parametrize(
    "legend",
    [{"A": "3799", "B": "844"}, {"A": "844", "B": "3799"}],
    ids=["3799-listed-first", "844-listed-first"],
)
def test_with_equal_counts_under_the_threshold_the_first_key_entry_stays(legend: Legend) -> None:
    original = drawn(EVEN_PAIR, legend)
    # Numeric code order puts 844 first; string order would put "3799" first.
    assert counted(original) == [("844", 20), ("3799", 20)]
    result = prune_rare_threads(original, min_stitches=100)
    assert counted(result) == [("844", 40)]
    assert np.array_equal(result.grid, np.zeros((4, 10), dtype=np.intp))
    assert_cleaned_from(result, original)


@pytest.mark.parametrize("make", [single_thread, one_cell], ids=["single-thread", "1x1"])
def test_a_single_thread_is_kept_whatever_the_threshold(make: PatternFactory) -> None:
    assert_equal_patterns(prune_rare_threads(make(), min_stitches=1000), make())


def test_a_pruned_entry_takes_its_skeins_from_the_merged_count() -> None:
    # A fills exactly one skein; one more stitch from B needs a second.
    per_skein = stitches_per_skein(FABRIC_COUNT)
    original = drawn(["A" * per_skein + "B"], NEAR)
    assert [(e.stitches, e.skeins) for e in original.key] == [(per_skein, 1), (1, 1)]
    result = prune_rare_threads(original, min_stitches=2)
    assert [(e.thread.code, e.stitches, e.skeins) for e in result.key] == [
        ("3799", per_skein + 1, 2)
    ]


# ------------------------------------------------------------------------- bare fabric


def test_bare_fabric_cells_stay_bare_after_pruning() -> None:
    # A (3799, 3 stitches) is under 4 and goes to 413, the nearer of the two kept greys.
    original = ramp_with_bare_fabric()
    assert counted(original) == [("317", 4), ("413", 4), ("3799", 3)]
    assert distance("3799", "413") < distance("3799", "317")

    result = prune_rare_threads(original, min_stitches=4)

    assert counted(result) == [("413", 7), ("317", 4)]
    assert drawing(result, dict(zip("ABC", RAMP, strict=True))) == [
        "B.BBC",
        "..BCC",
        "BBB.C",
    ]
    assert np.array_equal(result.grid == EMPTY, original.grid == EMPTY)
    _assert_pruned_from(result, original, 4)


def test_a_rare_stitch_alone_on_bare_fabric_is_moved_not_removed() -> None:
    original = drawn(["AAA.", "AA..", "...B"], NEAR, fabric_count=18.0)
    assert counted(original) == [("3799", 5), ("844", 1)]

    result = prune_rare_threads(original, min_stitches=2)

    assert drawing(result, NEAR) == ["AAA.", "AA..", "...A"]
    assert result.total_stitches == 6
    assert result.fabric_count == 18.0
    _assert_pruned_from(result, original, 2)


@pytest.mark.parametrize("min_stitches", [0, 1, 5, 1000])
def test_a_pattern_without_stitches_is_returned_empty_by_pruning(min_stitches: int) -> None:
    result = prune_rare_threads(all_bare(), min_stitches=min_stitches)
    assert not result.key
    assert result.total_stitches == 0
    assert result.grid.shape == (2, 4)
    assert np.all(result.grid == EMPTY)


# ---------------------------------------------------------------------- post-conditions

PRUNING_THRESHOLDS = [10, 25, 50, 75, 2000]


@pytest.mark.parametrize("min_stitches", PRUNING_THRESHOLDS)
def test_pruning_keeps_exactly_the_entries_at_or_above_the_threshold(min_stitches: int) -> None:
    original = shades()
    assert min(stitches_of(original)) < min_stitches
    result = prune_rare_threads(original, min_stitches=min_stitches)
    assert len(result.key) < len(original.key)
    _assert_pruned_from(result, original, min_stitches)


@pytest.mark.parametrize("min_stitches", PRUNING_THRESHOLDS)
def test_every_pruned_entry_moves_to_its_nearest_kept_entry(min_stitches: int) -> None:
    original = shades()
    result = prune_rare_threads(original, min_stitches=min_stitches)
    after = codes_of(result)
    pruned = [code for code in codes_of(original) if code not in after]
    assert pruned
    for position, code in enumerate(codes_of(original)):
        if code in after:
            continue
        targets = np.unique(result.grid[original.grid == position])
        assert targets.size == 1, code
        target = after[int(targets[0])]
        nearest = min(distance(code, other) for other in after)
        assert distance(code, target) <= nearest + 1e-9, (code, target)


# ------------------------------------------------------------------------ invalid input


@pytest.mark.parametrize("min_stitches", [-1, -1000], ids=["minus-1", "minus-1000"])
@pytest.mark.parametrize("make", [near_uneven, all_bare], ids=["near-pair", "all-bare"])
def test_a_negative_min_stitches_raises_value_error(
    make: PatternFactory, min_stitches: int
) -> None:
    with pytest.raises(ValueError, match="min stitches"):
        prune_rare_threads(make(), min_stitches=min_stitches)


# ------------------------------------------------------------- purity and determinism


def test_pruning_leaves_the_input_pattern_untouched() -> None:
    original = shades()
    grid = original.grid.copy()
    key = original.key
    result = prune_rare_threads(original, min_stitches=40)
    assert len(result.key) < len(key)
    assert np.array_equal(original.grid, grid)
    assert original.key == key
    assert not original.grid.flags.writeable
    assert original.fabric_count == FABRIC_COUNT


def test_the_same_pruning_twice_gives_the_same_pattern() -> None:
    original = shades()
    assert_equal_patterns(
        prune_rare_threads(original, min_stitches=40),
        prune_rare_threads(original, min_stitches=40),
    )


def test_equal_patterns_built_separately_prune_the_same_way() -> None:
    assert_equal_patterns(
        prune_rare_threads(shades(), min_stitches=40),
        prune_rare_threads(shades(), min_stitches=40),
    )
