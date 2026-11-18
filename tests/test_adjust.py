"""`adjust_image`: brightness, contrast, saturation, hue, gamma and sharpness."""

import numpy as np
import numpy.typing as npt
import pytest
from PIL import Image

from cross_stitch.colour import srgb_to_lab
from cross_stitch.pattern import Adjustments, adjust_image, convert_image

ByteArray = npt.NDArray[np.uint8]


def _uniform(rgb: tuple[int, int, int], size: tuple[int, int] = (6, 4)) -> Image.Image:
    return Image.new("RGB", size, rgb)


def _ramp() -> Image.Image:
    """A horizontal grey ramp, 0 to 255."""
    row = np.linspace(0, 255, 64).astype(np.uint8)
    return Image.fromarray(np.tile(row, (8, 1))).convert("RGB")


def _colourful() -> Image.Image:
    rng = np.random.default_rng(3)
    return Image.fromarray(rng.integers(0, 256, size=(12, 16, 3), dtype=np.uint8))


def _pixels(image: Image.Image) -> ByteArray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _pixel(image: Image.Image) -> npt.NDArray[np.int_]:
    pixel: npt.NDArray[np.int_] = _pixels(image)[0, 0].astype(int)
    return pixel


def _step_edge() -> Image.Image:
    """Dark left half, light right half: one vertical edge."""
    pixels = np.full((16, 16, 3), 60, dtype=np.uint8)
    pixels[:, 8:] = 190
    return Image.fromarray(pixels)


def _largest_column_step(image: Image.Image) -> int:
    grey = _pixels(image)[..., 0].astype(int)
    return int(np.abs(np.diff(grey, axis=1)).max())


def _p_image() -> Image.Image:
    return _colourful().quantize(colors=8)


@pytest.mark.parametrize(
    "image",
    [
        _colourful(),
        _colourful().convert("RGBA"),
        _colourful().convert("L"),
        _p_image(),
    ],
    ids=["RGB", "RGBA", "L", "P"],
)
def test_all_neutral_returns_the_same_mode_and_pixels(image: Image.Image) -> None:
    adjusted = adjust_image(image, Adjustments())

    assert adjusted.mode == image.mode
    assert np.array_equal(np.asarray(adjusted), np.asarray(image))


def test_brightness_scales_the_levels() -> None:
    grey = _uniform((100, 100, 100))

    assert np.all(np.abs(_pixel(adjust_image(grey, Adjustments(brightness=50))) - 150) <= 1)
    assert np.all(_pixel(adjust_image(grey, Adjustments(brightness=-100))) == 0)


def test_more_brightness_never_darkens_a_pixel() -> None:
    ramp = _ramp()

    assert np.all(_pixels(adjust_image(ramp, Adjustments(brightness=20))) >= _pixels(ramp))


def test_no_contrast_leaves_one_colour() -> None:
    pixels = np.zeros((8, 8, 3), dtype=np.uint8)
    pixels[:, 4:] = (230, 180, 40)

    flat = _pixels(adjust_image(Image.fromarray(pixels), Adjustments(contrast=-100)))

    assert len(np.unique(flat.reshape(-1, 3), axis=0)) == 1


def test_more_contrast_spreads_the_levels() -> None:
    ramp = _ramp()

    assert _pixels(adjust_image(ramp, Adjustments(contrast=50))).std() > _pixels(ramp).std()


def test_no_saturation_gives_greys() -> None:
    grey = _pixels(adjust_image(_colourful(), Adjustments(saturation=-100)))

    assert np.array_equal(grey[..., 0], grey[..., 1])
    assert np.array_equal(grey[..., 1], grey[..., 2])


def test_more_saturation_raises_chroma() -> None:
    muted = _uniform((150, 120, 110))

    def chroma(image: Image.Image) -> float:
        lab = srgb_to_lab(_pixel(image).astype(np.uint8))
        return float(np.hypot(lab[1], lab[2]))

    assert chroma(adjust_image(muted, Adjustments(saturation=50))) > chroma(muted)


