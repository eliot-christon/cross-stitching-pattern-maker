"""Hand edits of a pattern: thread replacements, strokes, rectangles and fills, applied in
order, each against the pattern the earlier ones left.

Coordinates are (x, y): the column, then the row, 0-based. A stroke, rectangle or fill
carries the (width, height) of the grid it was drawn on, and is skipped on a grid of any
other size, so an edit never lands on cells it was not drawn on. Cells off the grid are
clipped. A thread of `None` is bare fabric: painting with it erases.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cross_stitch.pattern.model import EMPTY, Pattern, build_pattern
from cross_stitch.threads import Thread

__all__ = ["Change", "Edited", "Fill", "Rect", "Replace", "Stroke", "edit_pattern"]

IntArray = npt.NDArray[np.intp]
BoolArray = npt.NDArray[np.bool_]
type Cell = tuple[int, int]
type Size = tuple[int, int]

_CHUNK = 1 << 20
"""Most line cells generated at once, so a long stroke never holds them all."""


@dataclass(frozen=True)
class Replace:
    """Every stitch on `old` moves to `new`; a `new` of `None` leaves them bare."""

    old: Thread
    new: Thread | None


@dataclass(frozen=True)
class Stroke:
    """A pencil (or, with no thread, eraser) stroke: successive `points` joined by straight
    8-connected lines, a `brush` x `brush` square (odd) centred on every cell of them."""

    thread: Thread | None
    brush: int
    grid: Size
    points: tuple[Cell, ...]


@dataclass(frozen=True)
class Rect:
    """Every cell of the box with corners `start` and `end`, both included, in any order."""

    thread: Thread | None
    grid: Size
    start: Cell
    end: Cell


@dataclass(frozen=True)
class Fill:
    """The zone of the value under `at`: the cells joined to it through the 4 neighbours
    sharing a side, bare fabric being one value. Sides only, because a stitcher reads a
    one-stitch diagonal line as a closed outline, and a fill must not leak through it."""

    thread: Thread | None
    grid: Size
    at: Cell


type Change = Replace | Stroke | Rect | Fill


@dataclass(frozen=True)
class Edited:
    """A pattern after its changes, and what each change did."""

    pattern: Pattern
    changed: tuple[int, ...]
    """One count per change, in order: the cells whose value it changed (0: nothing)."""


def edit_pattern(pattern: Pattern, changes: Sequence[Change]) -> Edited:
    """Apply `changes` in order, each against the pattern the earlier ones left.

    The result is rebuilt with `build_pattern`, so a thread outside the key joins it, a
    thread no cell keeps leaves it, the key is re-sorted and skeins follow the counts.
    `pattern` is not modified; with nothing changed it is returned as it is. A `Stroke`
    with no points or a brush that is not an odd number from 1 is a `ValueError`.
    """
    for change in changes:
        if isinstance(change, Stroke):
            _check_stroke(change)
    editor = _Editor(pattern)
    changed = tuple(editor.apply(change) for change in changes)
    if not any(changed):
        return Edited(pattern, changed)
    return Edited(editor.pattern(), changed)


def _check_stroke(stroke: Stroke) -> None:
    if not stroke.points:
        raise ValueError("a stroke needs at least one point")
    if stroke.brush < 1 or stroke.brush % 2 == 0:
        raise ValueError(f"the brush must be an odd number from 1, got {stroke.brush!r}")


@dataclass(frozen=True)
class _Area:
    """Cells of the grid a change covers: `mask` placed with its top-left cell at
    (`left`, `top`), inside the grid. Only that box is read or written."""

    left: int
    top: int
    mask: BoolArray

    @property
    def box(self) -> tuple[slice, slice]:
        height, width = self.mask.shape
        return slice(self.top, self.top + height), slice(self.left, self.left + width)


class _Editor:
    """A writable copy of a pattern's grid, over a list of threads that grows when a
    change paints a thread outside the key."""

    def __init__(self, pattern: Pattern) -> None:
        self.cells: IntArray = pattern.grid.copy()
        self.threads: list[Thread] = [entry.thread for entry in pattern.key]
        self.index: dict[Thread, int] = {thread: i for i, thread in enumerate(self.threads)}
        self.size: Size = (pattern.width, pattern.height)
        self.fabric_count = pattern.fabric_count

    def pattern(self) -> Pattern:
        return build_pattern(self.cells, self.threads, self.fabric_count)

    def value(self, thread: Thread | None) -> int:
        """The grid value of `thread`, adding it to the threads when it is new."""
        if thread is None:
            return EMPTY
        if thread not in self.index:
            self.index[thread] = len(self.threads)
            self.threads.append(thread)
        return self.index[thread]

    def apply(self, change: Change) -> int:
        """Apply one change; the cells whose value it changed."""
        if isinstance(change, Replace):
            if change.old not in self.index or change.old == change.new:
                return 0
            return self._paint(_Area(0, 0, self.cells == self.index[change.old]), change.new)
        if change.grid != self.size:
            return 0
        if isinstance(change, Stroke):
            area = _stroke_area(change, self.size)
        elif isinstance(change, Rect):
            area = _rect_area(change, self.size)
        else:
            area = _fill_area(self.cells, change.at)
        return 0 if area is None else self._paint(area, change.thread)

    def _paint(self, area: _Area, thread: Thread | None) -> int:
        value = self.value(thread)
        cells = self.cells[area.box]
        target = area.mask & (cells != value)
        cells[target] = value
        return int(np.count_nonzero(target))


@dataclass(frozen=True)
class _Lines:
    """The straight lines joining successive points, each with the range of its steps
    whose cell lies within bounds on the line's longer axis."""

    starts: IntArray
    deltas: IntArray
    steps: IntArray
    """max(|dx|, |dy|): one cell per step along the longer axis."""
    first: IntArray
    """The first step in bounds."""
    counts: IntArray
    """How many steps from `first` are in bounds (0: none)."""


