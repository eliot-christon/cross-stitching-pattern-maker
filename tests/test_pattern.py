"""Image -> DMC pattern: resize, transparency, quantisation, key, counts, skeins and size.

Every image is built in code from a few known colours. Expected threads come from the DMC
table (`dmc_thread(code).rgb`, whose own-row lookup is pinned in `test_threads.py`), never
from the conversion's own output.
"""

import dataclasses
import math

import numpy as np
import pytest
from PIL import Image

from cross_stitch.pattern import (
    EMPTY,
    KeyEntry,
    Pattern,
    convert_image,
    skeins_needed,
    stitches_per_skein,
)
from cross_stitch.threads import dmc_thread

type Rgb = tuple[int, int, int]
type Rgba = tuple[int, int, int, int]
type Pixel = Rgb | Rgba

BLACK: Rgb = (0, 0, 0)
WHITE: Rgb = (255, 255, 255)
TRANSPARENT_BLACK: Rgba = (0, 0, 0, 0)
TRANSPARENT_RED: Rgba = (255, 0, 0, 0)
OPAQUE_BLACK: Rgba = (0, 0, 0, 255)

FABRIC_COUNTS = [11.0, 14.0, 16.0, 18.0, 28.0]


def _rgb(code: str) -> Rgb:
    return dmc_thread(code).rgb


def _stripes(colours: list[Pixel], widths: list[int], height: int) -> Image.Image:
    """Vertical stripes, left to right: colours[i] repeated widths[i] columns."""
    row = [colour for colour, width in zip(colours, widths, strict=True) for _ in range(width)]
    return Image.fromarray(np.array([row] * height, dtype=np.uint8))


def _plain(colour: Rgb, width: int, height: int) -> Image.Image:
    return Image.new("RGB", (width, height), colour)


def _gradient(width: int = 32, height: int = 16) -> Image.Image:
    """Many distinct colours: red across, green down, blue the inverse of red."""
    red = np.tile(np.linspace(0, 255, width), (height, 1))
    green = np.tile(np.linspace(0, 255, height)[:, np.newaxis], (1, width))
    array = np.stack([red, green, 255 - red], axis=-1).round().astype(np.uint8)
    return Image.fromarray(array)


def _codes(pattern: Pattern) -> list[str]:
    return [entry.thread.code for entry in pattern.key]


def _code_grid(pattern: Pattern) -> list[list[str]]:
    """The grid as DMC codes, "" for an empty cell."""
    return [
        ["" if index == EMPTY else pattern.key[int(index)].thread.code for index in row]
        for row in pattern.grid
    ]


def _assert_counts_add_up(pattern: Pattern) -> None:
    grid = pattern.grid
    assert grid.shape == (pattern.height, pattern.width)
    assert grid.dtype == np.intp
    stitched = grid != EMPTY
    assert np.all((grid[stitched] >= 0) & (grid[stitched] < len(pattern.key)))
    for index, entry in enumerate(pattern.key):
        assert entry.stitches == int(np.count_nonzero(grid == index)), entry.thread.code
        assert entry.stitches >= 1, entry.thread.code
        assert entry.skeins == skeins_needed(entry.stitches, pattern.fabric_count)
    assert isinstance(pattern.total_stitches, int)
    assert sum(entry.stitches for entry in pattern.key) == pattern.total_stitches
    assert pattern.total_stitches == int(np.count_nonzero(stitched))
    codes = _codes(pattern)
    assert len(set(codes)) == len(codes)


def _assert_same_pattern(first: Pattern, second: Pattern) -> None:
    assert np.array_equal(first.grid, second.grid)
    assert first.grid.dtype == second.grid.dtype
    assert first.key == second.key
    assert first.fabric_count == second.fabric_count


# ------------------------------------------------------------------------------- golden


GOLDEN_CODES = ["310", "Blanc", "321", "797"]


def _golden_image() -> Image.Image:
    return _stripes([_rgb(code) for code in GOLDEN_CODES], [10, 10, 10, 10], 20)


