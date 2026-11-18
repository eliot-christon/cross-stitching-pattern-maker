"""Helpers shared by the pattern cleanup tests.

Patterns are drawn as rows of letters, each letter standing for a DMC thread named by its
code and "." for bare fabric, and built with `build_pattern`. Distances are CIEDE2000
between the threads' Lab colours, computed here with `delta_e_2000`, never taken from the
code under test. `conftest.py` registers this module for pytest's assertion rewriting.
"""

import itertools
import math
from collections.abc import Callable, Mapping, Sequence

import numpy as np
import numpy.typing as npt

from cross_stitch.colour import delta_e_2000, srgb_to_lab
from cross_stitch.pattern import (
    EMPTY,
    Pattern,
    build_pattern,
    skeins_needed,
)
from cross_stitch.threads import dmc_thread

type Legend = Mapping[str, str]
type PatternFactory = Callable[[], Pattern]
type Cell = tuple[int, int]

BARE = "."
FABRIC_COUNT = 14.0

# Two dark pewter greys close enough to be confused on fabric. By code order 844 comes
# before 3799 (numeric, not string, order), so a tie in stitches goes to 844.
NEAR = {"A": "3799", "B": "844"}

# Neutral greys from dark to light: 3799 -> 413 -> 317, each step a little larger than the
# one before, the two ends further apart than either step.
RAMP = ("3799", "413", "317")

# A spread of greys, whites, browns and a few strong colours: close pairs and far ones.
SHADES = (
    "310",
    "3799",
    "844",
    "413",
    "317",
    "169",
    "414",
    "318",
    "168",
    "415",
    "762",
    "Blanc",
    "B5200",
    "3865",
    "Ecru",
    "321",
    "797",
    "820",
    "3371",
    "451",
    "452",
    "453",
    "645",
    "646",
    "647",
    "648",
)

# 6 x 10: A 50 stitches, B 10, the B cells scattered.
UNEVEN_PAIR = (
    "BAAAAAAAAB",
    "AAABAAAAAA",
    "AABBAAAAAA",
    "AAAAAABAAA",
    "ABAAAAAABA",
    "AAAAABAAAB",
)

# 4 x 10: A 20 stitches, B 20, interleaved.
EVEN_PAIR = (
    "ABABABABAB",
    "BABABABABA",
    "AABBAABBAB",
    "BBAABBAABA",
)


# ------------------------------------------------------------------------------ helpers


def drawn(rows: Sequence[str], legend: Legend, fabric_count: float = FABRIC_COUNT) -> Pattern:
    """A pattern drawn as rows of letters: a letter is the DMC thread `legend[letter]`, "."
    is bare fabric. The threads go to `build_pattern` in legend order."""
    letters = list(legend)
    cells = np.array(
        [[EMPTY if char == BARE else letters.index(char) for char in row] for row in rows],
        dtype=np.intp,
    )
    return build_pattern(cells, [dmc_thread(legend[letter]) for letter in letters], fabric_count)


def drawing(pattern: Pattern, legend: Legend) -> list[str]:
    """The grid as rows of letters, the inverse of `drawn` for the same legend."""
    letter_of = {code: letter for letter, code in legend.items()}
    letters = [letter_of[entry.thread.code] for entry in pattern.key]
    return [
        "".join(BARE if index == EMPTY else letters[int(index)] for index in row)
        for row in pattern.grid
    ]


def speckled(codes: Sequence[str], shape: tuple[int, int], seed: int) -> Pattern:
    """Bare fabric and the threads of `codes` at seeded random places, bare fabric the most
    likely and each thread less likely than the one before it, so the counts differ."""
    weights = np.arange(len(codes) + 1, 0, -1, dtype=np.float64)
    draw = np.random.default_rng(seed).choice(len(codes) + 1, size=shape, p=weights / weights.sum())
    cells = (draw - 1).astype(np.intp)
    return build_pattern(cells, [dmc_thread(code) for code in codes], FABRIC_COUNT)


def codes_of(pattern: Pattern) -> list[str]:
    return [entry.thread.code for entry in pattern.key]


def stitches_of(pattern: Pattern) -> list[int]:
    return [entry.stitches for entry in pattern.key]


def code_grid(pattern: Pattern) -> list[list[str | None]]:
    """The grid as thread codes, None for bare fabric."""
    return [
        [None if index == EMPTY else pattern.key[int(index)].thread.code for index in row]
        for row in pattern.grid
    ]


