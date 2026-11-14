"""Confetti: small clusters of one thread inside other colours, tedious to stitch.

A cluster is a set of cells of one key entry connected through their 8 neighbours (a
diagonal step is an ordinary move on the back of the fabric). Its neighbours are the
stitched cells outside it among its cells' 8 neighbours, each counted once; bare fabric
and the grid edge are not neighbours.
"""

import numpy as np
import numpy.typing as npt

from cross_stitch.colour import delta_e_2000_matrix, srgb_to_lab
from cross_stitch.pattern.model import EMPTY, Pattern, build_pattern

__all__ = ["isolated_stitches", "remove_confetti"]

IntArray = npt.NDArray[np.intp]


def isolated_stitches(pattern: Pattern) -> int:
    """How many stitched cells have no 8-neighbour of the same key entry."""
    padded = _padded(pattern.grid)
    centre = padded[1:-1, 1:-1]
    height, width = centre.shape
    has_twin = np.zeros(centre.shape, dtype=bool)
    for row in range(3):
        for col in range(3):
            if (row, col) != (1, 1):
                has_twin |= padded[row : row + height, col : col + width] == centre
    return int(np.count_nonzero((centre != EMPTY) & ~has_twin))


def remove_confetti(pattern: Pattern, *, max_size: int) -> Pattern:
    """Merge every cluster of at most `max_size` cells into the thread around it.

    A cluster with at least one neighbour takes the key entry held by the most neighbour
    cells; ties go to the entry nearest in CIEDE2000 to the cluster's thread, then to the
    earlier key entry. Clusters are handled smallest first, ties in reading order of their
    first cell, each against the grid as earlier merges left it, until no cluster of at
    most `max_size` cells has a neighbour. Bare fabric is never filled and no stitch becomes
    bare, so a cluster with no neighbour stays. `max_size` 0 returns the pattern unchanged.
    """
    if max_size < 0:
        raise ValueError(f"max size must be >= 0, got {max_size!r}")
    if max_size == 0 or len(pattern.key) < 2:
        return pattern
    padded = _padded(pattern.grid)
    lab = srgb_to_lab([entry.thread.rgb for entry in pattern.key])
    merger = _Merger(padded, max_size)
    merger.run(delta_e_2000_matrix(lab, lab).tolist())
    cells = np.array(merger.entry, dtype=np.intp).reshape(padded.shape)[1:-1, 1:-1]
    return build_pattern(cells, [entry.thread for entry in pattern.key], pattern.fabric_count)


def _padded(grid: IntArray) -> IntArray:
    """The grid inside a one-cell border of bare fabric, so every cell has 8 neighbours."""
    padded = np.full((grid.shape[0] + 2, grid.shape[1] + 2), EMPTY, dtype=np.intp)
    padded[1:-1, 1:-1] = grid
    return padded


def _cluster_labels(padded: IntArray) -> IntArray:
    """Flat label per cell of `padded`: the smallest flat index (so the first cell in
    reading order) of its 8-connected same-entry cluster, or `EMPTY` for bare fabric.

    Union-find in numpy: each round hooks the larger of two linked roots under the smaller
    one, then pointer jumping flattens every tree, until no link joins two roots.
    """
    flat = padded.ravel()
    parent = np.arange(flat.size, dtype=np.intp)
    width = padded.shape[1]
    firsts, seconds = [], []
    for step in (1, width - 1, width, width + 1):  # right, down-left, down, down-right
        linked = np.nonzero((flat[:-step] == flat[step:]) & (flat[:-step] != EMPTY))[0]
        firsts.append(linked)
        seconds.append(linked + step)
    first, second = np.concatenate(firsts), np.concatenate(seconds)
    while first.size:
        root_a, root_b = parent[first], parent[second]
        apart = root_a != root_b
        first, second = first[apart], second[apart]
        root_a, root_b = root_a[apart], root_b[apart]
        np.minimum.at(parent, np.maximum(root_a, root_b), np.minimum(root_a, root_b))
        jumped = parent[parent]
        while not np.array_equal(jumped, parent):
            parent, jumped = jumped, jumped[jumped]
    parent[flat == EMPTY] = EMPTY
    return parent


class _Merger:  # pylint: disable=too-few-public-methods
    """The grid, flat and padded, with its clusters, while confetti is merged away.

    A cluster is known by its label, the flat index of its first cell in reading order.
    Only clusters of at most `max_size` cells are tracked cell by cell; a larger one only
    needs to be known as larger, since it never shrinks.
    """

    def __init__(self, padded: IntArray, max_size: int) -> None:
        labels = _cluster_labels(padded)
        stitched = labels != EMPTY
        sizes = np.bincount(labels[stitched], minlength=labels.size)
        self.entry: list[int] = padded.ravel().tolist()
        self.label: list[int] = labels.tolist()
        self.size: list[int] = sizes.tolist()
        self.max_size = max_size
        width = padded.shape[1]
        self.steps = (-width - 1, -width, -width + 1, -1, 1, width - 1, width, width + 1)
        self.members: dict[int, list[int]] = {}
        self.buckets: dict[int, list[int]] = {}
        small = np.nonzero(stitched & (sizes[np.where(stitched, labels, 0)] <= max_size))[0]
        small = small[np.argsort(labels[small], kind="stable")]
        for cluster in np.split(small, np.nonzero(np.diff(labels[small]))[0] + 1):
            if cluster.size:
                self._track(int(cluster[0]), cluster.tolist())

    def _track(self, label: int, cells: list[int]) -> None:
        self.buckets.setdefault(len(cells), []).append(label)
        if len(cells) > 1:
            self.members[label] = cells

    def run(self, distances: list[list[float]]) -> None:
        """Merge clusters, smallest first, then by first cell, until none can be.

        `distances[i][j]` is the CIEDE2000 distance between key entries i and j.
        """
        # A merge only ever makes a bigger cluster, so the smallest bucket left is complete
        # by the time it is taken.
        while self.buckets:
            size = min(self.buckets)
            for label in sorted(self.buckets.pop(size)):
                if self.label[label] == label and self.size[label] == size:
                    self._merge(label, distances)

    def _merge(self, label: int, distances: list[list[float]]) -> None:
        """Give the cluster `label` to its neighbours' entry, if it has neighbours."""
        cells = self.members.pop(label, [label])
        if len(cells) == 1:
            around = [label + step for step in self.steps]
        else:
            around = list({cell + step for cell in cells for step in self.steps} - set(cells))
        votes: dict[int, int] = {}
        for cell in around:
            if self.entry[cell] != EMPTY:
                votes[self.entry[cell]] = votes.get(self.entry[cell], 0) + 1
        if not votes:
            self.members[label] = cells  # no neighbour: the cluster stays as it is
            return
        to_own = distances[self.entry[label]]
        target = min(votes, key=lambda entry: (-votes[entry], to_own[entry], entry))
        for cell in cells:
            self.entry[cell] = target
        joined = {self.label[cell] for cell in around if self.entry[cell] == target}
        large = [other for other in joined if self.size[other] > self.max_size]
        for other in joined:
            if self.size[other] <= self.max_size:
                cells.extend(self.members.pop(other, [other]))
        new = large[0] if large else min(cells)
        for cell in cells:
            self.label[cell] = new
        if not large:
            self.size[new] = len(cells)
            if len(cells) <= self.max_size:
                self._track(new, cells)
