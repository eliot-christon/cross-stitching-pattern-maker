"""Pattern cleanup: merge threads a stitcher cannot tell apart, fold rare threads into
others, cap the number of threads, and `clean_pattern`, which runs those steps and
confetti removal in a fixed order.

Every step rewrites which thread each key entry's cells use and hands the grid back to
`build_pattern`, so counts, skeins and key order follow from the grid. Colours are compared
thread to thread in CIEDE2000; no thread outside the input's key ever appears.
"""

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cross_stitch.colour import delta_e_2000_matrix, srgb_to_lab
from cross_stitch.pattern.confetti import isolated_stitches, remove_confetti
from cross_stitch.pattern.model import Pattern, build_pattern
from cross_stitch.threads import nearest_indices

__all__ = [
    "CLEANUP_HEADROOM",
    "CleanedPattern",
    "clean_pattern",
    "colours_with_headroom",
    "limit_threads",
    "merge_similar_threads",
    "prune_rare_threads",
]

CLEANUP_HEADROOM = 1.5
"""How many times the threads asked for (rounded up) a conversion takes when it is cleaned
afterwards: cleanup removes threads, and `limit_threads` brings the count back to the one
asked for. More headroom survives harsher cleanup but slows k-means down in proportion."""


def colours_with_headroom(max_colours: int) -> int:
    """The threads to convert with when the pattern will be cleaned and capped at
    `max_colours` (see `CLEANUP_HEADROOM`)."""
    return math.ceil(max_colours * CLEANUP_HEADROOM)


@dataclass(frozen=True)
class CleanedPattern:
    """A cleaned pattern, the pattern it was cleaned from (`converted`, the same object),
    and the isolated stitches (see `isolated_stitches`) of each."""

    pattern: Pattern
    converted: Pattern
    isolated_before: int
    isolated_after: int


def clean_pattern(
    pattern: Pattern,
    *,
    merge_distance: float,
    min_stitches: int,
    confetti_size: int,
    max_colours: int | None = None,
) -> CleanedPattern:
    """Merge similar threads, remove confetti, prune rare threads, then cap the threads at
    `max_colours` (`limit_threads`; `None` is no cap).

    In that order every guarantee holds on the result: later steps only remove threads, so
    no two entries are closer than `merge_distance`; pruning and capping move whole entries,
    which only joins clusters, so no cluster of at most `confetti_size` cells with a
    neighbour comes back; and they only add stitches to the entries they keep, so none is
    under `min_stitches` unless it is the only one. Every setting at 0 and no cap (or a cap
    the key already meets) return the pattern unchanged.
    """
    merged = merge_similar_threads(pattern, merge_distance=merge_distance)
    cleaned = prune_rare_threads(
        remove_confetti(merged, max_size=confetti_size), min_stitches=min_stitches
    )
    if max_colours is not None:
        cleaned = limit_threads(cleaned, max_colours)
    return CleanedPattern(
        pattern=cleaned,
        converted=pattern,
        isolated_before=isolated_stitches(pattern),
        isolated_after=isolated_stitches(cleaned),
    )


def merge_similar_threads(pattern: Pattern, *, merge_distance: float) -> Pattern:
    """Merge key entries closer than `merge_distance` (CIEDE2000) into one another.

    While some pair of entries is strictly under `merge_distance`, the closest pair merges
    (ties: the pair whose earlier member comes first in the key, then the other member's
    position). The entry with more stitches, counted after the merges so far, keeps its
    thread and takes every cell of the other; equal counts go to the earlier entry.
    Survivors keep their colour, so distances are always between threads of the input's
    key. `merge_distance` 0 returns the pattern unchanged.
    """
    if not (math.isfinite(merge_distance) and merge_distance >= 0):
        raise ValueError(f"merge distance must be a finite number >= 0, got {merge_distance!r}")
    if merge_distance == 0 or len(pattern.key) < 2:
        return pattern
    return _merge_closest(pattern, under=merge_distance)


def limit_threads(pattern: Pattern, count: int) -> Pattern:
    """Merge key entries into one another until at most `count` remain.

    The merge is `merge_similar_threads`'s, with no distance bound: the closest pair
    (CIEDE2000) merges first, into the entry with more stitches. A key of at most `count`
    entries returns the pattern unchanged. Raises `ValueError` if `count` < 1.
    """
    if count < 1:
        raise ValueError(f"the thread count must be at least 1, got {count!r}")
    if len(pattern.key) <= count:
        return pattern
    return _merge_closest(pattern, until=count)


def prune_rare_threads(pattern: Pattern, *, min_stitches: int) -> Pattern:
    """Move every entry with fewer than `min_stitches` stitches onto its nearest kept entry.

    Kept entries are those with at least `min_stitches` stitches in the input, and always
    the first key entry, so a threshold above every count leaves a one-thread pattern. Each
    other entry takes the kept thread nearest to its own in CIEDE2000 (ties to the earlier
    key entry). Counts are read once from the input, so a pruned entry is never a target and
    the order of processing does not matter. No cell becomes bare fabric. `min_stitches` 0
    or 1 returns the pattern unchanged.
    """
    if min_stitches < 0:
        raise ValueError(f"min stitches must be >= 0, got {min_stitches!r}")
    if not pattern.key:
        return pattern
    kept = [0] + [i for i, entry in enumerate(pattern.key) if i and entry.stitches >= min_stitches]
    if len(kept) == len(pattern.key):
        return pattern
    lab = srgb_to_lab([entry.thread.rgb for entry in pattern.key])
    nearest = nearest_indices(lab, lab[kept])
    owner = [i if i in kept else kept[int(nearest[i])] for i in range(len(pattern.key))]
    return _reassign(pattern, owner)


def _reassign(pattern: Pattern, owner: list[int]) -> Pattern:
    """The pattern with each key entry i's cells on the thread of entry `owner[i]`."""
    threads = [pattern.key[o].thread for o in owner]
    return build_pattern(np.asarray(pattern.grid), threads, pattern.fabric_count)


def _merge_closest(pattern: Pattern, *, under: float = math.inf, until: int = 0) -> Pattern:
    """Merge the closest pair of entries, again and again, while some pair is strictly
    closer than `under` and more than `until` entries remain (see the callers)."""
    lab = srgb_to_lab([entry.thread.rgb for entry in pattern.key])
    owner = _merge_owners(
        delta_e_2000_matrix(lab, lab), [entry.stitches for entry in pattern.key], under, until
    )
    return _reassign(pattern, owner)


def _merge_owners(
    distances: npt.NDArray[np.float64], counts: list[int], under: float, until: int
) -> list[int]:
    """For each key entry, the entry whose thread it ends up using (see `_merge_closest`)."""
    # Only pairs (i, j) with i < j that are under the distance are candidates.
    candidate = np.triu(distances < under, k=1)
    owner = list(range(len(counts)))
    remaining = len(counts)
    while remaining > until and candidate.any():
        rows, cols = np.nonzero(candidate)  # row-major: ties fall to (earlier i, earlier j)
        pick = int(np.argmin(distances[rows, cols]))
        first, second = int(rows[pick]), int(cols[pick])
        survivor, merged = (second, first) if counts[second] > counts[first] else (first, second)
        counts[survivor] += counts[merged]
        counts[merged] = 0
        owner = [survivor if o == merged else o for o in owner]
        candidate[merged, :] = False
        candidate[:, merged] = False
        remaining -= 1
    return owner