def test_golden_four_stripes_give_exactly_those_four_threads() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=4)
    # All four tie at 200 stitches: numeric codes first in numeric order, then "Blanc".
    assert _codes(pattern) == ["310", "321", "797", "Blanc"]
    assert [entry.stitches for entry in pattern.key] == [200, 200, 200, 200]
    assert [entry.thread for entry in pattern.key] == [
        dmc_thread(code) for code in ("310", "321", "797", "Blanc")
    ]
    assert pattern.total_stitches == 800
    _assert_counts_add_up(pattern)


def test_golden_grid_is_the_four_stripes_cell_for_cell() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=4)
    assert (pattern.width, pattern.height) == (40, 20)
    expected_row = [code for code in GOLDEN_CODES for _ in range(10)]
    assert _code_grid(pattern) == [expected_row] * 20


def test_golden_key_entries_carry_one_skein_each_on_aida_14() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=4)
    assert [entry.skeins for entry in pattern.key] == [1, 1, 1, 1]


def test_more_colours_allowed_than_present_gives_only_those_present() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=10)
    assert sorted(_codes(pattern)) == sorted(["310", "Blanc", "321", "797"])
    assert len(pattern.key) == 4
    _assert_counts_add_up(pattern)


# ----------------------------------------------------------------- snapping and merging


@pytest.mark.parametrize(
    ("first", "second", "code"),
    [(BLACK, (1, 1, 1), "310"), (WHITE, (254, 254, 254), "B5200")],
    ids=["near-black", "near-white"],
)
def test_two_colours_snapping_to_one_thread_merge_into_one_entry(
    first: Rgb, second: Rgb, code: str
) -> None:
    image = _stripes([first, second], [3, 5], 2)
    pattern = convert_image(image, width=8, max_colours=2)
    assert _codes(pattern) == [code]
    assert pattern.key[0].stitches == 16
    assert np.array_equal(pattern.grid, np.zeros((2, 8), dtype=np.intp))
    _assert_counts_add_up(pattern)


def test_single_colour_image_gives_one_entry_covering_every_cell() -> None:
    pattern = convert_image(_plain(_rgb("321"), 7, 5), width=7, max_colours=4)
    assert _codes(pattern) == ["321"]
    assert pattern.key[0].stitches == 7 * 5
    assert pattern.total_stitches == 35
    _assert_counts_add_up(pattern)


def test_one_colour_allowed_puts_every_cell_in_one_entry() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=1)
    assert len(pattern.key) == 1
    assert pattern.key[0].stitches == 800
    assert np.array_equal(pattern.grid, np.zeros((20, 40), dtype=np.intp))


def test_kmeans_separates_two_well_separated_groups_of_shades() -> None:
    # Six distinct colours, two allowed: three blacks and three reds a hair off 321.
    blacks: list[Pixel] = [BLACK, (1, 1, 1), (2, 2, 2)]
    reds: list[Pixel] = [(198, 43, 59), (199, 43, 59), (200, 43, 59)]
    colours = blacks + reds
    pattern = convert_image(_stripes(colours, [2] * 6, 2), width=12, max_colours=2)
    assert _codes(pattern) == ["310", "321"]
    assert [entry.stitches for entry in pattern.key] == [12, 12]
    assert _code_grid(pattern) == [["310"] * 6 + ["321"] * 6] * 2


def test_kmeans_weights_each_colour_by_its_cell_count() -> None:
    # 999 cells of 321 and one white cell, one colour allowed: weighted by count, the
    # centroid stays on 321; an unweighted mean of the two would land on a pale pink.
    array = np.full((20, 50, 3), _rgb("321"), dtype=np.uint8)
    array[0, 0] = WHITE
    pattern = convert_image(Image.fromarray(array), width=50, max_colours=1)
    assert _codes(pattern) == ["321"]
    assert pattern.key[0].stitches == 1000


@pytest.mark.parametrize("max_colours", [1, 2, 3, 5, 16])
def test_gradient_never_exceeds_the_colour_limit_and_counts_add_up(max_colours: int) -> None:
    pattern = convert_image(_gradient(), width=32, max_colours=max_colours)
    assert 1 <= len(pattern.key) <= max_colours
    assert pattern.total_stitches == 32 * 16
    _assert_counts_add_up(pattern)


# -------------------------------------------------------------------------------- order


