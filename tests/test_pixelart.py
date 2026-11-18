"""Pixel art: finding the grid of art pixels in an enlarged image and reducing it.

Every image is generated here: a small seeded art, enlarged the ways pixel art is shared
(whole and fractional factors, smoothed edges, JPEG, cropped edges), and images that are
not pixel art.
"""

import io

import numpy as np
import numpy.typing as npt
import pytest
from PIL import Image, ImageFilter

from cross_stitch.pattern import (
    PixelGrid,
    find_pixel_grid,
    pixel_art_colours,
    unscale_pixel_art,
)

PALETTE = np.array(
    [[0, 0, 0, 255], [255, 255, 255, 255], [214, 64, 52, 255], [60, 120, 200, 255]],
    dtype=np.uint8,
)
COLUMNS, ROWS = 12, 10


def _art() -> npt.NDArray[np.uint8]:
    """A 12 x 10 art of the four palette colours, seeded: edges on both axes everywhere."""
    choice = np.random.default_rng(5).integers(0, len(PALETTE), size=(ROWS, COLUMNS))
    return PALETTE[choice]


def _image(pixels: npt.NDArray[np.uint8]) -> Image.Image:
    return Image.fromarray(pixels, mode="RGBA")


def _enlarged(factor: float) -> Image.Image:
    """The art enlarged by `factor`, each art pixel copied (cells of uneven width when the
    factor is fractional)."""
    size = (round(COLUMNS * factor), round(ROWS * factor))
    return _image(_art()).resize(size, Image.Resampling.NEAREST)


def _jpeg(image: Image.Image) -> Image.Image:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return Image.open(io.BytesIO(buffer.getvalue()))


def _pixels(image: Image.Image) -> npt.NDArray[np.int16]:
    return np.asarray(image.convert("RGBA"), dtype=np.int16)


def _found(image: Image.Image) -> PixelGrid:
    grid = find_pixel_grid(image)
    assert grid is not None
    return grid


@pytest.mark.parametrize("factor", [2, 7, 10])
def test_a_whole_enlargement_is_found_and_reduces_to_the_art_exactly(factor: int) -> None:
    grid = _found(_enlarged(factor))

    assert (grid.columns, grid.rows) == (COLUMNS, ROWS)
    assert grid.pitch_x == pytest.approx(factor, rel=0.01)
    assert np.array_equal(np.asarray(unscale_pixel_art(_enlarged(factor), grid)), _art())


@pytest.mark.parametrize("factor", [3.5, 10.4, 13.7])
def test_a_fractional_enlargement_reduces_to_the_art_exactly(factor: float) -> None:
    image = _enlarged(factor)
    grid = _found(image)

    assert (grid.columns, grid.rows) == (COLUMNS, ROWS)
    assert grid.pitch_x == pytest.approx(factor, rel=0.02)
    assert np.array_equal(np.asarray(unscale_pixel_art(image, grid)), _art())


def test_smoothed_edges_and_jpeg_noise_reduce_to_the_art_within_a_few_levels() -> None:
    image = _jpeg(_enlarged(10.4).filter(ImageFilter.GaussianBlur(1)))
    grid = _found(image)

    assert (grid.columns, grid.rows) == (COLUMNS, ROWS)
    difference = np.abs(_pixels(unscale_pixel_art(image, grid)) - _art().astype(np.int16))
    assert difference.max() <= 16
    assert pixel_art_colours(unscale_pixel_art(image, grid)) == len(PALETTE)


@pytest.mark.parametrize(("crop", "columns"), [(3, COLUMNS), (5, COLUMNS - 1)])
def test_a_cropped_first_cell_counts_when_at_least_half_of_it_shows(
    crop: int, columns: int
) -> None:
    enlarged = _enlarged(7)
    image = enlarged.crop((crop, 0, enlarged.width, enlarged.height))
    grid = _found(image)

    assert (grid.columns, grid.rows) == (columns, ROWS)
    expected = _art()[:, COLUMNS - columns :]
    assert np.array_equal(np.asarray(unscale_pixel_art(image, grid)), expected)


def test_transparent_art_pixels_stay_transparent() -> None:
    art = _art()
    art[0, :] = (0, 0, 0, 0)
    image = _image(art).resize((COLUMNS * 6, ROWS * 6), Image.Resampling.NEAREST)

    reduced = np.asarray(unscale_pixel_art(image, _found(image)))
    assert np.array_equal(reduced, art)


