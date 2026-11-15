"""`limit_threads` and the thread cap at the end of `clean_pattern`.

Drawing helpers and sample patterns: `cleanup_helpers.py`. Distances are computed there,
never taken from the code under test.
"""

import itertools

import pytest
from cleanup_helpers import (
    PatternFactory,
    all_bare,
    assert_cleaned_from,
    assert_equal_patterns,
    closest_pair,
    codes_of,
    counted,
    distance,
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
    CLEANUP_HEADROOM,
    clean_pattern,
    colours_with_headroom,
    limit_threads,
    merge_similar_threads,
)

# Five threads in two families: two near-black greys, two reds and a white far from both.
FIVE = {"A": "310", "B": "3799", "C": "321", "D": "817", "E": "Blanc"}
FIVE_ROWS = (
    "AAAAAAAABB",
    "CCCCCCDDDE",
    "AAAACCCCEE",
    "AAAABCCCEE",
)


def _five() -> tuple[str, ...]:
    pattern = drawn(FIVE_ROWS, FIVE)
    assert counted(pattern) == [
        ("310", 16),
        ("321", 13),
        ("Blanc", 5),
        ("817", 3),
        ("3799", 3),
    ]
    return FIVE_ROWS


def test_five_threads_capped_at_three_merge_each_family_into_its_bigger_thread() -> None:
    original = drawn(_five(), FIVE)
    # The two families are each other's closest pairs; white is far from both.
    family = max(distance("310", "3799"), distance("321", "817"))
    assert family < min(
        distance(first, second)
        for first, second in itertools.product(["310", "3799", "321", "817"], ["Blanc"])
    )

    result = limit_threads(original, 3)

    assert counted(result) == [("310", 19), ("321", 16), ("Blanc", 5)]
    assert_cleaned_from(result, original)


def test_capping_is_the_merge_of_the_closest_pairs_first() -> None:
    original = drawn(_five(), FIVE)
    # One merge: the closest pair of the key goes, as merge_similar_threads would take it.
    just_above_closest = closest_pair(original) + 1e-6
    expected = merge_similar_threads(original, merge_distance=just_above_closest)
    assert len(expected.key) == 4

    assert_equal_patterns(limit_threads(original, 4), expected)


@pytest.mark.parametrize("count", [1, 2])
def test_a_cap_leaves_exactly_that_many_threads_and_the_counts_add_up(count: int) -> None:
    original = shades()
    result = limit_threads(original, count)

    assert len(result.key) == count
    assert_cleaned_from(result, original)


@pytest.mark.parametrize(
    "make",
    [near_uneven, ramp_with_bare_fabric, all_bare, single_thread, one_cell],
    ids=["near-pair", "ramp-with-bare-fabric", "all-bare", "single-thread", "1x1"],
)
def test_a_cap_the_key_already_meets_returns_the_input_itself(make: PatternFactory) -> None:
    original = make()
    assert limit_threads(original, max(len(original.key), 1)) is original


@pytest.mark.parametrize("count", [0, -1])
def test_a_cap_under_one_thread_is_refused(count: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        limit_threads(shades(), count)


def test_capping_twice_gives_the_same_pattern() -> None:
    assert_equal_patterns(limit_threads(shades(), 5), limit_threads(shades(), 5))


# ---------------------------------------------------------------- the cap in clean_pattern


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_cleanup_then_cap_keeps_every_cleanup_guarantee(seed: int) -> None:
    codes = ["310", "3799", "844", "413", "317", "321", "817", "797", "Blanc"]
    original = speckled(codes, (24, 30), seed)
    merge_distance, min_stitches = 3.0, 20

    cleaned = clean_pattern(
        original,
        merge_distance=merge_distance,
        min_stitches=min_stitches,
        confetti_size=0,
        max_colours=3,
    )
    result = cleaned.pattern

    assert len(result.key) == 3
    assert closest_pair(result) >= merge_distance
    assert min(stitches_of(result)) >= min_stitches
    assert_cleaned_from(result, original)
    assert cleaned.converted is original


def test_no_cap_leaves_what_cleanup_gives() -> None:
    original = shades()
    capped = clean_pattern(original, merge_distance=0, min_stitches=0, confetti_size=0)
    assert capped.pattern is original
    assert codes_of(capped.pattern) == codes_of(original)


@pytest.mark.parametrize("asked", [1, 2, 7, 20, 100])
def test_the_headroom_converts_with_more_threads_than_asked(asked: int) -> None:
    converted = colours_with_headroom(asked)
    assert converted >= asked * CLEANUP_HEADROOM
    assert converted < asked * CLEANUP_HEADROOM + 1
