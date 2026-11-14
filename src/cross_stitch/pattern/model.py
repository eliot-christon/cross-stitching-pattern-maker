"""The pattern model: a stitch grid, its thread key, counts, skeins and finished size.

Counts are never stored apart from the grid: `build_pattern` derives every key entry's
stitch count from the grid and every skein estimate from that count, so the counts add up
by construction.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cross_stitch.threads import Thread

__all__ = [
    "EMPTY",
    "KeyEntry",
    "Pattern",
    "build_pattern",
    "check_fabric_count",
    "skeins_needed",
    "stitches_per_skein",
]

EMPTY = -1
"""Grid value of a cell left unstitched (bare fabric)."""

CM_PER_INCH = 2.54

# Skein estimate constants (see `stitches_per_skein`), after Kathleen M. Dyer's
# Needlework FAQ, section 32, https://www.mismatch.co.uk/cross.htm#floss_amt
SEGMENTS_PER_SKEIN = 17  # a skein is about 8 1/2 yards: 17 lengths of 18 inches
USABLE_INCHES_PER_SEGMENT = 15  # 3 of every 18 inches go on securing ends and waste
SKEIN_STRANDS = 6
STITCH_STRANDS = 2
CROSS_INCHES_TIMES_COUNT = 6  # one full cross takes 6 / count inches of thread
COMPLEX_PROJECT_ALLOWANCE = 0.20  # more thread per cross for many colour changes


def check_fabric_count(fabric_count: float) -> None:
    """Raise `ValueError` unless `fabric_count` (stitches per inch) is finite and > 0."""
    if not (math.isfinite(fabric_count) and fabric_count > 0):
        raise ValueError(f"fabric count must be a positive number, got {fabric_count!r}")


def stitches_per_skein(fabric_count: float) -> int:
    """How many full crosses one skein covers on this fabric count (stitches per inch).

    Kathleen M. Dyer's Needlework FAQ, section 32 "The Amount of Floss for Cross Stitch"
    (https://www.mismatch.co.uk/cross.htm#floss_amt), derives

        17 * (15 / (6 / count)) * (6 / strands)

    from a skein of about 8 1/2 yards cut into 17 lengths of 18 inches, 3 inches of each
    lost to securing ends and general waste, and 6 / count inches of thread per cross
    (both half stitches, the vertical travel on the back and a little slop). On Aida 14
    with 2 strands that is 1785. Dyer warns that complex projects get fewer stitches per
    skein; a converted image is one (many colours, frequent stops and starts), so the
    estimate allows 20% more thread per cross:

        floor(1785 / 1.2) = 1487 crosses on Aida 14

    which sits between Dyer's figure and the conservative planning figure of 1050-1200 on
    Aida 14 published at
    https://crossstitchstylearte.com/how-to-calculate-the-exact-amount-of-thread-needed-for-any-cross-stitch-project/
    erring towards more skeins.
    Thread per cross scales with 1 / fabric count, so the result is proportional to it.
    """
    check_fabric_count(fabric_count)
    usable_inches = SEGMENTS_PER_SKEIN * USABLE_INCHES_PER_SEGMENT * SKEIN_STRANDS
    inches_per_cross = CROSS_INCHES_TIMES_COUNT / fabric_count * STITCH_STRANDS
    return math.floor(usable_inches / inches_per_cross / (1 + COMPLEX_PROJECT_ALLOWANCE))


def skeins_needed(stitches: int, fabric_count: float) -> int:
    """Skeins for `stitches` full crosses: 0 for none, else rounded up (so at least 1)."""
    if stitches < 0:
        raise ValueError(f"stitch count must not be negative, got {stitches}")
    if stitches == 0:
        check_fabric_count(fabric_count)
        return 0
    return -(-stitches // stitches_per_skein(fabric_count))


@dataclass(frozen=True)
class KeyEntry:
    """One thread of the key with its stitch count and skein estimate."""

    thread: Thread
    stitches: int
    skeins: int


@dataclass(frozen=True, eq=False)
class Pattern:
    """A stitch grid on a fabric count.

    `grid` has shape (height, width); each cell is an index into `key` or `EMPTY`. The key
    is ordered by stitch count descending, ties by thread code (see `code_order`). Patterns
    compare by identity: compare grids with `np.array_equal` and keys with `==`.
    """

    grid: npt.NDArray[np.intp]
    key: tuple[KeyEntry, ...]
    fabric_count: float

    @property
    def height(self) -> int:
        return int(self.grid.shape[0])

    @property
    def width(self) -> int:
        return int(self.grid.shape[1])

    @property
    def total_stitches(self) -> int:
        return sum(entry.stitches for entry in self.key)

    @property
    def width_in(self) -> float:
        return self.width / self.fabric_count

    @property
    def height_in(self) -> float:
        return self.height / self.fabric_count

    @property
    def width_cm(self) -> float:
        return self.width_in * CM_PER_INCH

    @property
    def height_cm(self) -> float:
        return self.height_in * CM_PER_INCH


def code_order(code: str) -> tuple[int, int, str]:
    """Sort key for thread codes: numeric codes first by value, then the rest by name."""
    if code.isdigit():
        return (0, int(code), code)
    return (1, 0, code)


def build_pattern(
    cells: npt.NDArray[np.intp], threads: Sequence[Thread], fabric_count: float
) -> Pattern:
    """Build a pattern from a grid of indices into `threads` (or `EMPTY`).

    Threads that appear more than once in `threads` merge into one key entry, unused
    threads are dropped, and the key is ordered by stitch count descending, ties by code.
    """
    check_fabric_count(fabric_count)
    if cells.ndim != 2:
        raise ValueError(f"the grid must be 2-D, got shape {cells.shape}")
    unique_threads = list(dict.fromkeys(threads))
    merged = np.array([unique_threads.index(t) for t in threads], dtype=np.intp)
    stitched = cells != EMPTY
    counts = np.bincount(merged[cells[stitched]], minlength=len(unique_threads))
    order = sorted(
        (i for i in range(len(unique_threads)) if counts[i] > 0),
        key=lambda i: (-counts[i], code_order(unique_threads[i].code)),
    )
    position = np.full(len(unique_threads), EMPTY, dtype=np.intp)
    position[order] = np.arange(len(order))
    grid = np.full(cells.shape, EMPTY, dtype=np.intp)
    grid[stitched] = position[merged[cells[stitched]]]
    grid.flags.writeable = False
    key = tuple(
        KeyEntry(
            thread=unique_threads[i],
            stitches=int(counts[i]),
            skeins=skeins_needed(int(counts[i]), fabric_count),
        )
        for i in order
    )
    return Pattern(grid=grid, key=key, fabric_count=float(fabric_count))
