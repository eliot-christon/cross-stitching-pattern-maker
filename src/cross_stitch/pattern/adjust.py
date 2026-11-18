"""Tone and colour adjustments of an image before it is read: brightness, contrast,
saturation, hue, gamma and sharpness. Image in, image out; alpha is never changed, so a
cell that is bare fabric stays bare fabric."""

from dataclasses import dataclass, fields

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageEnhance

__all__ = ["Adjustments", "adjust_image"]

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Adjustments:
    """The six adjustments; the defaults change nothing.

    `brightness`, `contrast`, `saturation` and `sharpness` are percentages from -100 to
    100: -100 gives black, one flat colour, greys and a softened image; 100 doubles the
    effect's factor. `hue` turns every colour around the HSV colour wheel, in degrees.
    `gamma` above 1 lightens the mid-tones, below 1 darkens them; black and white stay."""

    brightness: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    hue: float = 0.0
    gamma: float = 1.0
    sharpness: float = 0.0

    @property
    def neutral(self) -> bool:
        """Whether every value is its default, so the image is left untouched."""
        return all(getattr(self, field.name) == field.default for field in fields(Adjustments))


def adjust_image(image: Image.Image, adjustments: Adjustments) -> Image.Image:
    """`image` with `adjustments` applied, in this order: brightness, contrast, gamma (the
    tones), then saturation and hue (the colours), then sharpness (the edges).

    All neutral returns `image` itself. Otherwise the result is RGBA when `image` has
    transparency, with its alpha unchanged, and RGB when it has none."""
    if adjustments.neutral:
        return image
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    rgba = image.convert("RGBA")
    rgb = rgba.convert("RGB")
    rgb = _enhance(ImageEnhance.Brightness, rgb, adjustments.brightness)
    rgb = _enhance(ImageEnhance.Contrast, rgb, adjustments.contrast)
    if adjustments.gamma != 1.0:
        rgb = rgb.point(_gamma_table(adjustments.gamma) * 3)
    rgb = _enhance(ImageEnhance.Color, rgb, adjustments.saturation)
    if adjustments.hue % 360:
        rgb = _rotate_hue(rgb, adjustments.hue)
    rgb = _sharpen(rgb, adjustments.sharpness)
    if not has_alpha:
        return rgb
    rgb.putalpha(rgba.getchannel("A"))
    return rgb


def _enhance(
    enhancer: type[ImageEnhance.Brightness]
    | type[ImageEnhance.Contrast]
    | type[ImageEnhance.Color]
    | type[ImageEnhance.Sharpness],
    image: Image.Image,
    percent: float,
) -> Image.Image:
    """`image` through a Pillow enhancer at factor 1 + percent / 100 (1 is unchanged)."""
    if percent == 0:
        return image
    return enhancer(image).enhance(1 + percent / 100)


def _sharpen(image: Image.Image, percent: float) -> Image.Image:
    """`image` (RGB) through Pillow's sharpness enhancer, with its edge pixels repeated
    around it first: Pillow's 3 x 3 filters leave the outermost ring as it is, which would
    draw a false edge one pixel inside the border."""
    if percent == 0:
        return image
    padded = Image.fromarray(np.pad(np.asarray(image), ((1, 1), (1, 1), (0, 0)), mode="edge"))
    sharpened = _enhance(ImageEnhance.Sharpness, padded, percent)
    return sharpened.crop((1, 1, image.width + 1, image.height + 1))


def _gamma_table(gamma: float) -> list[int]:
    """The 256 levels mapped through v ** (1 / gamma), on 0-1."""
    levels = np.arange(256) / 255
    return [int(v) for v in np.rint(255 * levels ** (1 / gamma))]


def _rotate_hue(image: Image.Image, degrees: float) -> Image.Image:
    """`image` (RGB) with every hue turned by `degrees` in HSV, saturation and value kept,
    in floating point so turning back gives the original within rounding."""
    rgb: FloatArray = np.asarray(image, dtype=np.float64) / 255
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    value = rgb.max(axis=-1)
    chroma = value - rgb.min(axis=-1)
    safe = np.where(chroma == 0, 1.0, chroma)
    hue = np.where(
        value == r,
        ((g - b) / safe) % 6,
        np.where(value == g, (b - r) / safe + 2, (r - g) / safe + 4),
    )
    hue = (hue + degrees / 60) % 6
    # HSV -> RGB: each channel from its offset on the six-sector wheel.
    channels = [
        value - chroma * np.clip(np.minimum(k, 4 - k), 0, 1)
        for k in ((5 + hue) % 6, (3 + hue) % 6, (1 + hue) % 6)
    ]
    out = np.rint(np.stack(channels, axis=-1) * 255).astype(np.uint8)
    return Image.fromarray(out)
