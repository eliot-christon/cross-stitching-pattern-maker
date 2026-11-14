"""`clean_pattern`: the three cleanup steps composed, in their fixed order.

Every case asserts the conditions it relies on (including what another order would give),
so a pattern that stops meeting them fails loudly instead of passing for the wrong reason.
Drawing helpers and sample patterns: `cleanup_helpers.py`.
"""

import dataclasses
import itertools
import math

import numpy as np
import pytest
from cleanup_helpers import (
    Cell,
    PatternFactory,
    all_bare,
    assert_cleaned_from,
    assert_equal_patterns,
    closest_pair,
    counted,
    distance,
    drawing,
    drawn,
    near_uneven,
    one_cell,
    ramp_with_bare_fabric,
    shades,
    single_thread,
    speckled,
    stitches_of,
)

from cross_stitch.pattern import (
    EMPTY,
    CleanedPattern,
    Pattern,
    clean_pattern,
    isolated_stitches,
    merge_similar_threads,
    prune_rare_threads,
    remove_confetti,
)

# 11 x 10: A 100 stitches, then two rare near-identical greys side by side, B 3 and C 3,
# both far from A.
RARE_TWINS = (*(["A" * 10] * 10), "BBBCCC....")
RARE_TWINS_LEGEND = {"A": "Blanc", "B": "3799", "C": "844"}

# 6 x 8: an A field holding a 5-cell B cluster (row 1) and one lone B cell (row 4), the
# lone cell's 8 neighbours all A: A 42 stitches, B 6.
CLUSTER_AND_LONE = (
    "AAAAAAAA",
    "ABBBBBAA",
    "AAAAAAAA",
    "AAAAAAAA",
    "AAAAAABA",
    "AAAAAAAA",
)
FIELD = {"A": "797", "B": "321"}

# 5 x 5: an A field with one B cell in the middle.
LONE_IN_FIELD = ("AAAAA", "AAAAA", "AABAA", "AAAAA", "AAAAA")

# Eight threads with at least one close pair (3799 and 844) and far ones.
NOISY_EIGHT = ("310", "Blanc", "321", "797", "3799", "844", "413", "317")

# (merge_distance, min_stitches, confetti_size), each one setting every step to work.
ALL_ON = [(3.0, 60, 1), (5.0, 100, 2), (10.0, 200, 3)]


def _noisy_eight(seed: int) -> Pattern:
    """40 x 40 of bare fabric and the eight threads at seeded random places: nearly every
    cell is confetti."""
    pattern = speckled(NOISY_EIGHT, (40, 40), seed)
    assert len(pattern.key) == 8
    return pattern


def _cluster_sets(pattern: Pattern) -> list[set[Cell]]:
    """Every set of same-entry stitched cells joined through their 8 neighbours, found by a
    depth-first flood written here, independent of the code under test."""
    entry_at: dict[Cell, int] = {
        (int(row), int(col)): int(pattern.grid[row, col])
        for row, col in np.argwhere(pattern.grid != EMPTY)
    }
    left = set(entry_at)
    clusters: list[set[Cell]] = []
    while left:
        stack = [left.pop()]
        cluster = set(stack)
        while stack:
            row, col = here = stack.pop()
            for other in itertools.product(range(row - 1, row + 2), range(col - 1, col + 2)):
                if other in left and entry_at[other] == entry_at[here]:
                    left.remove(other)
                    cluster.add(other)
                    stack.append(other)
        clusters.append(cluster)
    return clusters


def _unsettled(pattern: Pattern, confetti_size: int) -> list[set[Cell]]:
    """The clusters of at most `confetti_size` cells with a stitched cell next to them
    (necessarily of another entry): what confetti cleanup must leave none of."""
    height, width = pattern.grid.shape
    found: list[set[Cell]] = []
    for cluster in _cluster_sets(pattern):
        if len(cluster) > confetti_size:
            continue
        touched = {
            (r, c)
            for row, col in cluster
            for r, c in itertools.product(range(row - 1, row + 2), range(col - 1, col + 2))
            if 0 <= r < height and 0 <= c < width and pattern.grid[r, c] != EMPTY
        }
        if not touched <= cluster:
            found.append(cluster)
    return found


def _assert_same_cleaning(first: CleanedPattern, second: CleanedPattern) -> None:
    assert_equal_patterns(first.pattern, second.pattern)
    counts = (first.isolated_before, first.isolated_after)
    assert counts == (second.isolated_before, second.isolated_after)