def test_key_is_ordered_by_stitch_count_descending() -> None:
    image = _stripes([_rgb("310"), _rgb("321"), _rgb("Blanc")], [1, 3, 2], 4)
    pattern = convert_image(image, width=6, max_colours=3)
    assert _codes(pattern) == ["321", "Blanc", "310"]
    assert [entry.stitches for entry in pattern.key] == [12, 8, 4]


def test_ties_put_numeric_codes_first_in_numeric_order_then_the_others_alphabetically() -> None:
    order = ["01", "35", "150", "3865", "B5200", "Blanc", "Ecru"]
    scrambled = ["Ecru", "3865", "01", "Blanc", "150", "B5200", "35"]
    image = _stripes([_rgb(code) for code in scrambled], [2] * 7, 3)
    pattern = convert_image(image, width=14, max_colours=7)
    assert _codes(pattern) == order
    assert {entry.stitches for entry in pattern.key} == {6}


# --------------------------------------------------------------------------- determinism


def test_converting_the_same_gradient_twice_gives_the_same_pattern() -> None:
    image = _gradient()
    _assert_same_pattern(
        convert_image(image, width=24, max_colours=5),
        convert_image(image, width=24, max_colours=5),
    )


def test_two_equal_images_built_separately_give_the_same_pattern() -> None:
    _assert_same_pattern(
        convert_image(_gradient(), width=20, max_colours=6, fabric_count=18.0),
        convert_image(_gradient(), width=20, max_colours=6, fabric_count=18.0),
    )


def test_conversion_leaves_the_input_image_untouched() -> None:
    image = _gradient()
    before = (image.mode, image.size, image.tobytes())
    convert_image(image, width=10, max_colours=3)
    assert (image.mode, image.size, image.tobytes()) == before


# ------------------------------------------------------------------------- grid size


@pytest.mark.parametrize(
    ("image_size", "width", "grid_size"),
    [
        ((200, 100), 50, (50, 25)),
        ((3, 1000), 2, (2, 667)),
        ((1000, 3), 2, (2, 1)),
        ((10, 1), 1, (1, 1)),
        ((20, 10), 40, (40, 20)),
        ((1, 1), 1, (1, 1)),
        ((1, 1), 5, (5, 5)),
        # Halves round up: 3 * 6 / 4 = 4.5 -> 5 and 1 * 10 / 4 = 2.5 -> 3.
        ((4, 6), 3, (3, 5)),
        ((4, 10), 1, (1, 3)),
    ],
    ids=[
        "downscale-2-to-1",
        "tall-thin",
        "wide-flat-at-least-1-high",
        "one-row-at-least-1-high",
        "upscale",
        "1x1",
        "1x1-upscaled",
        "half-rounds-up-4.5",
        "half-rounds-up-2.5",
    ],
)
def test_grid_has_the_requested_width_and_the_image_aspect_ratio(
    image_size: tuple[int, int], width: int, grid_size: tuple[int, int]
) -> None:
    pattern = convert_image(_plain(_rgb("797"), *image_size), width=width, max_colours=2)
    assert (pattern.width, pattern.height) == grid_size
    assert pattern.grid.shape == (grid_size[1], grid_size[0])
    assert pattern.total_stitches == grid_size[0] * grid_size[1]
    assert _codes(pattern) == ["797"]
    _assert_counts_add_up(pattern)


def test_tall_image_keeps_its_aspect_within_rounding() -> None:
    pattern = convert_image(_plain(BLACK, 3, 1000), width=2, max_colours=1)
    assert pattern.height >= 1
    assert abs(pattern.height - 2 * 1000 / 3) <= 0.5


def test_upscaling_keeps_a_single_colour_and_fills_every_cell() -> None:
    pattern = convert_image(_plain(_rgb("321"), 20, 10), width=40, max_colours=3)
    assert (pattern.width, pattern.height) == (40, 20)
    assert _codes(pattern) == ["321"]
    assert pattern.key[0].stitches == 800


# ------------------------------------------------------------------------- image modes


