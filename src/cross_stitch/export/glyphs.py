"""Measured facts about each chart symbol, as printed: its ink and how alike two look.

- **ink**: the fraction of a chart cell the symbol darkens, 0 to 1 (anti-aliased render
  at `PX_PER_MM`, no blur).
- **similarity**: for two symbols, sum(min) / sum(max) of their renders after a Gaussian
  blur of `BLUR_MM` (a weighted Jaccard score). 1 for a symbol with itself; high for
  near-identical silhouettes (two hollow diamond-like shapes); low for a filled and an
  outlined version of one shape, whose difference in ink is plain at a glance. A pair at
  or above `ALIKE` looks alike.

Renders use the chart's own geometry (`geometry.py`): the cell, the font and size, the
centring on the advance width and the baseline rise that `pdf.py` draws with.

The values live in `glyphs.json` next to this module, so nothing renders text at run time
and the same symbols always give the same numbers. Regenerate it with
`uv run python -m cross_stitch.export.glyphs` after changing `SYMBOLS`, the font or the
geometry; a test recomputes it and fails when the committed file has drifted.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from cross_stitch.export.geometry import CELL_MM, FONT_PATH, SYMBOL_CENTRING, SYMBOL_SIZE_PT

__all__ = [
    "ALIKE",
    "BLUR_MM",
    "OVERRIDES",
    "PX_PER_MM",
    "GlyphTable",
    "glyph_table",
    "measure",
    "render",
    "table_json",
]

PX_PER_MM = 16
"""Resolution of the measurement renders."""
BLUR_MM = 0.25
"""Standard deviation of the blur before comparing two symbols: small details (a dot, a
stroke's end) count for less than the silhouette, as they do for an eye at 3 mm."""
ALIKE = 0.5
"""A pair whose similarity is at or above this looks alike on the chart."""

OVERRIDES: dict[tuple[str, str], tuple[float, str]] = {
    ("@", "▤"): (0.3, "a round letter against a hatched square: alike only in ink"),
    ("@", "▥"): (0.3, "a round letter against a hatched square: alike only in ink"),
}
"""Pairs whose measured similarity the eye disagrees with: (a, b) -> (score, reason).
Applied on top of the measured matrix, in both orders."""

_TABLE = "glyphs.json"
_DECIMALS = 4
_POINT_MM = 25.4 / 72


@dataclass(frozen=True)
class GlyphTable:
    """The ink of each symbol and the similarity of every pair, in `symbols` order."""

    symbols: tuple[str, ...]
    ink: npt.NDArray[np.float64]
    """Shape (n,): ink of `symbols[i]`."""
    similarity: npt.NDArray[np.float64]
    """Shape (n, n), symmetric, 1 on the diagonal."""

    def index(self, symbol: str) -> int:
        """Position of `symbol` in the table; `ValueError` if it is not measured."""
        return self.symbols.index(symbol)


def _cell_px() -> int:
    return round(CELL_MM * PX_PER_MM)


def _padding_px() -> int:
    # Room for the blur's tail on every side, so no symbol is cut at the cell's edge.
    return math.ceil(3 * BLUR_MM * PX_PER_MM)


@cache
def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=SYMBOL_SIZE_PT * _POINT_MM * PX_PER_MM)


def render(symbol: str) -> npt.NDArray[np.float64]:
    """`symbol` drawn in a chart cell (plus padding), as darkness from 0 to 1."""
    cell, pad = _cell_px(), _padding_px()
    size_px = SYMBOL_SIZE_PT * _POINT_MM * PX_PER_MM
    image = Image.new("L", (cell + 2 * pad, cell + 2 * pad), 0)
    draw = ImageDraw.Draw(image)
    width = draw.textlength(symbol, font=_font())
    rise = (cell - size_px * SYMBOL_CENTRING) / 2
    draw.text(
        (pad + (cell - width) / 2, pad + cell - rise), symbol, fill=255, font=_font(), anchor="ls"
    )
    return np.asarray(image, dtype=np.float64) / 255


def _blurred(darkness: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    image = Image.fromarray(np.round(darkness * 255).astype(np.uint8), mode="L")
    blurred = image.filter(ImageFilter.GaussianBlur(BLUR_MM * PX_PER_MM))
    return np.asarray(blurred, dtype=np.float64).ravel() / 255


def measure(symbols: Sequence[str]) -> GlyphTable:
    """Render `symbols` and measure their ink and pairwise similarity (no overrides)."""
    renders = [render(symbol) for symbol in symbols]
    cell_area = _cell_px() ** 2
    ink = np.array([float(r.sum()) / cell_area for r in renders])
    blurred = np.stack([_blurred(r) for r in renders])
    similarity = np.ones((len(symbols), len(symbols)))
    for i, row in enumerate(blurred):
        lower = np.minimum(row, blurred).sum(axis=1)
        upper = np.maximum(row, blurred).sum(axis=1)
        similarity[i] = np.divide(lower, upper, out=np.ones_like(lower), where=upper > 0)
    similarity = (similarity + similarity.T) / 2
    np.fill_diagonal(similarity, 1.0)
    return GlyphTable(tuple(symbols), ink.round(_DECIMALS), similarity.round(_DECIMALS))


def table_json(table: GlyphTable) -> str:
    """The table as the text of `glyphs.json`."""
    data = {
        "px_per_mm": PX_PER_MM,
        "blur_mm": BLUR_MM,
        "symbols": list(table.symbols),
        "ink": table.ink.tolist(),
        "similarity": table.similarity.tolist(),
    }
    return json.dumps(data, ensure_ascii=False, indent=0) + "\n"


def _with_overrides(table: GlyphTable) -> GlyphTable:
    similarity = table.similarity.copy()
    for (a, b), (score, _reason) in OVERRIDES.items():
        i, j = table.index(a), table.index(b)
        similarity[i, j] = similarity[j, i] = score
    return GlyphTable(table.symbols, table.ink, similarity)


@cache
def glyph_table() -> GlyphTable:
    """The committed measurements, with `OVERRIDES` applied."""
    text = resources.files(__package__).joinpath(_TABLE).read_text(encoding="utf-8")
    data = json.loads(text)
    table = GlyphTable(
        tuple(data["symbols"]),
        np.array(data["ink"], dtype=np.float64),
        np.array(data["similarity"], dtype=np.float64),
    )
    return _with_overrides(table)


if __name__ == "__main__":
    from pathlib import Path

    from cross_stitch.export.symbols import SYMBOLS

    target = Path(__file__).with_name(_TABLE)
    target.write_text(table_json(measure(SYMBOLS)), encoding="utf-8")
    print(f"wrote {target}")
