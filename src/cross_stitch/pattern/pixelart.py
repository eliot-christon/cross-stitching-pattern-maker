"""Pixel art: find the grid of art pixels in an image and reduce the image to it.

Pixel art is often shared enlarged, by a whole or a fractional factor, sometimes smoothed
at the edges and saved as JPEG. Converting it as a picture blurs its pixels into each
other; reduced to one pixel per art pixel first, every art pixel becomes one stitch.

`find_pixel_grid` locates the grid on each axis from where the colour edges fall:

1. **Edges:** the colour change between each pair of neighbouring pixel lines, summed
   over the other axis (alpha included), so a boundary of art pixels is a peak.
2. **Pitch:** for every candidate pitch from `MIN_PITCH` to a size that leaves
   `MIN_ART_PIXELS` art pixels, how well the edges line up on one grid of that pitch: the
   length of the edge-weighted mean of `exp(2 pi i x / pitch)` (1 when every edge sits on
   the grid, near 0 for edges spread anywhere). A grid's sub-multiples line up as well, so
   the largest pitch scoring within `HARMONIC_TOLERANCE` of the best wins; it is then
   refined, and its phase gives where the grid lines fall.
3. **Checks:** the score must reach `MIN_ALIGNMENT`, the pitches across and down must agree
   within `SQUARE_TOLERANCE` (art pixels are square), and once reduced, the centre of each
   art pixel must be close to one colour (`MIN_UNIFORM_CELLS`), which a photo whose only
   regular pattern is its JPEG blocks fails.

An image with no such grid, at most `MAX_NATIVE_SIZE` on each side, of at most
`MAX_NATIVE_COLOURS` exact colours and mostly flat (`MIN_NATIVE_FLAT` of its neighbouring
pixels the same colour, which a smooth gradient is not) is pixel art at its own size
(pitch 1). Everything
is deterministic: no randomness, no threshold that depends on the machine.
"""

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from PIL import Image

from cross_stitch.colour import delta_e_2000, srgb_to_lab
from cross_stitch.pattern.convert import OPAQUE_THRESHOLD

__all__ = [
    "MAX_NATIVE_COLOURS",
    "MAX_NATIVE_SIZE",
    "PixelGrid",
    "find_pixel_grid",
    "pixel_art_colours",
    "unscale_pixel_art",
]

MIN_PITCH = 2.0
"""Smallest enlargement looked for: below it an image is at its own size or not pixel art."""
MIN_ART_PIXELS = 8
"""Fewest art pixels a pixel art has across or down."""
MIN_ALIGNMENT = 0.5
"""Lowest score (0-1) of the edges lining up on the grid."""
HARMONIC_TOLERANCE = 0.85
"""A larger pitch wins over a better-scoring smaller one if it scores this share of it."""
MIN_UNIFORM_CELLS = 0.85
"""Share of the art pixels whose centre must be one colour, within `UNIFORM_LEVELS`."""
UNIFORM_LEVELS = 32
"""Largest channel difference (0-255) from an art pixel's colour still counted as it."""
SQUARE_TOLERANCE = 0.05
"""Largest relative difference between the pitch across and the pitch down."""
MAX_NATIVE_SIZE = 1000
MAX_NATIVE_COLOURS = 256
MIN_NATIVE_FLAT = 0.5
"""Share of neighbouring pixel pairs of the same colour in pixel art at its own size."""
MIN_COLOUR_PIXELS = 3
"""Fewest art pixels a colour covers to count as one of the art's colours."""
SAME_COLOUR = 5.0
"""CIEDE2000 under which two colours of a pixel art count as one (compression noise)."""

_PADDING = 8  # the spectrum is sampled 8 times finer than the image's length
_REFINE_STEPS = 65
_ROW_CHUNK = 256

FloatArray = npt.NDArray[np.float64]
ByteArray = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class PixelGrid:
    """The grid of art pixels in an image: `columns` x `rows` cells, each `pitch_x` x
    `pitch_y` image pixels, the first starting at (`origin_x`, `origin_y`), which may be
    outside the image by less than half a cell."""

    columns: int
    rows: int
    pitch_x: float
    pitch_y: float
    origin_x: float
    origin_y: float


@dataclass(frozen=True)
class _Axis:
    pitch: float
    origin: float
    cells: int