def _lines(ends: IntArray, low: IntArray, high: IntArray) -> _Lines:
    """The lines joining successive `ends`, steps clipped on their longer axis. Along that
    axis step i is exactly i cells from the start, so the steps in bounds are one range."""
    starts, deltas = ends[:-1], np.diff(ends, axis=0)
    steps = np.abs(deltas).max(axis=1, initial=0)
    moving = steps > 0
    starts, deltas, steps = starts[moving], deltas[moving], steps[moving]
    axis = (np.abs(deltas[:, 1]) > np.abs(deltas[:, 0])).astype(np.intp)
    rows = np.arange(len(steps))
    start, forward = starts[rows, axis], deltas[rows, axis] > 0
    first = np.maximum(np.where(forward, low[axis] - start, start - high[axis]), 0)
    last = np.minimum(np.where(forward, high[axis] - start, start - low[axis]), steps - 1)
    return _Lines(starts, deltas, steps, first, np.maximum(last - first + 1, 0))


def _line_cells(
    points: Sequence[Cell], low: Cell, high: Cell
) -> Iterator[tuple[IntArray, IntArray]]:
    """The x and y of the cells of the straight 8-connected lines joining successive
    `points`, each point included, that lie between `low` and `high` (inclusive), a chunk
    at a time. A line of max(|dx|, |dy|) steps moves one cell per step along its longer
    axis and rounds the other, halves up. Only the steps in bounds on the longer axis are
    generated, so a line costs at most the size of the box, however far its ends lie."""
    ends = np.array(points, dtype=np.intp).reshape(-1, 2)
    bounds = np.array(low, dtype=np.intp), np.array(high, dtype=np.intp)
    lines = _lines(ends, *bounds)
    # A line's last cell is the next line's first, or the final point, added at the end.
    for chosen in _chunks(lines.counts):
        yield _inside(*_steps(lines, chosen), *bounds)
    yield _inside(ends[-1:, 0], ends[-1:, 1], *bounds)


def _chunks(counts: IntArray) -> Iterator[IntArray]:
    """The indices of the lines with cells, in groups of about `_CHUNK` cells each."""
    group = np.cumsum(counts) // _CHUNK
    for chunk in np.unique(group[counts > 0]):
        yield np.flatnonzero((group == chunk) & (counts > 0))


def _steps(lines: _Lines, chosen: IntArray) -> tuple[IntArray, IntArray]:
    """The cells of the in-bounds steps of the `chosen` lines."""
    counts = lines.counts[chosen]
    line = np.repeat(chosen, counts)
    i = lines.first[line] + np.arange(len(line)) - np.repeat(np.cumsum(counts) - counts, counts)
    n = lines.steps[line]
    xs = lines.starts[line, 0] + (2 * i * lines.deltas[line, 0] + n) // (2 * n)
    ys = lines.starts[line, 1] + (2 * i * lines.deltas[line, 1] + n) // (2 * n)
    return xs, ys


def _inside(xs: IntArray, ys: IntArray, low: IntArray, high: IntArray) -> tuple[IntArray, IntArray]:
    keep = (xs >= low[0]) & (xs <= high[0]) & (ys >= low[1]) & (ys <= high[1])
    return xs[keep], ys[keep]


def _stroke_area(stroke: Stroke, size: Size) -> _Area | None:
    """The cells a stroke covers, clipped to a grid of `size`."""
    width, height = size
    reach = stroke.brush // 2
    # Only centres whose square reaches the grid matter, and a line never leaves the box
    # of its ends: the centres lie in the points' box cut to the grid widened by `reach`.
    points = np.array(stroke.points, dtype=np.intp)
    left, top = (max(int(v), -reach) for v in points.min(axis=0))
    right = min(int(points[:, 0].max()), width + reach - 1)
    bottom = min(int(points[:, 1].max()), height + reach - 1)
    if left > right or top > bottom:
        return None
    # Mark the centres in that box padded by the brush's reach, then widen them along each
    # axis in turn: a square brush is a row of the brush's width swept down its height.
    box = np.zeros((bottom - top + 1 + 2 * reach, right - left + 1 + 2 * reach), dtype=bool)
    for xs, ys in _line_cells(stroke.points, (left, top), (right, bottom)):
        box[ys - top + reach, xs - left + reach] = True
    if not box.any():
        return None
    widened = _widen(_widen(box, reach, axis=1), reach, axis=0)
    return _clipped(widened, (left - reach, top - reach), size)