def _sprite() -> npt.NDArray[np.uint8]:
    """A 16 x 16 sprite at its own size: white ground, a black frame, a red and a blue
    block: flat areas, as pixel art has."""
    indices = np.ones((16, 16), dtype=np.intp)
    indices[2:14, 2:14] = 0
    indices[4:12, 4:8] = 2
    indices[4:12, 8:12] = 3
    return PALETTE[indices]


def test_an_image_at_its_own_size_with_few_colours_is_pixel_art_at_pitch_one() -> None:
    art = _sprite()
    grid = _found(_image(art))

    assert grid == PixelGrid(16, 16, 1.0, 1.0, 0.0, 0.0)
    assert np.array_equal(np.asarray(unscale_pixel_art(_image(art), grid)), art)


def test_a_smooth_gradient_is_not_pixel_art() -> None:
    ramp = np.linspace(0, 255, 300)
    pixels = np.stack(np.broadcast_arrays(ramp[np.newaxis, :], ramp[:, np.newaxis], 128.0), -1)
    assert find_pixel_grid(Image.fromarray(pixels.astype(np.uint8), mode="RGB")) is None


def test_small_noise_of_few_colours_is_not_pixel_art_at_its_own_size() -> None:
    noise = PALETTE[np.random.default_rng(1).integers(0, len(PALETTE), size=(16, 16))]
    assert find_pixel_grid(_image(noise)) is None


def test_noise_is_not_pixel_art() -> None:
    pixels = np.random.default_rng(2).integers(0, 256, size=(300, 300, 3), dtype=np.uint8)
    assert find_pixel_grid(Image.fromarray(pixels, mode="RGB")) is None


def test_a_jpeg_photo_like_image_is_not_pixel_art_despite_its_blocks() -> None:
    noise = np.random.default_rng(3).integers(0, 256, size=(40, 40, 3), dtype=np.uint8)
    smooth = Image.fromarray(noise, mode="RGB").resize((320, 320), Image.Resampling.BICUBIC)
    assert find_pixel_grid(_jpeg(smooth.filter(ImageFilter.GaussianBlur(3)))) is None


def test_a_best_pitch_on_the_slope_of_a_peak_outside_the_window_is_no_grid() -> None:
    # DMC 310, Blanc, 321 and 797 in 10-pixel stripes, smoothed (Pillow leaves the outer
    # ring as it is): across, the best score sits on the window's large-pitch end, below
    # its neighbour outside the window, so no pitch is a peak on that axis.
    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    for i, rgb in enumerate([(0, 0, 0), (252, 251, 248), (199, 43, 59), (19, 71, 125)]):
        pixels[:, i * 10 : (i + 1) * 10] = rgb
    softened = Image.fromarray(pixels, mode="RGB").filter(ImageFilter.SMOOTH)
    grid = find_pixel_grid(softened)
    assert grid is None or grid.pitch_x != 10


def test_finding_twice_gives_the_same_grid() -> None:
    image = _jpeg(_enlarged(10.4))
    assert find_pixel_grid(image) == find_pixel_grid(image)


def test_colours_count_the_shades_a_stitcher_tells_apart() -> None:
    art = _art().copy()
    art[0, 0] = (1, 1, 1, 255)  # next to black: the same thread
    art[0, 1] = (0, 0, 0, 100)  # mostly transparent: bare fabric, not counted
    assert pixel_art_colours(_image(art)) == len(PALETTE)


def test_a_half_transparent_art_pixel_keeps_its_colour_and_alpha() -> None:
    art = _art().copy()
    art[2, 3] = (214, 64, 52, 128)
    image = _image(art).resize((COLUMNS * 6, ROWS * 6), Image.Resampling.NEAREST)

    assert np.array_equal(np.asarray(unscale_pixel_art(image, _found(image))), art)


def test_a_colour_on_fewer_than_three_art_pixels_is_a_leftover_not_counted() -> None:
    art = _art().copy()
    art[0, 0] = (240, 200, 40, 255)  # one yellow art pixel: smoothing left it there
    assert pixel_art_colours(_image(art)) == len(PALETTE)
    art[0, 1] = art[0, 2] = (240, 200, 40, 255)  # on three: the art uses it
    assert pixel_art_colours(_image(art)) == len(PALETTE) + 1