# ------------------------------------------------------------------------- all settings 0


@pytest.mark.parametrize(
    "make",
    [near_uneven, ramp_with_bare_fabric, all_bare, single_thread, one_cell, shades],
    ids=["near-pair", "ramp-with-bare-fabric", "all-bare", "single-thread", "1x1", "shades"],
)
def test_all_three_settings_zero_return_the_input_and_equal_isolated_counts(
    make: PatternFactory,
) -> None:
    cleaned = clean_pattern(make(), merge_distance=0.0, min_stitches=0, confetti_size=0)
    assert_equal_patterns(cleaned.pattern, make())
    isolated = isolated_stitches(make())
    assert cleaned.isolated_before == cleaned.isolated_after == isolated


def test_the_cleaned_pattern_is_a_frozen_record_of_the_pattern_and_both_counts() -> None:
    cleaned = clean_pattern(
        drawn(LONE_IN_FIELD, FIELD), merge_distance=0.0, min_stitches=0, confetti_size=1
    )
    assert isinstance(cleaned, CleanedPattern)
    names = {field.name for field in dataclasses.fields(cleaned)}
    assert names == {"pattern", "isolated_before", "isolated_after"}
    assert isinstance(cleaned.pattern, Pattern)
    # Plain ints, not numpy integers, so the API can return them as they are.
    assert isinstance(cleaned.isolated_before, int)
    assert isinstance(cleaned.isolated_after, int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cleaned.isolated_after = 5  # type: ignore[misc]


# ------------------------------------------------------------------------------ the order


def test_merging_before_pruning_lets_two_rare_twins_survive_together() -> None:
    merge_distance = distance("3799", "844") + 0.01
    assert distance("3799", "Blanc") > merge_distance
    assert distance("844", "Blanc") > merge_distance
    original = drawn(RARE_TWINS, RARE_TWINS_LEGEND)
    assert counted(original) == [("Blanc", 100), ("844", 3), ("3799", 3)]
    # Pruning first would send both twins, 3 stitches each, to Blanc.
    pruned_first = merge_similar_threads(
        prune_rare_threads(original, min_stitches=5), merge_distance=merge_distance
    )
    assert counted(pruned_first) == [("Blanc", 106)]

    cleaned = clean_pattern(
        original, merge_distance=merge_distance, min_stitches=5, confetti_size=0
    )

    # Equal counts: 844, the earlier key entry, absorbs 3799 and then has 6 >= 5.
    assert counted(cleaned.pattern) == [("Blanc", 100), ("844", 6)]
    assert drawing(cleaned.pattern, RARE_TWINS_LEGEND) == [*RARE_TWINS[:-1], "CCCCCC...."]
    assert_cleaned_from(cleaned.pattern, original)


def test_confetti_before_pruning_leaves_no_entry_under_min_stitches() -> None:
    original = drawn(CLUSTER_AND_LONE, FIELD)
    assert counted(original) == [("797", 42), ("321", 6)]
    # Pruning first would keep B (6 >= 6), then the lone cell would leave it at 5.
    pruned_first = remove_confetti(prune_rare_threads(original, min_stitches=6), max_size=1)
    assert counted(pruned_first) == [("797", 43), ("321", 5)]

    cleaned = clean_pattern(original, merge_distance=0.0, min_stitches=6, confetti_size=1)

    # The lone cell becomes A, B falls to 5 and is pruned into A.
    assert min(stitches_of(cleaned.pattern)) >= 6
    assert counted(cleaned.pattern) == [("797", 48)]
    assert drawing(cleaned.pattern, FIELD) == ["A" * 8] * 6
    assert (cleaned.isolated_before, cleaned.isolated_after) == (1, 0)
    assert_cleaned_from(cleaned.pattern, original)


@pytest.mark.parametrize(("merge_distance", "min_stitches", "confetti_size"), ALL_ON)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_steps_run_merge_then_confetti_then_prune(
    seed: int, merge_distance: float, min_stitches: int, confetti_size: int
) -> None:
    original = _noisy_eight(seed)
    merged = merge_similar_threads(original, merge_distance=merge_distance)
    unconfettied = remove_confetti(merged, max_size=confetti_size)
    expected = prune_rare_threads(unconfettied, min_stitches=min_stitches)

    cleaned = clean_pattern(
        original,
        merge_distance=merge_distance,
        min_stitches=min_stitches,
        confetti_size=confetti_size,
    )

    assert_equal_patterns(cleaned.pattern, expected)


# ------------------------------------------------------------------------ post-conditions


@pytest.mark.parametrize(("merge_distance", "min_stitches", "confetti_size"), ALL_ON)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_all_three_guarantees_hold_on_the_cleaned_pattern(
    seed: int, merge_distance: float, min_stitches: int, confetti_size: int
) -> None:
    original = _noisy_eight(seed)
    # Each step has work to do on the input.
    assert closest_pair(original) < merge_distance
    assert min(stitches_of(original)) < min_stitches
    assert _unsettled(original, confetti_size)

    cleaned = clean_pattern(
        original,
        merge_distance=merge_distance,
        min_stitches=min_stitches,
        confetti_size=confetti_size,
    )
    result = cleaned.pattern

    assert closest_pair(result) >= merge_distance
    assert not _unsettled(result, confetti_size)
    assert len(result.key) == 1 or min(stitches_of(result)) >= min_stitches
    assert len(result.key) < len(original.key)
    assert_cleaned_from(result, original)
    assert cleaned.isolated_before == isolated_stitches(original)
    assert cleaned.isolated_after == isolated_stitches(result)


# ------------------------------------------------------------------------ isolated counts


def test_a_lone_stitch_in_a_field_is_counted_before_and_gone_after() -> None:
    original = drawn(LONE_IN_FIELD, FIELD)
    assert counted(original) == [("797", 24), ("321", 1)]

    cleaned = clean_pattern(original, merge_distance=0.0, min_stitches=0, confetti_size=1)

    assert (cleaned.isolated_before, cleaned.isolated_after) == (1, 0)
    assert drawing(cleaned.pattern, FIELD) == ["AAAAA"] * 5
    assert_cleaned_from(cleaned.pattern, original)


def test_a_lone_stitch_on_bare_fabric_stays_and_is_counted_after_too() -> None:
    original = drawn(["...", ".B.", "...", "AA."], FIELD)
    cleaned = clean_pattern(original, merge_distance=0.0, min_stitches=0, confetti_size=1)
    assert_equal_patterns(cleaned.pattern, drawn(["...", ".B.", "...", "AA."], FIELD))
    assert (cleaned.isolated_before, cleaned.isolated_after) == (1, 1)


# ------------------------------------------------------------------------ invalid input


@pytest.mark.parametrize(
    ("merge_distance", "min_stitches", "confetti_size", "message"),
    [
        (-1.0, 0, 0, "merge distance"),
        (math.nan, 0, 0, "merge distance"),
        (math.inf, 0, 0, "merge distance"),
        (0.0, -1, 0, "min stitches"),
        (0.0, 0, -1, "max size"),
        (3.0, 5, -1, "max size"),
    ],
    ids=[
        "distance-minus-1",
        "distance-nan",
        "distance-inf",
        "min-minus-1",
        "size-minus-1",
        "size-minus-1-others-on",
    ],
)
@pytest.mark.parametrize("make", [near_uneven, all_bare], ids=["near-pair", "all-bare"])
def test_an_invalid_setting_raises_the_steps_value_error(
    make: PatternFactory,
    merge_distance: float,
    min_stitches: int,
    confetti_size: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        clean_pattern(
            make(),
            merge_distance=merge_distance,
            min_stitches=min_stitches,
            confetti_size=confetti_size,
        )


# ------------------------------------------------------------- purity and determinism


def test_cleaning_leaves_the_input_pattern_untouched() -> None:
    original = _noisy_eight(0)
    grid = original.grid.copy()
    key = original.key
    cleaned = clean_pattern(original, merge_distance=5.0, min_stitches=100, confetti_size=2)
    assert len(cleaned.pattern.key) < len(key)
    assert np.array_equal(original.grid, grid)
    assert original.key == key
    assert not original.grid.flags.writeable


def test_the_same_cleaning_twice_gives_the_same_result() -> None:
    original = _noisy_eight(1)
    _assert_same_cleaning(
        clean_pattern(original, merge_distance=5.0, min_stitches=100, confetti_size=2),
        clean_pattern(original, merge_distance=5.0, min_stitches=100, confetti_size=2),
    )
    _assert_same_cleaning(
        clean_pattern(_noisy_eight(1), merge_distance=5.0, min_stitches=100, confetti_size=2),
        clean_pattern(_noisy_eight(1), merge_distance=5.0, min_stitches=100, confetti_size=2),
    )