def _widen(box: BoolArray, reach: int, *, axis: int) -> BoolArray:
    """`box` with every set cell also setting the `reach` cells either side along `axis`."""
    widened = box.copy()
    for shift in range(1, min(reach, box.shape[axis] - 1) + 1):
        ahead = [slice(None)] * 2
        behind = [slice(None)] * 2
        ahead[axis], behind[axis] = slice(shift, None), slice(None, -shift)
        widened[tuple(ahead)] |= box[tuple(behind)]
        widened[tuple(behind)] |= box[tuple(ahead)]
    return widened


def _rect_area(rect: Rect, size: Size) -> _Area | None:
    """The cells of a rectangle, clipped to a grid of `size`."""
    (x0, y0), (x1, y1) = rect.start, rect.end
    left, top = min(x0, x1), min(y0, y1)
    box = np.ones((max(y0, y1) - top + 1, max(x0, x1) - left + 1), dtype=bool)
    return _clipped(box, (left, top), size)


def _clipped(box: BoolArray, corner: Cell, size: Size) -> _Area | None:
    """`box` with its top-left cell at `corner`, cut to a grid of `size`; `None` when
    nothing of it is on the grid."""
    width, height = size
    left, top = corner
    x_from, y_from = max(left, 0), max(top, 0)
    x_to, y_to = min(left + box.shape[1], width), min(top + box.shape[0], height)
    if x_from >= x_to or y_from >= y_to:
        return None
    return _Area(x_from, y_from, box[y_from - top : y_to - top, x_from - left : x_to - left])


def _fill_area(cells: IntArray, at: Cell) -> _Area | None:
    """The 4-connected zone of the value under `at`, bare fabric being one value; `None`
    when `at` is off the grid."""
    height, width = cells.shape
    x, y = at
    if not (0 <= x < width and 0 <= y < height):
        return None
    runs = _Runs(cells == cells[y, x])
    return runs.area(runs.zone(runs.at(x, y)))


class _Runs:
    """The runs of a boolean grid: the set cells side by side in one row, in reading order.

    Two runs on neighbouring rows sharing a column share a side, so a 4-connected zone
    grows run by run, never cell by cell."""

    def __init__(self, grid: BoolArray) -> None:
        self.height, self.width = grid.shape
        padded = np.zeros((self.height, self.width + 2), dtype=np.int8)
        padded[:, 1:-1] = grid
        edges = np.diff(padded, axis=1)
        self.rows, self.starts = np.nonzero(edges == 1)
        self.ends = np.nonzero(edges == -1)[1]  # one past each run, in the same order
        # Runs as positions in the grid read row after row, so one sorted search finds
        # the runs of any row overlapping any span.
        line = self.width + 2
        start_at, end_at = self.rows * line + self.starts, self.rows * line + self.ends
        self.neighbours: list[tuple[list[int], list[int]]] = []
        """For the row above, then below: the first and one past the last run overlapping
        each run (ending after its start, starting before its end)."""
        for step in (-1, 1):
            shifted = (self.rows + step) * line
            self.neighbours.append(
                (
                    np.searchsorted(end_at, shifted + self.starts, "right").tolist(),
                    np.searchsorted(start_at, shifted + self.ends, "left").tolist(),
                )
            )

    def at(self, x: int, y: int) -> int:
        """The run holding the set cell (x, y)."""
        line = self.width + 2
        return int(np.searchsorted(self.rows * line + self.starts, y * line + x, "right")) - 1

    def zone(self, seed: int) -> list[int]:
        """The runs joined to run `seed` through shared sides."""
        reached = {seed}
        pending = [seed]
        while pending:
            run = pending.pop()
            for first, last in self.neighbours:
                for other in range(first[run], last[run]):
                    if other not in reached:
                        reached.add(other)
                        pending.append(other)
        return sorted(reached)

    def area(self, chosen: list[int]) -> _Area:
        """The cells of the `chosen` runs, over the rows they span: +1 where each starts,
        -1 one past it, summed along each row (runs never share a start or an end)."""
        rows = self.rows[chosen]
        top = int(rows.min())
        marks = np.zeros((int(rows.max()) - top + 1, self.width + 1), dtype=np.int8)
        marks[rows - top, self.starts[chosen]] = 1
        marks[rows - top, self.ends[chosen]] = -1
        return _Area(0, top, np.cumsum(marks, axis=1, dtype=np.int8)[:, : self.width] > 0)
