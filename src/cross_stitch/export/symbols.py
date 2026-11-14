"""Chart symbols: one per key entry, assigned by position from one fixed list.

Entry 0 of a key (the thread with most stitches) takes `SYMBOLS[0]`, entry 1 takes
`SYMBOLS[1]`, and so on; the thread itself plays no part. The JSON response and the PDF
chart both take their symbols from `key_symbols`, so they cannot disagree.

The list holds 100 single characters, as many as a pattern has colours at most. Every one
is in a Unicode block the chart font (DejaVu Sans) covers: Basic Latin, Latin-1
Supplement, Arrows, Mathematical Operators, Geometric Shapes. They stay told apart in
black and white at about 3 mm: at most one member of each look-alike family is in the
list (no O beside 0 or a circle, no I beside l or 1, no X beside a multiplication sign),
and the most distinct shapes come first, so small keys get the clearest symbols.
Changing the list changes every chart.
"""

from collections.abc import Sequence

from cross_stitch.pattern import KeyEntry

__all__ = ["SYMBOLS", "key_symbols"]

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


def key_symbols(key: Sequence[KeyEntry]) -> list[str]:
    """The symbol of each key entry, in key order: entry i gets `SYMBOLS[i]`.

    Raises `ValueError` for a key longer than the list, which is never padded or wrapped.
    """
    if len(key) > len(SYMBOLS):
        raise ValueError(f"a key has at most {len(SYMBOLS)} entries; this one has {len(key)}")
    return list(SYMBOLS[: len(key)])
