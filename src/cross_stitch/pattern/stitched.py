"""Stitched renders: find the grid of stitches in a picture of cross stitch and reduce it.

A render or a face-on photo of finished cross stitch, or a screenshot of a chart, holds a
regular grid of cells, but its cells are not flat: each is a textured cross between dark
gaps, or a coloured square under a symbol. `find_pixel_grid` (pixel art) wants flat cells
and refuses them; this reader finds their grid from the light, not the colour:

1. **Profile:** the luminance change between neighbouring pixel lines, averaged over the
   other axis. Gaps between stitches and chart lines make it periodic.
2. **Pitch:** the frequency, from `MIN_STITCH_PITCH` to a size leaving `MIN_STITCHES`
   cells, where the profile lines up best (the same score as pixel art's: 1 when every
   change sits on the grid). A stitch's texture can line up better on a fraction of its
   pitch, so 2, 3 and 4 times the best pitch are candidates too when they score
   `SUBHARMONIC_SHARE` of it.
3. **Checks:** a pitch must score `MIN_STITCH_ALIGNMENT`, and the profile's mean change
   reach `MIN_EDGE_LEVEL` grey levels, which the faint 8-pixel blocks of a JPEG of a
   smooth picture do not. The mean luminance of each pixel line must itself repeat at the
   pitch (`MIN_LINE_ALIGNMENT`): gaps and lines darken whole lines of pixels, while a
   texture finer than the pixels (fabric weave) only shows at a false, folded pitch in
   the profile of changes, so a pitch that is such a fold of a finer, stronger texture is
   dropped too. Of the candidate pairs across and down that agree within
   `MAX_ANISOTROPY`, the smallest wins, unless a larger pair's lines repeat
   `LARGER_PITCH_MARGIN` times as strongly (a chart's bold line every ten cells must not
   pass for its cell).
4. **Phase:** of `PHASES` offsets on each axis, the one leaving the most pixels of the
   cells' central `CELL_SHARE` close to their cell's colour: gaps and lines fall between
   cells, a symbol stays inside one. A cell cut by the image's edge counts when at least
   half of it shows.

`unstitch` gives each cell the median colour of its central `CELL_SHARE`, so gaps, shading
and a thin symbol do not count. `fabric_weave` says whether an image with no stitch grid
shows a regular texture finer than a stitch instead (fabric photographed close, at an
angle), and `symbols_only` whether a grid's cells hold one colour under symbols (a chart
whose thread colours are only in its key). Everything is deterministic.
"""

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from PIL import Image

from cross_stitch.pattern.pixelart import PixelGrid, _centre_blocks, _refine, pixel_art_colours

__all__ = [
    "MIN_STITCH_PITCH",
    "fabric_weave",
    "find_stitch_grid",
    "symbols_only",
    "unstitch",
]

MIN_STITCH_PITCH = 3.0
"""Smallest stitch looked for, in image pixels; finer regular texture is fabric weave."""
MIN_WEAVE_PITCH = 2.2
"""Smallest weave looked for: finer, a profile peak is pixel noise at the sampling limit."""
MIN_STITCHES = 8
"""Fewest stitches across or down."""
MIN_STITCH_ALIGNMENT = 0.06
"""Lowest score (0-1) of the luminance changes lining up on the grid. On the local corpus,
stitched renders and chart screenshots score 0.06-0.91 (a photo of a hoop, cropped to the
stitching, the lowest), other photos 0.05 at most."""
MIN_EDGE_LEVEL = 4.0
"""Lowest mean luminance change (grey levels, 0-255) between neighbouring pixels."""
MIN_LINE_ALIGNMENT = 0.12
"""Lowest score of the lines' mean luminance repeating at the pitch, on each axis. On the
local corpus every grid found scores 0.20 or more; a fine weave folded into a false pitch
scores 0.08 at most."""
SUBHARMONIC_SHARE = 0.2
"""A multiple of the best pitch is a candidate when it scores this share of the best."""
LARGER_PITCH_MARGIN = 1.5
"""How many times as strongly a larger pair's lines must repeat to win over a smaller one."""
MAX_ANISOTROPY = 0.07
"""Largest relative difference between the pitch across and the pitch down."""
MIN_WEAVE_ALIGNMENT = 0.04
"""Lowest score, on both axes, of a texture finer than `MIN_STITCH_PITCH` for
`fabric_weave`. On the local corpus a photo of stitching at an angle scores 0.060 and
0.045, other photos 0.024 at most."""
CELL_SHARE = 0.6
"""Central part of a cell, on each axis, that gives its colour."""
UNIFORM_LEVELS = 48
"""Largest channel difference (0-255) from a cell's median still counted as its colour."""
PHASES = 12
"""Offsets tried on each axis for where the cells start."""
SYMBOL_SHARE = 0.1
"""Share of a cell's centre unlike its colour that makes it hold a symbol."""
MIN_SYMBOL_CELLS = 0.2
"""Share of cells holding a symbol for `symbols_only`."""