@pytest.mark.parametrize(
    "image",
    [
        Image.new("RGB", (4, 2), BLACK),
        Image.new("RGBA", (4, 2), OPAQUE_BLACK),
        Image.new("L", (4, 2), 0),
        Image.new("LA", (4, 2), (0, 255)),
        Image.new("1", (4, 2), 0),
        Image.new("RGB", (4, 2), BLACK).convert("P"),
    ],
    ids=["RGB", "RGBA", "L-greyscale", "LA", "1-bilevel", "P-palette"],
)
def test_any_pillow_mode_is_accepted(image: Image.Image) -> None:
    pattern = convert_image(image, width=4, max_colours=2)
    assert _codes(pattern) == ["310"]
    assert pattern.key[0].stitches == 8


def test_greyscale_white_gives_snow_white() -> None:
    pattern = convert_image(Image.new("L", (3, 3), 255), width=3, max_colours=1)
    assert _codes(pattern) == ["B5200"]


# ------------------------------------------------------------------------- transparency


@pytest.mark.parametrize("transparent", [TRANSPARENT_BLACK, TRANSPARENT_RED], ids=["black", "red"])
def test_transparent_left_half_is_empty_and_out_of_the_key(transparent: Rgba) -> None:
    image = _stripes([transparent, OPAQUE_BLACK], [8, 8], 8)
    pattern = convert_image(image, width=8, max_colours=4)
    assert (pattern.width, pattern.height) == (8, 4)
    assert _codes(pattern) == ["310"]
    assert pattern.key[0].stitches == 16
    assert pattern.total_stitches == 16
    assert _code_grid(pattern) == [[""] * 4 + ["310"] * 4] * 4
    assert np.all(pattern.grid[:, :4] == EMPTY)
    _assert_counts_add_up(pattern)


def test_colour_under_full_transparency_does_not_change_the_result() -> None:
    black = _stripes([TRANSPARENT_BLACK, OPAQUE_BLACK], [8, 8], 8)
    red = _stripes([TRANSPARENT_RED, OPAQUE_BLACK], [8, 8], 8)
    _assert_same_pattern(
        convert_image(black, width=8, max_colours=4),
        convert_image(red, width=8, max_colours=4),
    )


def test_transparent_pixels_do_not_tint_a_mostly_opaque_cell() -> None:
    # 8x4 -> 2x1: the left cell averages one transparent red column with three opaque
    # black ones. It is stitched (alpha 191) and stays black: red must not leak in.
    image = _stripes([TRANSPARENT_RED, OPAQUE_BLACK], [1, 7], 4)
    pattern = convert_image(image, width=2, max_colours=2)
    assert (pattern.width, pattern.height) == (2, 1)
    assert _codes(pattern) == ["310"]
    assert pattern.key[0].stitches == 2
    assert np.array_equal(pattern.grid, np.zeros((1, 2), dtype=np.intp))


@pytest.mark.parametrize(
    ("alpha", "stitched"),
    [(0, False), (127, False), (128, True), (255, True)],
)
def test_a_cell_is_stitched_from_alpha_128(alpha: int, stitched: bool) -> None:
    pattern = convert_image(Image.new("RGBA", (4, 2), (0, 0, 0, alpha)), width=4, max_colours=1)
    if stitched:
        assert _codes(pattern) == ["310"]
        assert pattern.total_stitches == 8
    else:
        assert not pattern.key
        assert pattern.total_stitches == 0
        assert np.all(pattern.grid == EMPTY)
    _assert_counts_add_up(pattern)


def test_fully_transparent_image_gives_an_empty_pattern_of_the_right_size() -> None:
    image = Image.new("RGBA", (140, 70), TRANSPARENT_RED)
    pattern = convert_image(image, width=140, max_colours=5)
    assert isinstance(pattern.key, tuple)
    assert not pattern.key
    assert pattern.total_stitches == 0
    assert pattern.grid.shape == (70, 140)
    assert np.all(pattern.grid == EMPTY)
    # Bare fabric still has a size.
    assert pattern.width_in == pytest.approx(10.0)
    assert pattern.height_in == pytest.approx(5.0)


def test_empty_is_minus_one() -> None:
    assert EMPTY == -1


# ---------------------------------------------------------------------- finished size


