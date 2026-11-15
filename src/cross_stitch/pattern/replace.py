"""Thread replacement: swap threads of a pattern for other threads, or for bare fabric,
cell for cell."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cross_stitch.pattern.model import EMPTY, Pattern, build_pattern
from cross_stitch.threads import Thread

__all__ = ["Replaced", "replace_threads"]


@dataclass(frozen=True)
class Replaced:
    """A pattern after its replacements, and the positions of the pairs that did nothing."""

    pattern: Pattern
    ignored: tuple[int, ...]
    """0-based positions, ascending, of the pairs whose `from` was not in the pattern."""


def replace_threads(
    pattern: Pattern, replacements: Sequence[tuple[Thread, Thread | None]]
) -> Replaced:
    """Apply `(from, to)` pairs in sequence: each moves every stitch currently on `from` to
    `to`, against the pattern the earlier pairs left. A `to` of `None` removes `from`: its
    cells become bare fabric.

    A pair whose `from` is not in the pattern at that point is ignored and reported. The
    result is rebuilt with `build_pattern`, so a `to` already in the key merges with it
    (stitches add up, the key is re-sorted, skeins follow the counts). Bare fabric stays
    bare, and no thread appears other than the key's and the `to`s. `pattern` is not
    modified.
    """
    threads: list[Thread | None] = [entry.thread for entry in pattern.key]
    ignored: list[int] = []
    for position, (old, new) in enumerate(replacements):
        if old not in threads:
            ignored.append(position)
            continue
        threads = [new if thread == old else thread for thread in threads]
    if all(thread is not None for thread in threads) and len(ignored) == len(replacements):
        return Replaced(pattern, tuple(ignored))
    return Replaced(_rebuilt(pattern, threads), tuple(ignored))


def _rebuilt(pattern: Pattern, threads: Sequence[Thread | None]) -> Pattern:
    """The pattern with key entry i's cells on `threads[i]`, bare fabric where it is None."""
    kept = [i for i, thread in enumerate(threads) if thread is not None]
    position = np.full(len(threads) + 1, EMPTY, dtype=np.intp)  # the last slot maps EMPTY
    position[kept] = np.arange(len(kept))
    cells = position[np.where(pattern.grid == EMPTY, len(threads), pattern.grid)]
    return build_pattern(
        cells, [thread for thread in threads if thread is not None], pattern.fabric_count
    )