_PADDING = 8
_MULTIPLES = (2, 3, 4)
_FOLDS = (2, 3)  # harmonics of a fine texture that fold back into the stitch range
_FOLD_TOLERANCE = 0.03
_PHASE_LINES = 96  # pixel lines, evenly spread, that score an offset

FloatArray = npt.NDArray[np.float64]
ByteArray = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class _Pitch:
    pitch: float
    alignment: float
    lines: float = 0.0
    """How strongly the lines' mean luminance repeats at the pitch (`_line_alignment`)."""


def find_stitch_grid(image: Image.Image) -> PixelGrid | None:
    """The grid of stitches in `image`, or `None` when it has none (see the module
    docstring). Cells are `pitch_x` x `pitch_y` pixels, which may differ a little."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    luminance = _luminance(rgba)
    across = _stitch_pitches(luminance)
    down = _stitch_pitches(luminance.T)
    pairs = [
        (x, y)
        for x in across
        for y in down
        if abs(x.pitch - y.pitch) <= MAX_ANISOTROPY * max(x.pitch, y.pitch)
    ]
    if not pairs:
        return None
    pairs.sort(key=lambda pair: pair[0].pitch * pair[1].pitch)
    x, y = pairs[0]
    for larger_x, larger_y in pairs[1:]:
        if larger_x.lines + larger_y.lines >= LARGER_PITCH_MARGIN * (x.lines + y.lines):
            x, y = larger_x, larger_y
    origin_x = _best_origin(rgba, x.pitch)
    origin_y = _best_origin(np.swapaxes(rgba, 0, 1), y.pitch)
    columns = _cells(image.width, x.pitch, origin_x)
    rows = _cells(image.height, y.pitch, origin_y)
    if columns < MIN_STITCHES or rows < MIN_STITCHES:
        return None
    return PixelGrid(columns, rows, x.pitch, y.pitch, origin_x, origin_y)


def unstitch(image: Image.Image, grid: PixelGrid) -> Image.Image:
    """`image` reduced to one RGBA pixel per stitch of `grid`: the median of the central
    `CELL_SHARE` of each cell."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    blocks = _centre_blocks(rgba, grid, CELL_SHARE).astype(np.float64)
    median = np.median(blocks, axis=(2, 3))
    return Image.fromarray(np.rint(median).astype(np.uint8), mode="RGBA")


def fabric_weave(image: Image.Image) -> bool:
    """Whether `image` shows, on both axes, a regular texture finer than a stitch, as the
    weave of fabric photographed close does."""
    luminance = _luminance(np.asarray(image.convert("RGBA"), dtype=np.uint8))
    return all(
        _best_pitch(_profile(lines), MIN_WEAVE_PITCH, MIN_STITCH_PITCH, MIN_WEAVE_ALIGNMENT)
        is not None
        for lines in (luminance, luminance.T)
    )


def symbols_only(image: Image.Image, grid: PixelGrid) -> bool:
    """Whether the cells of `grid` are all one colour and many hold a symbol unlike it: a
    chart whose thread colours are only in its key."""
    if pixel_art_colours(unstitch(image, grid)) > 1:
        return False
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    blocks = _centre_blocks(rgba, grid, CELL_SHARE).astype(np.float64)
    median = np.median(blocks, axis=(2, 3), keepdims=True)
    unlike = np.abs(blocks - median).max(axis=4) > UNIFORM_LEVELS
    return bool((unlike.mean(axis=(2, 3)) >= SYMBOL_SHARE).mean() >= MIN_SYMBOL_CELLS)


def _luminance(rgba: ByteArray) -> FloatArray:
    """Rec. 601 luminance, transparent pixels as white (bare fabric shows no stitch)."""
    pixels = rgba.astype(np.float64)
    alpha = pixels[..., 3] / 255.0
    luma = pixels[..., :3] @ np.array([0.299, 0.587, 0.114])
    result: FloatArray = luma * alpha + 255.0 * (1.0 - alpha)
    return result


def _profile(luminance: FloatArray) -> FloatArray:
    """Mean luminance change between neighbouring columns: entry i is between columns i
    and i + 1."""
    result: FloatArray = np.abs(np.diff(luminance, axis=1)).mean(axis=0)
    return result


