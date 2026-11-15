"""Thread replacement: swap threads of a pattern for other threads, cell for cell."""

from collections.abc import Sequence
from dataclasses import dataclass

from cross_stitch.pattern.model import Pattern, build_pattern
from cross_stitch.threads import Thread

__all__ = ["Replaced", "replace_threads"]


@dataclass(frozen=True)
class Replaced:
    """A pattern after its replacements, and the positions of the pairs that did nothing."""

    pattern: Pattern
    ignored: tuple[int, ...]
    """0-based positions, ascending, of the pairs whose `from` was not in the pattern."""


def replace_threads(pattern: Pattern, replacements: Sequence[tuple[Thread, Thread]]) -> Replaced:
    """Apply `(from, to)` pairs in sequence: each moves every stitch currently on `from` to
    `to`, against the pattern the earlier pairs left.

    A pair whose `from` is not in the pattern at that point is ignored and reported. The
    result is rebuilt with `build_pattern`, so a `to` already in the key merges with it
    (stitches add up, the key is re-sorted, skeins follow the counts). Bare fabric stays
    bare, and no thread appears other than the key's and the `to`s. `pattern` is not
    modified.
    """
    threads = [entry.thread for entry in pattern.key]
    ignored: list[int] = []
    for position, (old, new) in enumerate(replacements):
        if old not in threads:
            ignored.append(position)
            continue
        threads = [new if thread == old else thread for thread in threads]
    if not threads:
        return Replaced(pattern, tuple(ignored))
    return Replaced(build_pattern(pattern.grid, threads, pattern.fabric_count), tuple(ignored))
