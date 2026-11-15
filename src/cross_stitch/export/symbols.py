"""Chart symbols: one per key entry, from one fixed list of 100.

`pattern_symbols` chooses each entry's symbol from the pattern itself:

- **neighbours first**: two entries that share many cell borders never get symbols that
  look alike on the chart (`glyphs.ALIKE`), whenever the list allows;
- **then tone**: darker threads get symbols with more ink and lighter threads lighter
  ones, so a black-and-white chart reads like a greyscale picture of the result.

The JSON response and every PDF chart read their symbols here, so a thread has one
symbol in the key, both chart variants and the page.

The list holds 100 single characters, as many as a pattern has colours at most. Every one
is in a Unicode block the chart font (DejaVu Sans) covers: Basic Latin, Latin-1
Supplement, Arrows, Mathematical Operators, Geometric Shapes. They stay told apart in
black and white at about 3 mm: at most one member of each look-alike family is in the
list (no O beside 0 or a circle, no I beside l or 1, no X beside a multiplication sign).
Changing the list changes every chart, and `glyphs.json` must be measured again.
"""

import numpy as np
import numpy.typing as npt

from cross_stitch.colour import srgb_to_lab
from cross_stitch.export.glyphs import ALIKE, glyph_table
from cross_stitch.pattern import EMPTY, Pattern

__all__ = ["SYMBOLS", "pattern_symbols"]

STRONG_SHARE = 0.01
"""Two entries are a strong pair when they share at least this share of all the borders
between two different stitched entries (and at least one border)."""

SYMBOLS: tuple[str, ...] = (
    # Filled and outlined shapes, then marks that read at a glance.
    *"\u25a0\u25a1\u25cf\u25cb\u25b2\u25b3\u25c6\u25c7\u25bc\u25bd",
    *"+\u00d7=#@%&?!",
    *"\u2190\u2191\u2192\u2193\u25d0\u25d1\u25b6\u25c0\u25b7\u25c1\u2295\u2297",
    # Capital letters and digits with no look-alike elsewhere in the list.
    *"ABCDEFHJKLMNPQRSTVWYZ",
    *"34679",
    # Operators, signs, arrows and shapes that differ by detail.
    *"\u00f7\u00b1\u2260\u2248\u2261\u221e\u221a\u2229\u222a\u00b6",
    *"\u229e\u22a0\u2234\u2194\u2195\u2196\u2197\u2198\u2199",
    *"\u25e7\u25e8\u25a4\u25a5\u25d2\u25d3\u25e2\u25e3\u25e4\u25e5",
    *"\u25ed\u25ee\u2205\u22c8\u21d2\u21af",
    # Lower-case letters unlike any capital, and the last few signs.
    *"aehrfd*<",
)


def _borders(grid: npt.NDArray[np.intp], entries: int) -> npt.NDArray[np.int64]:
    """Borders between each pair of entries: edges between two side-by-side or stacked
    cells holding different entries. Diagonal contact and bare fabric do not count."""
    counts = np.zeros(entries * entries, dtype=np.int64)
    for first, second in ((grid[:, :-1], grid[:, 1:]), (grid[:-1, :], grid[1:, :])):
        mask = (first != second) & (first != EMPTY) & (second != EMPTY)
        low = np.minimum(first[mask], second[mask])
        high = np.maximum(first[mask], second[mask])
        counts += np.bincount(low * entries + high, minlength=entries * entries)
    upper = counts.reshape(entries, entries)
    return upper + upper.T


def _targets(lightness: npt.NDArray[np.float64], symbols: int) -> npt.NDArray[np.float64]:
    """Each entry's wanted ink rank (0 = the lightest symbol): the lightest entry towards
    the lightest symbol, the darkest towards the heaviest, spread over the whole list."""
    entries = len(lightness)
    if entries == 1:
        return np.array([(100.0 - float(np.clip(lightness[0], 0, 100))) / 100 * (symbols - 1)])
    lightest_first = np.lexsort((np.arange(entries), -lightness))
    rank = np.empty(entries)
    rank[lightest_first] = np.arange(entries)
    return np.round(rank * (symbols - 1) / (entries - 1))