def find_pixel_grid(image: Image.Image) -> PixelGrid | None:
    """The grid of art pixels of `image`, or `None` if it is not pixel art (see the module
    docstring)."""
    pixels = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    across = _find_axis(_edges(pixels))
    down = _find_axis(_edges(np.swapaxes(pixels, 0, 1)))
    if across is not None or down is not None:
        # An axis with no edge at all (stripes) takes the other axis's pitch: square pixels.
        width, height = image.width, image.height
        across = across or _flat_axis(width, down)
        down = down or _flat_axis(height, across)
        if across is not None and down is not None and _square(across, down):
            grid = PixelGrid(
                across.cells, down.cells, across.pitch, down.pitch, across.origin, down.origin
            )
            if _uniform_share(pixels, grid) >= MIN_UNIFORM_CELLS:
                return grid
    if _native(image):
        return PixelGrid(image.width, image.height, 1.0, 1.0, 0.0, 0.0)
    return None


def unscale_pixel_art(image: Image.Image, grid: PixelGrid) -> Image.Image:
    """`image` reduced to one RGBA pixel per art pixel of `grid`: the median of the centre
    of each cell, so smoothed edges and compression noise between cells do not count."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    median = np.median(_centre_blocks(rgba, grid).astype(np.float64), axis=(2, 3))
    return Image.fromarray(np.rint(median).astype(np.uint8), mode="RGBA")


def pixel_art_colours(image: Image.Image) -> int:
    """The colours of the stitched (mostly opaque) pixels of an unscaled pixel art, as
    many as a stitcher would tell apart and the art really uses: taken from the most to
    the least frequent, a colour within `SAME_COLOUR` (CIEDE2000) of one already counted
    joins it, and a colour (with those joining it) on fewer than `MIN_COLOUR_PIXELS` art
    pixels is a leftover of smoothing, not counted. At least 1 when anything is stitched."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
    opaque = rgba[rgba[:, 3] >= OPAQUE_THRESHOLD][:, :3]
    if len(opaque) == 0:
        return 0
    colours, counts = np.unique(opaque, axis=0, return_counts=True)
    order = np.argsort(-counts, kind="stable")
    lab = srgb_to_lab(colours[order])
    leaders = lab[:0]
    pixels: list[int] = []
    for colour, count in zip(lab, counts[order], strict=True):
        near = np.flatnonzero(delta_e_2000(colour, leaders) < SAME_COLOUR)
        if len(near):
            pixels[int(near[0])] += int(count)
        else:
            leaders = np.vstack([leaders, colour])
            pixels.append(int(count))
    return max(1, sum(1 for total in pixels if total >= MIN_COLOUR_PIXELS))


def _premultiplied(rgba: ByteArray) -> FloatArray:
    """RGBA as floats, colour scaled by alpha, so a transparent pixel's colour is ignored."""
    pixels = rgba.astype(np.float64)
    pixels[..., :3] *= pixels[..., 3:] / 255.0
    return pixels


def _edges(rgba: ByteArray) -> FloatArray:
    """Colour change between neighbouring columns, summed over rows and channels: entry i
    is the edge between columns i and i + 1, at x = i + 1. Rows are taken a chunk at a
    time, so a large image is never held as floats whole."""
    total = np.zeros(rgba.shape[1] - 1)
    for start in range(0, rgba.shape[0], _ROW_CHUNK):
        chunk = _premultiplied(rgba[start : start + _ROW_CHUNK])
        total += np.abs(np.diff(chunk, axis=1)).sum(axis=(0, 2))
    return total


def _find_axis(edges: FloatArray) -> _Axis | None:
    """The grid on one axis from its edge profile, or `None` (see the module docstring)."""
    length = len(edges) + 1
    if edges.sum() <= 0 or length < MIN_ART_PIXELS * MIN_PITCH:
        return None
    peak = _peak_frequency(edges)
    if peak is None:
        return None
    frequency, alignment, phase = _refine(edges, *peak)
    if alignment < MIN_ALIGNMENT:
        return None
    pitch = 1 / frequency
    first_line = (phase / (2 * math.pi) * pitch) % pitch
    # A sliver of a cell at the start counts as a cell when at least half of it shows.
    origin = first_line - pitch if first_line >= pitch / 2 else first_line
    return _Axis(pitch, origin, max(1, round((length - origin) / pitch)))


