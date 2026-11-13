"""Image -> DMC pattern: resize to the stitch grid, quantise in Lab, snap to DMC threads.

Steps, all deterministic for a given image and settings:

1. **Resize** to `width` stitches with Pillow's BOX filter (area averaging: each cell is
   the mean of the pixels it covers). Height = round-half-up(width * image height / image
   width), at least 1. Upscaling is allowed. Pillow averages RGBA premultiplied by alpha,
   so a transparent pixel never tints the colour of a cell.
2. **Transparency**: a cell whose averaged alpha is below `OPAQUE_THRESHOLD` (128, i.e.
   mostly transparent) is `EMPTY`: bare fabric, no key entry, not a stitch.
3. **Quantise** the stitched cells with k-means in CIELAB. When there are no more
   distinct colours than `max_colours`, each distinct colour is its own cluster.
   Otherwise the distinct colours are grouped into bins of 5 bits per RGB channel (at
   most 32768), each bin standing for its cell-weighted mean Lab colour. With no more
   bins than `max_colours` those means are the centroids; otherwise weighted k-means runs
   on them, weighted by cell count. Binning bounds the work for photos with up to a
   million distinct colours.
   Initial centroids come from k-means++ with a fixed seed; assignment uses Euclidean
   distance in Lab, the distance whose minimiser is the cluster mean. Each cell then
   takes the centroid nearest to its own colour. No dithering.
4. **Snap** each centroid to its nearest DMC thread (CIEDE2000); centroids that land on
   the same thread merge into one key entry (`build_pattern`).
"""

import numpy as np
import numpy.typing as npt
from PIL import Image

from cross_stitch.colour import srgb_to_lab
from cross_stitch.pattern.model import EMPTY, Pattern, build_pattern, check_fabric_count
from cross_stitch.threads import nearest_dmc_lab

__all__ = ["OPAQUE_THRESHOLD", "convert_image"]

OPAQUE_THRESHOLD = 128
"""Lowest averaged alpha (0-255) of a stitched cell; below it the cell is empty."""

_SEED = 0
_MAX_ITERATIONS = 30
_TOLERANCE = 0.05
_CHUNK = 8192
_BIN_SHIFT = 3  # 8-bit channels -> 5-bit bins

FloatArray = npt.NDArray[np.float64]
IndexArray = npt.NDArray[np.intp]


