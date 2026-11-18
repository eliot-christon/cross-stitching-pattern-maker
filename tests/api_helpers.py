"""Helpers shared by the API tests: generated uploads, and the JSON the API should give
for a core pattern, written out here rather than taken from the API's own code.
`conftest.py` registers this module for pytest's assertion rewriting."""

import io
from typing import Any

import numpy as np
from PIL import Image

from cross_stitch.export import pattern_symbols, symbol_ink
from cross_stitch.pattern import EMPTY, Pattern, convert_image
from cross_stitch.threads import dmc_thread

type Pixel = tuple[int, int]

STRIPE_CODES = ["310", "Blanc", "321", "797"]
"""The stripes image, 40 x 20: 310 in columns 0-9, Blanc 10-19, 321 20-29, 797 30-39."""

CLEANUP_FORM = {"merge_distance": "3", "min_stitches": "5", "confetti_size": "1"}
"""All three cleanup settings on, as the forms of the cleanup tests send them."""


ADJUSTMENT_LIMITS: dict[str, dict[str, float]] = {
    "brightness": {"min": -100, "max": 100, "step": 1, "default": 0},
    "contrast": {"min": -100, "max": 100, "step": 1, "default": 0},
    "saturation": {"min": -100, "max": 100, "step": 1, "default": 0},
    "hue": {"min": -180, "max": 180, "step": 1, "default": 0},
    "gamma": {"min": 0.25, "max": 4, "step": 0.05, "default": 1},
    "sharpness": {"min": -100, "max": 100, "step": 1, "default": 0},
}
"""The image adjustments as `GET /limits` reports them, in its order."""


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def stripes() -> Image.Image:
    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    for i, code in enumerate(STRIPE_CODES):
        pixels[:, i * 10 : (i + 1) * 10] = dmc_thread(code).rgb
    return Image.fromarray(pixels)


def field_image(shape: Pixel, marks: dict[Pixel, str]) -> Image.Image:
    """An image of `shape` (height, width) pixels in DMC 797 (royal blue), with each pixel
    of `marks`, (row, column) -> DMC code, in that thread's colour."""
    pixels = np.full((*shape, 3), dmc_thread("797").rgb, dtype=np.uint8)
    for pixel, code in marks.items():
        pixels[pixel] = dmc_thread(code).rgb
    return Image.fromarray(pixels)


def cleanable() -> Image.Image:
    """8 x 12 royal blue with work for each cleanup step: two 3 x 3 blocks of near-identical
    greys (3799 and 844) to merge, one white (Blanc) pixel of confetti, and a red (321)
    domino too small for `min_stitches` 5 but too large for `confetti_size` 1."""
    marks = {(1, 2): "Blanc", (1, 8): "321", (1, 9): "321"}
    for row in range(4, 7):
        marks |= {(row, column): "3799" for column in range(1, 4)}
        marks |= {(row, column): "844" for column in range(6, 9)}
    return field_image((8, 12), marks)


def core_converted(image: Image.Image, max_colours: int) -> Pattern:
    """The core's conversion of `image` at its own width, on Aida 14."""
    return convert_image(image, width=image.width, max_colours=max_colours, fabric_count=14)


def grid_json(pattern: Pattern) -> list[list[int | None]]:
    return [[None if cell == EMPTY else cell for cell in row] for row in pattern.grid.tolist()]


def key_json(pattern: Pattern) -> list[dict[str, Any]]:
    symbols = pattern_symbols(pattern)
    return [
        {
            "code": entry.thread.code,
            "name": entry.thread.name,
            "rgb": list(entry.thread.rgb),
            "stitches": entry.stitches,
            "skeins": entry.skeins,
            "symbol": symbol,
            "symbol_ink": symbol_ink(entry.thread.rgb),
        }
        for entry, symbol in zip(pattern.key, symbols, strict=True)
    ]
