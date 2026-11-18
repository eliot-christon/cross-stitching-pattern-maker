"""Helpers shared by the API tests: generated uploads, and the limits the API reports for
the settings several test files check. `conftest.py` registers this module for pytest's
assertion rewriting."""

import io

import numpy as np
from PIL import Image

from cross_stitch.threads import dmc_thread

STRIPE_CODES = ["310", "Blanc", "321", "797"]
"""The stripes image, 40 x 20: 310 in columns 0-9, Blanc 10-19, 321 20-29, 797 30-39."""


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