def _stitch_pitches(luminance: FloatArray) -> list[_Pitch]:
    """The stitch pitches the columns of `luminance` could repeat at: the best and its
    strong multiples, each repeating in the columns' mean luminance too and not a fold of
    a finer texture that lines up better."""
    profile = _profile(luminance)
    best = _best_pitch(profile, MIN_STITCH_PITCH, math.inf, MIN_STITCH_ALIGNMENT)
    if best is None:
        return []
    candidates = [best]
    for multiple in _MULTIPLES:
        pitch = best.pitch * multiple
        if (len(profile) + 1) / pitch < MIN_STITCHES:
            break
        frequency, alignment, _ = _refine(profile, 1 / pitch, _step(profile))
        if alignment >= SUBHARMONIC_SHARE * best.alignment:
            candidates.append(_Pitch(1 / frequency, alignment))
    fine = _best_pitch(profile, MIN_WEAVE_PITCH, MIN_STITCH_PITCH, 0.0)
    means = luminance.mean(axis=0)
    kept = []
    for candidate in candidates:
        lines = _line_alignment(means, candidate.pitch)
        folded = fine is not None and fine.alignment > candidate.alignment
        if lines >= MIN_LINE_ALIGNMENT and not (folded and _is_fold(candidate.pitch, fine)):
            kept.append(_Pitch(candidate.pitch, candidate.alignment, lines))
    return kept


def _is_fold(pitch: float, fine: _Pitch | None) -> bool:
    """Whether `pitch` is where a harmonic of the `fine` texture folds back to, sampled at
    one value per pixel."""
    if fine is None:
        return False
    for harmonic in _FOLDS:
        frequency = (harmonic / fine.pitch) % 1.0
        frequency = min(frequency, 1.0 - frequency)
        if frequency > 0 and abs(1 / frequency - pitch) <= _FOLD_TOLERANCE * pitch:
            return True
    return False


def _step(profile: FloatArray) -> float:
    """The frequency step of the padded spectrum of `profile`."""
    return 1 / (1 << math.ceil(math.log2(_PADDING * (len(profile) + 1))))


def _best_pitch(
    profile: FloatArray, min_pitch: float, max_pitch: float, min_alignment: float
) -> _Pitch | None:
    """The pitch from `min_pitch` to under `max_pitch` (and leaving `MIN_STITCHES` cells)
    that the profile lines up on best, if it scores `min_alignment` and the profile's mean
    change reaches `MIN_EDGE_LEVEL`."""
    length = len(profile) + 1
    if length < MIN_STITCHES * min_pitch or profile.mean() < MIN_EDGE_LEVEL:
        return None
    step = _step(profile)
    size = round(1 / step)
    score = np.abs(np.fft.rfft(profile - profile.mean(), n=size))
    low = max(math.ceil(MIN_STITCHES / length * size), math.floor(size / max_pitch) + 1)
    high = math.floor(size / min_pitch)
    if low >= high:
        return None
    peak = low + int(np.argmax(score[low : high + 1]))
    frequency, alignment, _ = _refine(profile, peak * step, step)
    return _Pitch(1 / frequency, alignment) if alignment >= min_alignment else None


def _line_alignment(means: FloatArray, pitch: float) -> float:
    """How strongly the lines' mean luminance repeats at `pitch` (0 not at all, about 1 for
    a clean repeat): its swing at that frequency over its mean swing, once a moving
    average over one pitch has taken out slower changes."""
    width = max(2, round(pitch))
    padded = np.pad(means, width, mode="edge")
    trend = np.convolve(padded, np.ones(width) / width, mode="same")[width:-width]
    swing = means - trend
    total = float(np.abs(swing).sum())
    if total <= 0:
        return 0.0
    positions = np.arange(len(means), dtype=np.float64)
    return 2 * float(np.abs(swing @ np.exp(-2j * np.pi * positions / pitch))) / total


def _cells(length: int, pitch: float, origin: float) -> int:
    """Cells from `origin` in `length` pixels, a last one counting when half of it shows."""
    return max(1, round((length - origin) / pitch))


def _best_origin(rgba: ByteArray, pitch: float) -> float:
    """Of `PHASES` offsets within one pitch, the one leaving the most uniform cells (see
    the module docstring), as an origin: before the image when the first cell shows at
    least half; the earliest offset on a tie."""
    picked = np.linspace(0, rgba.shape[0] - 1, min(_PHASE_LINES, rgba.shape[0])).astype(np.intp)
    lines = rgba[picked].astype(np.float64)
    offsets = np.arange(PHASES) * pitch / PHASES
    offset = float(offsets[int(np.argmax([_uniform(lines, o, pitch) for o in offsets]))])
    return offset - pitch if offset >= pitch / 2 else offset


def _uniform(lines: FloatArray, offset: float, pitch: float) -> float:
    """Share of the pixels of the cells' central `CELL_SHARE`, line by line, within
    `UNIFORM_LEVELS` of their segment's median, the cells starting at `offset`."""
    size = max(1, round(pitch * CELL_SHARE))
    count = max(1, math.floor((lines.shape[1] - offset) / pitch))
    first = np.floor(offset + (np.arange(count) + 0.5) * pitch - size / 2 + 0.5).astype(np.intp)
    columns = np.clip(first[:, np.newaxis] + np.arange(size), 0, lines.shape[1] - 1)
    segments = lines[:, columns]  # (lines, cells, size, 4)
    median = np.median(segments, axis=2, keepdims=True)
    return float((np.abs(segments - median).max(axis=3) <= UNIFORM_LEVELS).mean())
