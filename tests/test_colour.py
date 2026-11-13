"""sRGB -> CIELAB (D65) conversion and the CIEDE2000 colour difference.

CIEDE2000 reference data: G. Sharma, W. Wu and E. N. Dalal, "The CIEDE2000 color-difference
formula: implementation notes, supplementary test data, and mathematical observations",
Color Research & Application 30(1):21-30, 2005, Table 1 (also distributed as the data file
`ciede2000testdata` on Gaurav Sharma's website). All 34 pairs are copied as published:
L1 a1 b1, L2 a2 b2 and the expected Delta E00 to 4 decimals, with kL = kC = kH = 1.

sRGB -> Lab references: 8-bit sRGB, IEC 61966-2-1 gamma decoding, D65 reference white.
"""

import ast
import sys
import warnings
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from cross_stitch import colour
from cross_stitch.colour import delta_e_2000, delta_e_2000_matrix, srgb_to_lab

type Lab = tuple[float, float, float]
type Rgb = tuple[int, int, int]

# (pair number, Lab1, Lab2, published Delta E00): Sharma, Wu and Dalal (2005), Table 1.
SHARMA_TABLE_1: list[tuple[int, Lab, Lab, float]] = [
    (1, (50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    (2, (50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    (3, (50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    (4, (50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    (5, (50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    (6, (50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    (7, (50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    (8, (50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    (9, (50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    (10, (50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    (11, (50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    (12, (50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    (13, (50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    (14, (50.0000, -0.0010, 2.4900), (50.0000, 0.0010, -2.4900), 4.8045),
    (15, (50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    (16, (50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    (17, (50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    (18, (50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    (19, (50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    (20, (50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    (21, (50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    (22, (50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    (23, (50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    (24, (50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    (25, (60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    (26, (63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    (27, (61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    (28, (35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    (29, (22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    (30, (36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    (31, (90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    (32, (90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    (33, (6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    (34, (2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]

SHARMA_IDS = [f"pair{row[0]}" for row in SHARMA_TABLE_1]
SHARMA_LAB1: npt.NDArray[np.float64] = np.array([row[1] for row in SHARMA_TABLE_1])
SHARMA_LAB2: npt.NDArray[np.float64] = np.array([row[2] for row in SHARMA_TABLE_1])
SHARMA_DELTA_E: npt.NDArray[np.float64] = np.array([row[3] for row in SHARMA_TABLE_1])

# 8-bit sRGB -> CIELAB (D65), 2-degree observer. Tolerance 0.01 per component.
SRGB_TO_LAB_REFERENCES: list[tuple[Rgb, Lab]] = [
    ((255, 255, 255), (100.0, 0.0, 0.0)),
    ((0, 0, 0), (0.0, 0.0, 0.0)),
    ((255, 0, 0), (53.2408, 80.0925, 67.2032)),
    ((0, 255, 0), (87.7347, -86.1827, 83.1793)),
    ((0, 0, 255), (32.2970, 79.1875, -107.8602)),
    ((255, 255, 0), (97.1393, -21.5537, 94.4780)),
    ((0, 255, 255), (91.1132, -48.0875, -14.1312)),
    ((255, 0, 255), (60.3242, 98.2343, -60.8249)),
    ((128, 128, 128), (53.5850, 0.0, 0.0)),
    # Near black: both the linear sRGB segment (10/255 < 0.04045) and the linear branch of
    # the Lab L* curve (Y < 216/24389) apply, so L* = 24389/27 * (10/255) / 12.92.
    ((10, 10, 10), (2.7418, 0.0, 0.0)),
]

LAB_TOLERANCE = 0.01
DELTA_E_TOLERANCE = 1e-4


# ---------------------------------------------------------------------------- CIEDE2000


@pytest.mark.parametrize(("pair", "lab1", "lab2", "expected"), SHARMA_TABLE_1, ids=SHARMA_IDS)
def test_delta_e_2000_matches_sharma_table_1(
    pair: int, lab1: Lab, lab2: Lab, expected: float
) -> None:
    result = delta_e_2000(np.array(lab1), np.array(lab2))
    assert abs(float(result) - expected) < DELTA_E_TOLERANCE, f"Sharma pair {pair}"


def test_delta_e_2000_of_one_pair_is_a_zero_dimensional_float64_array() -> None:
    result = delta_e_2000(np.array(SHARMA_TABLE_1[0][1]), np.array(SHARMA_TABLE_1[0][2]))
    assert result.shape == ()
    assert result.dtype == np.float64


def test_delta_e_2000_batch_of_sharma_pairs_gives_the_published_values() -> None:
    result = delta_e_2000(SHARMA_LAB1, SHARMA_LAB2)
    assert result.shape == (len(SHARMA_TABLE_1),)
    assert result.dtype == np.float64
    assert np.all(np.abs(result - SHARMA_DELTA_E) < DELTA_E_TOLERANCE)


def test_delta_e_2000_batch_equals_per_pair_calls_exactly() -> None:
    batch = delta_e_2000(SHARMA_LAB1, SHARMA_LAB2)
    one_by_one = np.array(
        [delta_e_2000(lab1, lab2) for lab1, lab2 in zip(SHARMA_LAB1, SHARMA_LAB2, strict=True)]
    )
    assert np.array_equal(batch, one_by_one)


def test_delta_e_2000_keeps_leading_shape() -> None:
    lab1 = SHARMA_LAB1[:12].reshape(2, 6, 3)
    lab2 = SHARMA_LAB2[:12].reshape(2, 6, 3)
    result = delta_e_2000(lab1, lab2)
    assert result.shape == (2, 6)
    assert np.array_equal(result.reshape(12), delta_e_2000(SHARMA_LAB1[:12], SHARMA_LAB2[:12]))


def test_delta_e_2000_broadcasts_one_colour_against_many() -> None:
    reference = SHARMA_LAB2[0]
    result = delta_e_2000(reference, SHARMA_LAB1)
    assert result.shape == (len(SHARMA_TABLE_1),)
    expected = np.array([delta_e_2000(reference, lab) for lab in SHARMA_LAB1])
    assert np.array_equal(result, expected)


@pytest.mark.parametrize(
    "lab",
    [
        (0.0, 0.0, 0.0),
        (100.0, 0.0, 0.0),
        (50.0, 0.0, 0.0),
        (50.0, 2.5, 0.0),
        (50.0, 0.0, -82.7485),
        (60.2574, -34.0099, 36.2677),
        (22.7233, 20.0904, -46.6940),
    ],
)
def test_delta_e_2000_of_a_colour_with_itself_is_zero(lab: Lab) -> None:
    result = delta_e_2000(np.array(lab), np.array(lab))
    assert float(result) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize(("pair", "lab1", "lab2", "expected"), SHARMA_TABLE_1, ids=SHARMA_IDS)
def test_delta_e_2000_is_symmetric(pair: int, lab1: Lab, lab2: Lab, expected: float) -> None:
    del expected  # the published value is checked elsewhere; only the order matters here
    forward = delta_e_2000(np.array(lab1), np.array(lab2))
    backward = delta_e_2000(np.array(lab2), np.array(lab1))
    assert float(forward) == float(backward), f"Sharma pair {pair}"


@pytest.mark.parametrize(
    ("lab1", "lab2", "expected"),
    [
        # Both achromatic (a = b = 0, hue undefined): only the lightness term remains.
        # Mean L* = 50 gives S_L = 1, so Delta E00 = Delta L* exactly.
        ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), 100.0),
        # Mean L* = 55: S_L = 1 + 0.015 * 25 / sqrt(20 + 25), Delta E00 = 10 / S_L.
        ((50.0, 0.0, 0.0), (60.0, 0.0, 0.0), 9.4706),
    ],
)
def test_delta_e_2000_between_greys_is_finite_and_warning_free(
    lab1: Lab, lab2: Lab, expected: float
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = delta_e_2000(np.array(lab1), np.array(lab2))
    assert abs(float(result) - expected) < DELTA_E_TOLERANCE


@pytest.mark.parametrize(
    ("lab1", "lab2"),
    [
        (np.zeros(4), np.zeros(4)),
        (np.zeros((5, 4)), np.zeros((5, 4))),
        (np.zeros((5, 2)), np.zeros((5, 2))),
        (np.zeros(3), np.zeros(4)),
    ],
    ids=["last-axis-4", "batch-last-axis-4", "batch-last-axis-2", "one-side-wrong"],
)
def test_delta_e_2000_rejects_a_last_axis_other_than_3(
    lab1: npt.NDArray[np.float64], lab2: npt.NDArray[np.float64]
) -> None:
    with pytest.raises(ValueError):
        delta_e_2000(lab1, lab2)


# ------------------------------------------------------------------------ all-pairs matrix


def test_delta_e_2000_matrix_three_against_four_matches_each_pair() -> None:
    lab1 = np.array([(0.0, 0.0, 0.0), (50.0, 2.5, 0.0), (60.2574, -34.0099, 36.2677)])
    lab2 = np.array(
        [
            (100.0, 0.0, 0.0),
            (50.0, 0.0, -82.7485),
            (73.0, 25.0, -18.0),
            (50.0, 2.5, 0.0),
        ]
    )
    result = delta_e_2000_matrix(lab1, lab2)
    assert result.shape == (3, 4)
    assert result.dtype == np.float64
    for i in range(3):
        for j in range(4):
            assert result[i, j] == delta_e_2000(lab1[i], lab2[j]), f"entry [{i}, {j}]"


def test_delta_e_2000_matrix_diagonal_of_sharma_pairs_gives_the_published_values() -> None:
    result = delta_e_2000_matrix(SHARMA_LAB1, SHARMA_LAB2)
    count = len(SHARMA_TABLE_1)
    assert result.shape == (count, count)
    assert np.all(np.abs(np.diag(result) - SHARMA_DELTA_E) < DELTA_E_TOLERANCE)


def test_delta_e_2000_matrix_of_one_colour_against_one_is_one_by_one() -> None:
    result = delta_e_2000_matrix(SHARMA_LAB1[:1], SHARMA_LAB2[:1])
    assert result.shape == (1, 1)
    assert abs(result[0, 0] - SHARMA_DELTA_E[0]) < DELTA_E_TOLERANCE


@pytest.mark.parametrize(
    ("lab1", "lab2"),
    [
        (np.zeros(3), np.zeros((4, 3))),
        (np.zeros((3, 3)), np.zeros(3)),
        (np.zeros((3, 4)), np.zeros((4, 3))),
        (np.zeros((3, 3)), np.zeros((4, 2))),
        (np.zeros((2, 3, 3)), np.zeros((4, 3))),
    ],
    ids=["lab1-1d", "lab2-1d", "lab1-4-columns", "lab2-2-columns", "lab1-3d"],
)
def test_delta_e_2000_matrix_rejects_anything_but_two_dimensional_with_3_columns(
    lab1: npt.NDArray[np.float64], lab2: npt.NDArray[np.float64]
) -> None:
    with pytest.raises(ValueError):
        delta_e_2000_matrix(lab1, lab2)


# ---------------------------------------------------------------------------- sRGB -> Lab


@pytest.mark.parametrize(("rgb", "expected"), SRGB_TO_LAB_REFERENCES, ids=str)
def test_srgb_to_lab_matches_reference_values(rgb: Rgb, expected: Lab) -> None:
    result = srgb_to_lab(np.array(rgb))
    assert result.shape == (3,)
    assert result.dtype == np.float64
    assert np.all(np.abs(result - np.array(expected)) < LAB_TOLERANCE), result


def test_srgb_to_lab_accepts_a_plain_list() -> None:
    result = srgb_to_lab([255, 0, 0])
    assert np.all(np.abs(result - np.array((53.2408, 80.0925, 67.2032))) < LAB_TOLERANCE)


def test_srgb_to_lab_gives_the_same_result_for_uint8_int_and_float_input() -> None:
    # uint8 is what an image library hands over; arithmetic on it must not wrap around.
    values = [(255, 255, 255), (200, 100, 50), (0, 0, 0)]
    from_uint8 = srgb_to_lab(np.array(values, dtype=np.uint8))
    from_int = srgb_to_lab(np.array(values, dtype=np.int64))
    from_float = srgb_to_lab(np.array(values, dtype=np.float64))
    assert np.array_equal(from_uint8, from_int)
    assert np.array_equal(from_uint8, from_float)
    assert np.all(np.abs(from_uint8[0] - np.array((100.0, 0.0, 0.0))) < LAB_TOLERANCE)


def test_srgb_to_lab_of_an_image_keeps_its_shape_and_equals_per_pixel_calls() -> None:
    # 2 rows x 3 columns, not square: red, green, blue / white, black, grey.
    image = np.array(
        [
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
            [(255, 255, 255), (0, 0, 0), (128, 128, 128)],
        ],
        dtype=np.uint8,
    )
    result = srgb_to_lab(image)
    assert result.shape == (2, 3, 3)
    assert result.dtype == np.float64
    for row in range(2):
        for col in range(3):
            assert np.array_equal(result[row, col], srgb_to_lab(image[row, col])), (row, col)
    assert np.all(np.abs(result[0, 0] - np.array((53.2408, 80.0925, 67.2032))) < LAB_TOLERANCE)
    assert np.all(np.abs(result[1, 1] - np.array((0.0, 0.0, 0.0))) < LAB_TOLERANCE)


def test_srgb_to_lab_of_a_one_pixel_image_is_one_by_one() -> None:
    result = srgb_to_lab(np.array([[(0, 0, 255)]], dtype=np.uint8))
    assert result.shape == (1, 1, 3)
    assert np.all(np.abs(result[0, 0] - np.array((32.2970, 79.1875, -107.8602))) < LAB_TOLERANCE)


@pytest.mark.parametrize(
    "rgb",
    [
        [256, 0, 0],
        [0, -1, 0],
        [0, 0, 1000],
        [255.5, 0.0, 0.0],
        [-0.5, 0.0, 0.0],
        [np.nan, 0.0, 0.0],
        [np.inf, 0.0, 0.0],
    ],
    ids=["256", "minus-1", "1000", "255.5", "minus-0.5", "nan", "inf"],
)
def test_srgb_to_lab_rejects_values_outside_0_255(rgb: list[float]) -> None:
    with pytest.raises(ValueError):
        srgb_to_lab(np.array(rgb))


def test_srgb_to_lab_rejects_one_bad_pixel_in_an_image() -> None:
    image = np.zeros((2, 2, 3), dtype=np.int64)
    image[1, 0, 2] = 256
    with pytest.raises(ValueError):
        srgb_to_lab(image)


@pytest.mark.parametrize(
    "shape",
    [(4,), (2,), (2, 2, 4), (5, 1)],
    ids=["rgba", "two-values", "rgba-image", "batch-of-one-value"],
)
def test_srgb_to_lab_rejects_a_last_axis_other_than_3(shape: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        srgb_to_lab(np.zeros(shape, dtype=np.uint8))


def test_colour_imports_only_numpy_and_the_standard_library() -> None:
    allowed = set(sys.stdlib_module_names) | {"numpy"}
    package_dir = Path(colour.__file__).parent
    imported = set()
    for path in package_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    assert imported, "the scan found no imports at all"
    assert imported <= allowed, f"unexpected imports: {sorted(imported - allowed)}"


def _random_lab(rng: np.random.Generator, count: int) -> npt.NDArray[np.float64]:
    return np.column_stack(
        [rng.uniform(0, 100, count), rng.uniform(-128, 128, count), rng.uniform(-128, 128, count)]
    )


def test_delta_e_2000_batch_equals_per_pair_calls_on_random_pairs() -> None:
    # The Sharma pairs alone do not catch a one-ulp gap between numpy's scalar and array
    # loops: thousands of seeded random pairs do.
    rng = np.random.default_rng(0)
    first, second = _random_lab(rng, 3000), _random_lab(rng, 3000)
    single = [float(delta_e_2000(a, b)) for a, b in zip(first, second, strict=True)]
    assert np.array_equal(delta_e_2000(first, second), single)


def test_srgb_to_lab_batch_equals_per_colour_calls_on_random_colours() -> None:
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, (3000, 3))
    assert np.array_equal(srgb_to_lab(rgb), [srgb_to_lab(colour) for colour in rgb])