class _Assignment:
    """One assignment in progress: the facts it weighs and the symbol each entry holds."""

    def __init__(self, pattern: Pattern) -> None:
        entries = len(pattern.key)
        table = glyph_table()
        order = [table.index(symbol) for symbol in SYMBOLS]
        self.ink = table.ink[order]
        self.alike = table.similarity[np.ix_(order, order)] >= ALIKE
        self.ink_rank = np.empty(len(SYMBOLS))
        self.ink_rank[np.lexsort((np.arange(len(SYMBOLS)), self.ink))] = np.arange(len(SYMBOLS))
        rgb = np.array([entry.thread.rgb for entry in pattern.key], dtype=np.float64)
        self.lightness = srgb_to_lab(rgb)[:, 0]
        self.target = _targets(self.lightness, len(SYMBOLS))
        borders = _borders(pattern.grid, entries)
        strong = borders >= max(1.0, STRONG_SHARE * borders.sum() / 2)
        np.fill_diagonal(strong, False)
        self.weight = np.where(strong, borders, 0)
        self.symbol = np.full(entries, -1, dtype=np.intp)

    def clashes(self, entry: int, symbol: int) -> int:
        """Borders `entry` would share with strong neighbours whose symbol looks alike."""
        neighbours = np.flatnonzero((self.weight[entry] > 0) & (self.symbol >= 0))
        neighbours = neighbours[neighbours != entry]
        alike = self.alike[symbol, self.symbol[neighbours]]
        return int(self.weight[entry, neighbours][alike].sum())

    def choose(self) -> None:
        """Each entry takes the free symbol with fewest clashes, then nearest its tone.

        Entries with most strong borders choose first: they are the hardest to place.
        """
        entries = len(self.symbol)
        for entry in sorted(range(entries), key=lambda i: (-int(self.weight[i].sum()), i)):
            free = np.flatnonzero(~np.isin(np.arange(len(SYMBOLS)), self.symbol))
            clashes = np.array([self.clashes(entry, int(symbol)) for symbol in free])
            distance = np.abs(self.ink_rank[free] - self.target[entry])
            self.symbol[entry] = free[np.lexsort((free, distance, clashes))[0]]

    def untangle(self) -> None:
        """Swap pairs whose tone is inverted, whenever the swap adds no clash.

        Each swap of an inverted pair removes at least one inversion, so this ends.
        """
        entries = len(self.symbol)
        changed = True
        while changed:
            changed = False
            for first in range(entries):
                for second in range(first + 1, entries):
                    changed = self._swap_if_better(first, second) or changed

    def _swap_if_better(self, first: int, second: int) -> bool:
        a, b = int(self.symbol[first]), int(self.symbol[second])
        if (self.lightness[first] - self.lightness[second]) * (self.ink[a] - self.ink[b]) <= 0:
            return False
        before = self.clashes(first, a) + self.clashes(second, b)
        self.symbol[first], self.symbol[second] = b, a
        if self.clashes(first, b) + self.clashes(second, a) > before:
            self.symbol[first], self.symbol[second] = a, b
            return False
        return True


def pattern_symbols(pattern: Pattern) -> list[str]:
    """One symbol per key entry, in key order, all distinct and from `SYMBOLS`.

    The rules, in priority order:

    1. Two entries forming a strong pair (sharing at least `STRONG_SHARE` of all borders
       between different stitched entries, and at least one) never get two symbols scoring
       `glyphs.ALIKE` or more, whenever the list allows; when it does not, the entries
       with most strong borders (summed over their pairs) choose first.
    2. Tone: thread lightness is CIELAB L*. The lightest entry aims at the lightest symbol
       and the darkest at the heaviest, spread over the whole list; where rule 1 does not
       bind, a darker thread never gets a lighter symbol than a lighter thread.
    3. Deterministic: ties go to the earlier key entry (of two equally light threads, the
       earlier aims at the lighter symbol), then the earlier `SYMBOLS` place.
       The result depends only on the threads, their key order and the border counts.

    Raises `ValueError` for a key longer than the list.
    """
    entries = len(pattern.key)
    if entries > len(SYMBOLS):
        raise ValueError(f"a key has at most {len(SYMBOLS)} entries; this one has {entries}")
    if entries == 0:
        return []
    assignment = _Assignment(pattern)
    assignment.choose()
    assignment.untangle()
    return [SYMBOLS[symbol] for symbol in assignment.symbol]