def counted(pattern: Pattern) -> list[tuple[str, int]]:
    """The key as (code, stitches), in key order."""
    return list(zip(codes_of(pattern), stitches_of(pattern), strict=True))


def _lab(code: str) -> npt.NDArray[np.float64]:
    return srgb_to_lab(dmc_thread(code).rgb)


def distance(first: str, second: str) -> float:
    """CIEDE2000 between two DMC threads: the smaller of both argument orders, so a merge
    distance set to it is never above the distance, whichever way the code measures it."""
    return min(
        float(delta_e_2000(_lab(first), _lab(second))),
        float(delta_e_2000(_lab(second), _lab(first))),
    )


def closest_pair(pattern: Pattern) -> float:
    """The smallest distance between two entries of the key, infinite with fewer than two."""
    pairs = itertools.combinations(codes_of(pattern), 2)
    return min((distance(first, second) for first, second in pairs), default=math.inf)


def chain_distance(first: str, middle: str, last: str) -> float:
    """A merge distance above d(first, middle) and d(middle, last) and under d(first, last),
    after checking that the three threads leave room for one."""
    links = max(distance(first, middle), distance(middle, last))
    ends = distance(first, last)
    assert links < ends, (links, ends)
    merge_distance = (links + ends) / 2
    assert links < merge_distance < ends
    return merge_distance


def assert_cleaned_from(result: Pattern, original: Pattern) -> None:
    """What any cleanup step keeps: size, fabric, bare-fabric cells and total stitches, only
    threads of the original key, and counts and skeins derived from the result's grid."""
    assert result.grid.shape == original.grid.shape
    assert result.grid.dtype == np.intp
    assert not result.grid.flags.writeable
    assert result.fabric_count == original.fabric_count
    assert np.array_equal(result.grid == EMPTY, original.grid == EMPTY)
    assert result.total_stitches == original.total_stitches
    threads = [entry.thread for entry in result.key]
    assert len(set(threads)) == len(threads)
    assert set(threads) <= {entry.thread for entry in original.key}
    stitched = result.grid[result.grid != EMPTY]
    assert np.all((stitched >= 0) & (stitched < len(result.key)))
    for index, entry in enumerate(result.key):
        cells = int(np.count_nonzero(result.grid == index))
        assert cells >= 1, entry.thread.code
        assert entry.stitches == cells, entry.thread.code
        assert entry.skeins == skeins_needed(cells, result.fabric_count), entry.thread.code
    assert stitches_of(result) == sorted(stitches_of(result), reverse=True)


def assert_counts_add_up(result: Pattern, original: Pattern) -> None:
    """What any edit keeps: the size and fabric, every stitch in exactly one key entry
    (counts summing to the total and to the stitched cells), skeins from the counts, the
    key sorted by stitches with each thread once."""
    assert result.grid.shape == original.grid.shape
    assert result.fabric_count == original.fabric_count
    stitched = int(np.count_nonzero(result.grid != EMPTY))
    assert sum(entry.stitches for entry in result.key) == result.total_stitches == stitched
    for index, entry in enumerate(result.key):
        assert entry.stitches == int(np.count_nonzero(result.grid == index)) >= 1
        assert entry.skeins == skeins_needed(entry.stitches, result.fabric_count)
    assert stitches_of(result) == sorted(stitches_of(result), reverse=True)
    threads = [entry.thread for entry in result.key]
    assert len(set(threads)) == len(threads)


def assert_equal_patterns(first: Pattern, second: Pattern) -> None:
    assert (first.grid.shape, first.grid.dtype) == (second.grid.shape, second.grid.dtype)
    assert np.array_equal(first.grid, second.grid)
    assert (first.key, first.fabric_count) == (second.key, second.fabric_count)


def near_uneven() -> Pattern:
    pattern = drawn(UNEVEN_PAIR, NEAR)
    assert counted(pattern) == [("3799", 50), ("844", 10)]
    return pattern


def ramp_with_bare_fabric() -> Pattern:
    pattern = drawn(["A.BBC", "..BCC", "AAB.C"], dict(zip("ABC", RAMP, strict=True)))
    assert np.count_nonzero(pattern.grid == EMPTY) == 4
    return pattern


def all_bare() -> Pattern:
    pattern = drawn(["....", "...."], {"A": "310"})
    assert not pattern.key
    return pattern


def single_thread() -> Pattern:
    return drawn(["AAA", "A.A"], {"A": "321"})


def one_cell() -> Pattern:
    return drawn(["A"], {"A": "797"})


def shades() -> Pattern:
    return speckled(SHADES, (30, 40), seed=3)
