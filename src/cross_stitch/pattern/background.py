"""The background of a pattern made bare fabric: a picture's plain surround is not stitched."""

import numpy as np

from cross_stitch.pattern.confetti import _cluster_labels, _padded
from cross_stitch.pattern.model import EMPTY, Pattern, build_pattern

__all__ = ["background_as_fabric"]


def background_as_fabric(pattern: Pattern) -> Pattern:
    """The pattern with its background as bare fabric.

    The background is the value most frequent among the border cells, each counted once,
    bare fabric counting as a value. If that is bare fabric, or bare fabric ties with it,
    nothing changes; a tie between threads goes to the earlier key entry. Every cell of
    the background's thread joined to the border through the 4 neighbours sharing a side
    becomes bare fabric, so a background never leaks through a one-cell diagonal outline
    and the same thread inside the subject (an eye) stays stitched. The result is rebuilt
    with `build_pattern`, so counts and skeins follow; `pattern` is not modified.
    """
    grid = pattern.grid
    if grid.size == 0:
        return pattern
    border = np.zeros(grid.shape, dtype=bool)
    border[[0, -1], :] = True
    border[:, [0, -1]] = True
    values, counts = np.unique(grid[border], return_counts=True)
    leaders = values[counts == counts.max()]
    if EMPTY in leaders:
        return pattern
    background = int(leaders.min())

    padded = _padded(grid)
    labels = _cluster_labels(padded, diagonals=False).reshape(padded.shape)[1:-1, 1:-1]
    touching = np.unique(labels[border & (grid == background)])
    cells = np.where(np.isin(labels, touching) & (grid == background), EMPTY, grid)
    return build_pattern(cells, [entry.thread for entry in pattern.key], pattern.fabric_count)