@pytest.mark.parametrize(
    ("degrees", "expected"), [(120, (0, 255, 0)), (180, (0, 255, 255)), (-120, (0, 0, 255))]
)
def test_hue_turns_the_colour_wheel(degrees: float, expected: tuple[int, int, int]) -> None:
    red = _uniform((255, 0, 0))

    turned = _pixel(adjust_image(red, Adjustments(hue=degrees)))

    assert np.all(np.abs(turned - expected) <= 2)


def test_turning_the_hue_back_gives_the_original() -> None:
    image = _colourful()

    there = adjust_image(image, Adjustments(hue=120))
    back = adjust_image(there, Adjustments(hue=-120))

    assert np.abs(_pixels(back).astype(int) - _pixels(image).astype(int)).max() <= 2


@pytest.mark.parametrize("degrees", [37, 120, -90, 180])
def test_hue_leaves_greys_alone(degrees: float) -> None:
    ramp = _ramp()

    assert np.array_equal(_pixels(adjust_image(ramp, Adjustments(hue=degrees))), _pixels(ramp))


def test_gamma_above_one_lightens_the_mid_tones() -> None:
    grey = _uniform((128, 128, 128))

    assert np.all(np.abs(_pixel(adjust_image(grey, Adjustments(gamma=2))) - 181) <= 1)
    assert np.all(_pixel(adjust_image(grey, Adjustments(gamma=0.5))) < 128)


@pytest.mark.parametrize("gamma", [0.25, 0.5, 2.0, 4.0])
def test_gamma_keeps_black_and_white(gamma: float) -> None:
    pixels = np.zeros((2, 2, 3), dtype=np.uint8)
    pixels[1] = 255

    adjusted = _pixels(adjust_image(Image.fromarray(pixels), Adjustments(gamma=gamma)))

    assert np.array_equal(adjusted, pixels)


@pytest.mark.parametrize("sharpness", [-100, -40, 60, 100])
def test_sharpness_leaves_a_flat_image_alone(sharpness: float) -> None:
    flat = _uniform((90, 140, 200), size=(10, 10))

    adjusted = adjust_image(flat, Adjustments(sharpness=sharpness))

    assert np.array_equal(_pixels(adjusted), _pixels(flat))


def test_sharpness_raises_or_lowers_the_edge() -> None:
    edge = _step_edge()

    sharper = adjust_image(edge, Adjustments(sharpness=100))
    softer = adjust_image(edge, Adjustments(sharpness=-100))

    assert _largest_column_step(sharper) > _largest_column_step(edge)
    assert _largest_column_step(softer) < _largest_column_step(edge)


def test_sharpness_treats_the_border_like_the_inside() -> None:
    edge = _pixels(adjust_image(_step_edge(), Adjustments(sharpness=-100)))

    assert np.array_equal(edge[0], edge[8])
    assert np.array_equal(edge[-1], edge[8])


@pytest.mark.parametrize(
    "adjustments",
    [
        Adjustments(brightness=-60),
        Adjustments(contrast=80),
        Adjustments(saturation=-100),
        Adjustments(hue=90),
        Adjustments(gamma=3),
        Adjustments(sharpness=100),
        Adjustments(brightness=30, contrast=-30, saturation=40, hue=-45, gamma=0.7, sharpness=-50),
    ],
)
def test_alpha_is_never_changed(adjustments: Adjustments) -> None:
    pixels = np.zeros((10, 20, 4), dtype=np.uint8)
    pixels[..., :3] = np.asarray(_colourful().resize((20, 10)))
    pixels[:, 10:, 3] = 255
    image = Image.fromarray(pixels, mode="RGBA")

    adjusted = adjust_image(image, adjustments)

    assert adjusted.mode == "RGBA"
    assert np.array_equal(np.asarray(adjusted)[..., 3], pixels[..., 3])


def test_a_grey_image_takes_colour_adjustments() -> None:
    grey = _ramp().convert("L")

    adjusted = adjust_image(grey, Adjustments(saturation=50, hue=90))

    assert convert_image(adjusted, width=8, max_colours=4).width == 8


def test_the_same_call_gives_the_same_pixels() -> None:
    adjustments = Adjustments(brightness=10, contrast=20, saturation=-30, hue=60, sharpness=40)

    first = adjust_image(_colourful(), adjustments)
    second = adjust_image(_colourful(), adjustments)

    assert np.array_equal(np.asarray(first), np.asarray(second))