def _peak_frequency(edges: FloatArray) -> tuple[float, float] | None:
    """The lowest frequency (largest pitch) whose score is a peak within
    `HARMONIC_TOLERANCE` of the best, and the spectrum's step; `None` when even the best
    is under `MIN_ALIGNMENT`."""
    length = len(edges) + 1
    size = 1 << math.ceil(math.log2(_PADDING * length))
    score = np.abs(np.fft.rfft(edges, n=size)) / edges.sum()
    low = math.ceil(MIN_ART_PIXELS / length * size)  # the largest pitch: MIN_ART_PIXELS cells
    high = math.floor(size / MIN_PITCH)
    if low >= high:
        return None
    best = float(score[low : high + 1].max())
    if best < MIN_ALIGNMENT:
        return None
    # Neighbours outside the window count too, so its ends can be peaks.
    k = next(
        k
        for k in range(low, high + 1)
        if score[k] >= HARMONIC_TOLERANCE * best
        and score[k] >= score[k - 1]
        and (k + 1 >= len(score) or score[k] >= score[k + 1])
    )
    return k / size, 1 / size


def _refine(edges: FloatArray, frequency: float, step: float) -> tuple[float, float, float]:
    """The frequency near `frequency` (within `step`) whose edges line up best: it, its
    score and the phase of the grid lines."""
    positions = np.arange(1, len(edges) + 1, dtype=np.float64)
    candidates = np.linspace(frequency - step, frequency + step, _REFINE_STEPS)
    sums = np.exp(2j * np.pi * np.outer(candidates, positions)) @ edges
    best = int(np.argmax(np.abs(sums)))
    alignment = float(np.abs(sums[best]) / edges.sum())
    return float(candidates[best]), alignment, float(np.angle(sums[best]))


def _square(across: _Axis, down: _Axis) -> bool:
    return abs(across.pitch - down.pitch) <= SQUARE_TOLERANCE * max(across.pitch, down.pitch)


def _flat_axis(length: int, other: _Axis | None) -> _Axis | None:
    """An axis with no edge: cut into cells of the other axis's pitch."""
    if other is None:
        return None
    return _Axis(other.pitch, 0.0, max(1, round(length / other.pitch)))


def _centre_indices(
    cells: int, pitch: float, origin: float, limit: int, share: float = 0.5
) -> npt.NDArray[np.intp]:
    """For each cell on one axis, the pixel indices of its centre: `share` of a cell (half
    by default), at least one pixel, clipped to the image's `limit` pixels."""
    size = max(1, round(pitch * share))
    centres = origin + (np.arange(cells) + 0.5) * pitch
    first = np.floor(centres - size / 2 + 0.5).astype(np.intp)
    indices: npt.NDArray[np.intp] = np.clip(first[:, np.newaxis] + np.arange(size), 0, limit - 1)
    return indices


def _centre_blocks(rgba: ByteArray, grid: PixelGrid, share: float = 0.5) -> ByteArray:
    """The central `share` of every cell on each axis: shape (rows, columns, ky, kx, 4)."""
    xs = _centre_indices(grid.columns, grid.pitch_x, grid.origin_x, rgba.shape[1], share)
    ys = _centre_indices(grid.rows, grid.pitch_y, grid.origin_y, rgba.shape[0], share)
    blocks: ByteArray = rgba[ys[:, np.newaxis, :, np.newaxis], xs[np.newaxis, :, np.newaxis, :]]
    return blocks


def _uniform_share(pixels: ByteArray, grid: PixelGrid) -> float:
    """Share of the cells whose centre pixels are all within `UNIFORM_LEVELS` of its
    median colour."""
    blocks = _premultiplied(_centre_blocks(pixels, grid))
    median = np.median(blocks, axis=(2, 3), keepdims=True)
    spread = np.abs(blocks - median).max(axis=(2, 3, 4))
    return float(np.mean(spread <= UNIFORM_LEVELS))


def _native(image: Image.Image) -> bool:
    """Whether `image` is small and of few colours, as pixel art at its own size is."""
    if image.width > MAX_NATIVE_SIZE or image.height > MAX_NATIVE_SIZE:
        return False
    if image.convert("RGBA").getcolors(MAX_NATIVE_COLOURS) is None:
        return False
    pixels = np.asarray(image.convert("RGBA"))
    same_across = np.all(pixels[:, 1:] == pixels[:, :-1], axis=-1)
    same_down = np.all(pixels[1:] == pixels[:-1], axis=-1)
    pairs = same_across.size + same_down.size
    flat = int(same_across.sum() + same_down.sum())
    return pairs > 0 and flat >= MIN_NATIVE_FLAT * pairs
