"""Images of cross stitch drawn in code, for the stitched reader's tests."""

import io

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageFilter

from cross_stitch.threads import dmc_thread

ART_COLUMNS, ART_ROWS = 20, 15
THREADS = ("321", "797", "702", "444")
"""Four DMC threads far apart: red, blue, green, yellow."""
PALETTE = np.array([dmc_thread(code).rgb for code in THREADS], dtype=np.float64)


def art(seed: int = 3, columns: int = ART_COLUMNS, rows: int = ART_ROWS) -> npt.NDArray[np.intp]:
    """A seeded `rows` x `columns` grid of indices into `THREADS`, every thread used."""
    cells = np.random.default_rng(seed).integers(0, len(THREADS), size=(rows, columns))
    cells.flat[: len(THREADS)] = np.arange(len(THREADS))
    return cells.astype(np.intp)


FloatArray = npt.NDArray[np.float64]


def _local(length: int, pitch: float) -> tuple[npt.NDArray[np.intp], FloatArray]:
    """For each pixel on one axis, its cell and its position inside it (0-1)."""
    position = (np.arange(length, dtype=np.float64) + 0.5) / pitch
    return np.floor(position).astype(np.intp), np.mod(position, 1.0)


def _cell_colours(
    cells: npt.NDArray[np.intp], pitch_x: float, pitch_y: float, palette: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Each pixel's thread colour, and its position inside its cell across and down."""
    rows, columns = cells.shape
    cx, u = _local(round(columns * pitch_x), pitch_x)
    cy, v = _local(round(rows * pitch_y), pitch_y)
    colour = palette[cells[np.minimum(cy, rows - 1)][:, np.minimum(cx, columns - 1)]]
    uu, vv = np.meshgrid(u, v)
    return colour, uu, vv


def stitched(
    cells: npt.NDArray[np.intp],
    pitch_x: float,
    pitch_y: float | None = None,
    *,
    palette: FloatArray = PALETTE,
    band: bool = False,
) -> Image.Image:
    """`cells` drawn as cross stitches: in each cell two shaded diagonal strokes in its
    thread's colour (their median shade the colour itself) over dark gaps, seeded noise,
    a slight blur. `band` adds a bright horizontal band across the middle of every stitch
    (energy at half the pitch down)."""
    colour, uu, vv = _cell_colours(cells, pitch_x, pitch_x if pitch_y is None else pitch_y, palette)
    stroke = np.minimum(np.abs(uu - vv), np.abs(uu + vv - 1))
    shade = np.where(stroke < 0.3, 1.05 - 0.16 * stroke / 0.3, 0.8)
    gap = (uu < 0.1) | (uu > 0.9) | (vv < 0.1) | (vv > 0.9)
    pixels = colour * np.where(gap, 0.25, shade)[..., np.newaxis]
    if band:
        pixels = np.where(((vv > 0.45) & (vv < 0.55))[..., np.newaxis], pixels + 90, pixels)
    pixels += np.random.default_rng(7).normal(0, 6, pixels.shape)
    image = Image.fromarray(np.clip(np.rint(pixels), 0, 255).astype(np.uint8))
    return image.filter(ImageFilter.GaussianBlur(0.6))


def chart(cells: npt.NDArray[np.intp], pitch: float, palette: FloatArray = PALETTE) -> Image.Image:
    """`cells` as a chart screenshot: flat coloured cells, thin grey lines, a black plus
    sign in each cell."""
    pixels, uu, vv = _cell_colours(cells, pitch, pitch, palette)
    line = (uu < 1 / pitch) | (vv < 1 / pitch)
    plus = ((np.abs(uu - 0.5) < 0.07) & (np.abs(vv - 0.5) < 0.25)) | (
        (np.abs(vv - 0.5) < 0.07) & (np.abs(uu - 0.5) < 0.25)
    )
    pixels[line] = (150, 150, 150)
    pixels[plus] = (0, 0, 0)
    return Image.fromarray(pixels.astype(np.uint8))


def smooth(width: int = 320, height: int = 240) -> FloatArray:
    """A smooth colour image: gentle gradients, no edges."""
    x = np.linspace(0, 1, width)[np.newaxis, :]
    y = np.linspace(0, 1, height)[:, np.newaxis]
    return np.stack(
        [
            120 + 80 * x + 0 * y,
            100 + 60 * np.sin(3 * y) + 0 * x,
            140 + 50 * x * y,
        ],
        axis=-1,
    )


def weave(period: float = 2.7) -> Image.Image:
    """A smooth image under a fine weave of `period` pixels: threads across and down, each
    a bright band over a darker shadow (not a pure sine), slightly blurred."""
    base = smooth()
    height, width = base.shape[:2]
    across = (np.mod(np.arange(width) / period, 1.0) < 0.6)[np.newaxis, :]
    down = (np.mod(np.arange(height) / period, 1.0) < 0.6)[:, np.newaxis]
    texture = 20.0 * across + 20.0 * down - 20.0
    pixels = np.clip(base + texture[..., np.newaxis], 0, 255).astype(np.uint8)
    return Image.fromarray(pixels).filter(ImageFilter.GaussianBlur(0.4))


def jpeg(quality: int = 50) -> Image.Image:
    """The smooth image saved as JPEG: its 8-pixel blocks are its only regular pattern."""
    buffer = io.BytesIO()
    Image.fromarray(smooth().astype(np.uint8)).save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def gradient() -> Image.Image:
    ramp = np.linspace(0, 255, 320).astype(np.uint8)
    return Image.fromarray(np.tile(ramp, (240, 1)))


def noise() -> Image.Image:
    rng = np.random.default_rng(11)
    return Image.fromarray(rng.integers(0, 256, size=(240, 320, 3), dtype=np.uint8))


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