def convert_image(
    image: Image.Image, *, width: int, max_colours: int, fabric_count: float = 14.0
) -> Pattern:
    """Convert a decoded image into a DMC pattern `width` stitches wide.

    Uses at most `max_colours` threads (fewer when centroids share a thread or the image
    has fewer colours). `fabric_count` is in stitches per inch. Raises `ValueError` if
    `width` < 1, `max_colours` < 1, `fabric_count` is not a positive number, or the image
    has no pixels.
    """
    if width < 1:
        raise ValueError(f"width must be at least 1 stitch, got {width}")
    if max_colours < 1:
        raise ValueError(f"max colours must be at least 1, got {max_colours}")
    check_fabric_count(fabric_count)
    if image.width < 1 or image.height < 1:
        raise ValueError(f"the image is empty ({image.width}x{image.height} pixels)")

    rgba = image.convert("RGBA")
    height = max(1, (2 * width * rgba.height + rgba.width) // (2 * rgba.width))
    cells = np.asarray(rgba.resize((width, height), Image.Resampling.BOX), dtype=np.uint8)

    stitched = cells[..., 3] >= OPAQUE_THRESHOLD
    colours, inverse, counts = np.unique(
        cells[stitched][:, :3], axis=0, return_inverse=True, return_counts=True
    )
    grid = np.full((height, width), EMPTY, dtype=np.intp)
    if len(colours) == 0:
        return build_pattern(grid, [], fabric_count)

    lab = srgb_to_lab(colours)
    if len(colours) <= max_colours:
        centroids, labels = lab, np.arange(len(colours), dtype=np.intp)
    else:
        centroids = _quantise(colours, lab, counts.astype(np.float64), max_colours)
        labels = _nearest_centroid(lab, centroids)
    grid[stitched] = labels[inverse.reshape(-1)]
    return build_pattern(grid, nearest_dmc_lab(centroids), fabric_count)


def _quantise(
    colours: npt.NDArray[np.uint8], lab: FloatArray, counts: FloatArray, k: int
) -> FloatArray:
    """At most `k` Lab centroids for the distinct `colours` (with their Lab and counts)."""
    bins = colours.astype(np.intp) >> _BIN_SHIFT
    bin_ids = (bins[:, 0] << 10) | (bins[:, 1] << 5) | bins[:, 2]
    unique_bins, bin_index = np.unique(bin_ids, return_inverse=True)
    mass, sums = _weighted_sums(bin_index, counts, lab, len(unique_bins))
    means = sums / mass[:, np.newaxis]
    if len(unique_bins) <= k:
        return means
    return _kmeans(means, mass, k)


def _weighted_sums(
    groups: IndexArray, weights: FloatArray, points: FloatArray, size: int
) -> tuple[FloatArray, FloatArray]:
    """Per group: the total weight (size,) and the weighted sum of its points (size, 3)."""
    mass = np.bincount(groups, weights=weights, minlength=size)
    sums = np.stack(
        [
            np.bincount(groups, weights=weights * points[:, axis], minlength=size)
            for axis in range(3)
        ],
        axis=1,
    )
    return mass, sums


def _nearest_centroid(points: FloatArray, centroids: FloatArray) -> IndexArray:
    """Index of the nearest centroid (Euclidean in Lab) for each point; ties go low."""
    labels = np.empty(len(points), dtype=np.intp)
    for start in range(0, len(points), _CHUNK):
        chunk = points[start : start + _CHUNK]
        distances = np.zeros((len(chunk), len(centroids)))
        for axis in range(3):
            distances += np.subtract.outer(chunk[:, axis], centroids[:, axis]) ** 2
        labels[start : start + _CHUNK] = np.argmin(distances, axis=1)
    return labels


def _kmeans_plus_plus(
    points: FloatArray, weights: FloatArray, k: int, rng: np.random.Generator
) -> FloatArray:
    """k-means++ seeding on weighted points: each new centroid is drawn with probability
    proportional to weight * squared distance to the nearest centroid chosen so far."""
    chosen = [int(rng.choice(len(points), p=weights / weights.sum()))]
    nearest = ((points - points[chosen[0]]) ** 2).sum(axis=1)
    for _ in range(1, k):
        mass = weights * nearest
        if mass.sum() <= 0:
            break
        chosen.append(int(rng.choice(len(points), p=mass / mass.sum())))
        nearest = np.minimum(nearest, ((points - points[chosen[-1]]) ** 2).sum(axis=1))
    return points[chosen]


def _kmeans(points: FloatArray, weights: FloatArray, k: int) -> FloatArray:
    """Weighted Lloyd's k-means: the centroids.

    Stops when no centroid moves by more than `_TOLERANCE` (Lab units, far below a visible
    difference) or after `_MAX_ITERATIONS`. A cluster that loses all its points is
    dropped, so fewer than `k` centroids may come back.
    """
    centroids = _kmeans_plus_plus(points, weights, k, np.random.default_rng(_SEED))
    labels = _nearest_centroid(points, centroids)
    for _ in range(_MAX_ITERATIONS):
        mass, sums = _weighted_sums(labels, weights, points, len(centroids))
        used = mass > 0
        moved = sums[used] / mass[used, np.newaxis]
        shift = float(np.max(np.abs(moved - centroids[used])))
        centroids = moved
        labels = _nearest_centroid(points, centroids)
        if shift <= _TOLERANCE:
            break
    return centroids
