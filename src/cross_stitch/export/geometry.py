"""The chart's printed geometry: what a symbol looks like on paper.

`pdf.py` draws with these values and `glyphs.py` measures symbols with them, so the
measurements describe the chart as printed. This module imports nothing from the package,
so both can read it without an import cycle.
"""

from pathlib import Path

FONT_PATH = Path(__file__).with_name("DejaVuSans.ttf")
"""The chart font, DejaVu Sans, shipped with the package (see `FONT_SOURCE.md`)."""

CELL_MM = 3.0
"""Side of one chart cell on paper, the same for every paper size."""

MIN_CELL_MM = 2.0
"""Smallest cell a chart split by pages may use: below it symbols stop being legible."""

MAX_CELL_MM = 6.0
"""Largest cell a chart split by pages may use, however few cells a page holds."""

SYMBOL_SIZE_PT = 6.5
"""Font size of a symbol in its cell, in points."""

SYMBOL_CENTRING = 0.7
"""A symbol is centred vertically as if it were this fraction of its font size tall: its
baseline sits (cell - SYMBOL_CENTRING * size) / 2 above the cell's bottom edge."""