def test_140_stitches_on_aida_14_is_10_inches_25_4_cm() -> None:
    pattern = convert_image(_plain(BLACK, 140, 70), width=140, max_colours=1, fabric_count=14)
    assert pattern.fabric_count == 14.0
    assert pattern.width_in == pytest.approx(10.0)
    assert pattern.width_cm == pytest.approx(25.4)
    assert pattern.height_in == pytest.approx(5.0)
    assert pattern.height_cm == pytest.approx(12.7)


def test_140_stitches_on_aida_18() -> None:
    pattern = convert_image(_plain(BLACK, 140, 70), width=140, max_colours=1, fabric_count=18)
    assert pattern.fabric_count == 18.0
    assert pattern.width_in == pytest.approx(140 / 18)
    assert pattern.width_cm == pytest.approx(140 / 18 * 2.54)
    assert pattern.height_in == pytest.approx(70 / 18)
    assert pattern.height_cm == pytest.approx(70 / 18 * 2.54)


def test_fabric_count_defaults_to_14() -> None:
    pattern = convert_image(_plain(BLACK, 28, 14), width=28, max_colours=1)
    assert pattern.fabric_count == 14.0
    assert pattern.width_in == pytest.approx(2.0)


def test_empty_cells_count_towards_the_finished_size() -> None:
    image = _stripes([TRANSPARENT_BLACK, OPAQUE_BLACK], [70, 70], 14)
    pattern = convert_image(image, width=140, max_colours=1)
    assert pattern.total_stitches == 70 * 14
    assert pattern.width_in == pytest.approx(10.0)
    assert pattern.height_in == pytest.approx(1.0)


# ------------------------------------------------------------------------------- skeins


def test_no_stitches_need_no_skein() -> None:
    assert skeins_needed(0, 14.0) == 0


@pytest.mark.parametrize("fabric_count", FABRIC_COUNTS)
def test_one_stitch_needs_one_skein(fabric_count: float) -> None:
    assert skeins_needed(1, fabric_count) == 1


@pytest.mark.parametrize("fabric_count", FABRIC_COUNTS)
def test_skein_boundary_is_one_skeins_worth_then_one_stitch_more(fabric_count: float) -> None:
    per_skein = stitches_per_skein(fabric_count)
    assert skeins_needed(per_skein, fabric_count) == 1
    assert skeins_needed(per_skein + 1, fabric_count) == 2
    assert skeins_needed(2 * per_skein, fabric_count) == 2
    assert skeins_needed(2 * per_skein + 1, fabric_count) == 3


def test_aida_14_boundary_gives_one_then_two_skeins() -> None:
    per_skein = stitches_per_skein(14)
    assert skeins_needed(per_skein, 14) == 1
    assert skeins_needed(per_skein + 1, 14) == 2


@pytest.mark.parametrize("fabric_count", FABRIC_COUNTS)
def test_more_stitches_never_need_fewer_skeins(fabric_count: float) -> None:
    skeins = [skeins_needed(stitches, fabric_count) for stitches in range(10_000)]
    assert skeins == sorted(skeins)


def test_coarser_fabric_needs_at_least_as_many_skeins() -> None:
    for stitches in range(1, 20_000, 37):
        assert skeins_needed(stitches, 11.0) >= skeins_needed(stitches, 18.0), stitches


def test_a_skein_covers_more_stitches_on_finer_fabric() -> None:
    assert stitches_per_skein(11) < stitches_per_skein(14) < stitches_per_skein(18)


def test_stitches_per_skein_is_proportional_to_the_fabric_count() -> None:
    # Thread per stitch scales with the cell side, 1 / fabric count; flooring loses < 1.
    assert abs(stitches_per_skein(28) - 2 * stitches_per_skein(14)) <= 1
    assert abs(stitches_per_skein(22) - 2 * stitches_per_skein(11)) <= 1


def test_stitches_per_skein_on_aida_14_is_plausible() -> None:
    # A sanity bracket around the epic's 20%-waste formula (2283 on Aida 14), not the
    # published two-strand figures (about 1100-1800), which the formula exceeds.
    assert 1500 <= stitches_per_skein(14) <= 3000


def test_key_skeins_follow_the_entry_stitch_count_and_fabric() -> None:
    image = _plain(_rgb("321"), 100, 50)
    for fabric_count in FABRIC_COUNTS:
        pattern = convert_image(image, width=100, max_colours=1, fabric_count=fabric_count)
        entry = pattern.key[0]
        assert entry.stitches == 5000
        assert entry.skeins == skeins_needed(5000, fabric_count)
        assert entry.skeins >= 2


