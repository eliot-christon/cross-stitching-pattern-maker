"""Key cleanup: merge threads a stitcher cannot tell apart.

Every step rewrites which thread each key entry's cells use and hands the grid back to
`build_pattern`, so counts, skeins and key order follow from the grid. Colours are compared
thread to thread in CIEDE2000; no thread outside the input's key ever appears.
"""

import math

import numpy as np
import numpy.typing as npt

from cross_stitch.colour import delta_e_2000_matrix, srgb_to_lab
from cross_stitch.pattern.model import Pattern, build_pattern

__all__ = ["merge_similar_threads"]


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
    lab = srgb_to_lab([entry.thread.rgb for entry in pattern.key])
    owner = _merge_owners(
        delta_e_2000_matrix(lab, lab),
        [entry.stitches for entry in pattern.key],
        merge_distance,
    )
    return _reassign(pattern, owner)


def _reassign(pattern: Pattern, owner: list[int]) -> Pattern:
    """The pattern with each key entry i's cells on the thread of entry `owner[i]`."""
    threads = [pattern.key[o].thread for o in owner]
    return build_pattern(np.asarray(pattern.grid), threads, pattern.fabric_count)


def _merge_owners(
    distances: npt.NDArray[np.float64], counts: list[int], merge_distance: float
) -> list[int]:
    """For each key entry, the entry whose thread it ends up using (see the caller)."""
    # Only pairs (i, j) with i < j that are under the distance are candidates.
    candidate = np.triu(distances < merge_distance, k=1)
    owner = list(range(len(counts)))
    while candidate.any():
        rows, cols = np.nonzero(candidate)  # row-major: ties fall to (earlier i, earlier j)
        pick = int(np.argmin(distances[rows, cols]))
        first, second = int(rows[pick]), int(cols[pick])
        survivor, merged = (second, first) if counts[second] > counts[first] else (first, second)
        counts[survivor] += counts[merged]
        counts[merged] = 0
        owner = [survivor if o == merged else o for o in owner]
        candidate[merged, :] = False
        candidate[:, merged] = False
    return owner
