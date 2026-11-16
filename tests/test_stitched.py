"""find_stitch_grid and unstitch: the grid of a picture of cross stitch, on drawn images."""

import numpy as np
import pytest
from PIL import Image
from stitch_helpers import (
    ART_COLUMNS,
    ART_ROWS,
    PALETTE,
    art,
    chart,
    gradient,
    jpeg,
    noise,
    stitched,
    weave,
)

from cross_stitch.pattern import find_pixel_grid
from cross_stitch.pattern.stitched import (
    fabric_weave,
    find_stitch_grid,
    symbols_only,
    unstitch,
)
from cross_stitch.threads import dmc_thread, nearest_dmc

CELLS = art()


def _codes(image: Image.Image) -> list[list[str]]:
    """The nearest DMC code of each pixel of a reduced image."""
    rgb = np.asarray(image.convert("RGB"))
    threads = nearest_dmc(rgb.reshape(-1, 3))
    width = rgb.shape[1]
    return [[t.code for t in threads[row : row + width]] for row in range(0, len(threads), width)]


def _expected(palette: np.ndarray = PALETTE) -> list[list[str]]:
    threads = nearest_dmc(np.rint(palette).astype(np.uint8))
    return [[threads[cell].code for cell in row] for row in CELLS]


def _read(image: Image.Image) -> tuple[tuple[int, int], list[list[str]]]:
    grid = find_stitch_grid(image)
    assert grid is not None
    return (grid.columns, grid.rows), _codes(unstitch(image, grid))


def test_a_render_gives_its_grid_and_each_stitch_its_thread() -> None:
    size, codes = _read(stitched(CELLS, 16))

    assert size == (ART_COLUMNS, ART_ROWS)
    assert codes == _expected()


@pytest.mark.parametrize(("pitch_x", "pitch_y"), [(11.85, 11.85), (16.3, 17.0)])
def test_fractional_and_slightly_unequal_pitches(pitch_x: float, pitch_y: float) -> None:
    size, codes = _read(stitched(CELLS, pitch_x, pitch_y))

    assert size == (ART_COLUMNS, ART_ROWS)
    assert codes == _expected()


def test_a_render_cut_off_at_the_left_and_top() -> None:
    image = stitched(CELLS, 16)
    cut = image.crop((5, 5, image.width, image.height))

    size, codes = _read(cut)

    assert size == (ART_COLUMNS, ART_ROWS)
    assert codes == _expected()


def test_a_strong_half_pitch_is_not_taken_for_the_pitch() -> None:
    size, _ = _read(stitched(CELLS, 16, band=True))

    assert size == (ART_COLUMNS, ART_ROWS)


def test_pitches_too_far_apart_across_and_down_are_no_grid() -> None:
    assert find_stitch_grid(stitched(CELLS, 16, 22)) is None


def test_black_and_white_threads_are_read() -> None:
    palette = np.array([dmc_thread(code).rgb for code in ("310", "Blanc")] * 2, dtype=np.float64)
    image = stitched(CELLS, 16, palette=palette)
    grid = find_stitch_grid(image)

    assert grid is not None
    assert (grid.columns, grid.rows) == (ART_COLUMNS, ART_ROWS)
    # Blanc, B5200 and 3865 are all but one white: each cell's lightness is what counts.
    light = np.asarray(unstitch(image, grid).convert("L")) > 128
    assert (light == (CELLS % 2 == 1)).all()
    assert not symbols_only(image, grid)


@pytest.mark.parametrize("image", [gradient(), noise(), jpeg(), weave()], ids=repr)
def test_no_stitch_grid_in_a_gradient_noise_jpeg_blocks_or_weave(image: Image.Image) -> None:
    assert find_stitch_grid(image) is None


def test_a_fine_weave_is_recognised_and_a_plain_photo_is_not() -> None:
    assert fabric_weave(weave())
    assert not fabric_weave(jpeg())
    assert not fabric_weave(gradient())


def test_flat_pixel_art_is_left_to_the_pixel_art_reader() -> None:
    flat = Image.fromarray(PALETTE[art(5, 12, 10)].astype(np.uint8)).resize(
        (120, 100), Image.Resampling.NEAREST
    )

    assert find_pixel_grid(flat) is not None


def test_a_colour_chart_gives_each_cell_its_fill_not_its_symbol() -> None:
    size, codes = _read(chart(CELLS, 14))

    assert size == (ART_COLUMNS, ART_ROWS)
    assert codes == _expected()


def test_a_chart_of_symbols_on_white_is_symbols_only() -> None:
    white = np.full((4, 3), 255.0)
    image = chart(CELLS, 14, palette=white)
    grid = find_stitch_grid(image)

    assert grid is not None
    assert symbols_only(image, grid)