# ------------------------------------------------------------------------- the model


def test_pattern_and_key_entry_are_frozen() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pattern.fabric_count = 18.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        pattern.key[0].stitches = 1  # type: ignore[misc]


def test_key_is_a_tuple_of_key_entries() -> None:
    pattern = convert_image(_golden_image(), width=40, max_colours=4)
    assert isinstance(pattern.key, tuple)
    assert all(isinstance(entry, KeyEntry) for entry in pattern.key)


# ------------------------------------------------------------------------ invalid input


@pytest.mark.parametrize(
    ("width", "max_colours", "fabric_count"),
    [
        (0, 4, 14.0),
        (-1, 4, 14.0),
        (10, 0, 14.0),
        (10, -1, 14.0),
        (10, 4, 0.0),
        (10, 4, -14.0),
        (10, 4, math.nan),
        (10, 4, math.inf),
    ],
    ids=[
        "width-0",
        "width-negative",
        "max-colours-0",
        "max-colours-negative",
        "fabric-0",
        "fabric-negative",
        "fabric-nan",
        "fabric-inf",
    ],
)
def test_invalid_settings_raise_value_error(
    width: int, max_colours: int, fabric_count: float
) -> None:
    with pytest.raises(ValueError):
        convert_image(
            _plain(BLACK, 4, 4), width=width, max_colours=max_colours, fabric_count=fabric_count
        )


def test_smallest_valid_settings_are_accepted() -> None:
    pattern = convert_image(_golden_image(), width=1, max_colours=1, fabric_count=0.5)
    assert (pattern.width, pattern.height) == (1, 1)
    assert len(pattern.key) == 1
    assert pattern.width_in == pytest.approx(2.0)


def test_kmeans_over_many_colour_bins_finds_the_two_groups() -> None:
    # Two groups of 64 distinct shades each, spread over several 5-bit colour bins, so the
    # binned k-means path runs (not "one cluster per distinct colour"). Offsets come in
    # +/- pairs so each group's mean is its thread's RGB.
    offsets = [(dr, dg, db) for dr in (-6, -2, 2, 6) for dg in (-6, -2, 2, 6) for db in (-6, 6)]
    offsets += [(-r, -g, -b) for r, g, b in offsets]
    pixels = [
        tuple(c + d for c, d in zip(_rgb(code), offset, strict=True))
        for code in ("321", "797")
        for offset in offsets
    ]
    image = Image.fromarray(np.array([pixels], dtype=np.uint8))
    pattern = convert_image(image, width=len(pixels), max_colours=2)
    _assert_counts_add_up(pattern)
    assert sorted(_codes(pattern)) == ["321", "797"]
    assert _code_grid(pattern)[0] == ["321"] * 64 + ["797"] * 64


@pytest.mark.parametrize("stitches", [-1, -100])
def test_skeins_for_a_negative_stitch_count_raise_value_error(stitches: int) -> None:
    with pytest.raises(ValueError, match="negative"):
        skeins_needed(stitches, 14)


@pytest.mark.parametrize("fabric_count", [0.0, -14.0, math.nan, math.inf])
def test_skein_functions_reject_a_bad_fabric_count(fabric_count: float) -> None:
    with pytest.raises(ValueError, match="fabric count"):
        stitches_per_skein(fabric_count)
    with pytest.raises(ValueError, match="fabric count"):
        skeins_needed(10, fabric_count)
    with pytest.raises(ValueError, match="fabric count"):
        skeins_needed(0, fabric_count)


def test_patterns_compare_by_identity_without_raising() -> None:
    first = convert_image(_gradient(), width=8, max_colours=3)
    second = convert_image(_gradient(), width=8, max_colours=3)
    assert first == first  # pylint: disable=comparison-with-itself
    assert first != second
    assert first.key == second.key


@pytest.mark.parametrize("size", [(0, 0), (0, 5), (5, 0)])
def test_an_image_without_pixels_raises_value_error(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="empty"):
        convert_image(Image.new("RGB", size), width=4, max_colours=2)
