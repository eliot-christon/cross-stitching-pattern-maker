"""The DMC stranded cotton table and the nearest-thread lookup.

Pinned values are copied from `src/cross_stitch/threads/dmc.csv`, itself a byte-for-byte copy
of makebead/craft-color-codes `data/csv/dmc-floss.csv` at commit
84dbdc26a961247f2aba58c91f314966a38e64ae (see `threads/DMC_SOURCE.md`). Thread tables are
facts: no pinned case below may be removed.
"""

import csv
import dataclasses
import hashlib
import io
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

import cross_stitch
from cross_stitch.colour import delta_e_2000, srgb_to_lab
from cross_stitch.threads import (
    Thread,
    dmc_thread,
    dmc_threads,
    nearest_dmc,
    nearest_dmc_lab,
    nearest_indices,
)

type Rgb = tuple[int, int, int]
type Lab = tuple[float, float, float]

# Stated by DMC_SOURCE.md; the source file has 489 data rows.
SOURCE_ROW_COUNT = 489
SOURCE_SHA256 = "66ebd107ace9f373edc185743d2699fc037e46c36428d72c0e8591d695aa0326"
PRE_COMMIT_SIZE_CAP_BYTES = 1024 * 1024

# (code as stored, name as loaded, RGB): literal values from the source CSV.
PINNED_THREADS: list[tuple[str, str, Rgb]] = [
    ("310", "Black", (0, 0, 0)),
    ("Blanc", "White", (252, 251, 248)),
    ("Ecru", "Ecru", (240, 234, 218)),
    ("B5200", "Snow White", (255, 255, 255)),
    ("321", "Red", (199, 43, 59)),
    ("666", "Bright Red", (227, 29, 66)),
    ("797", "Royal Blue", (19, 71, 125)),
    ("3865", "Winter White", (249, 247, 241)),
    ("150", "Dusty Rose Ultra Very Dark", (171, 2, 73)),
    ("815", "Garnet Medium", (135, 7, 31)),
    ("3371", "Black Brown", (30, 17, 8)),
    ("309", "Rose Dark", (193, 32, 65)),
    ("3713", "Salmon Very Light", (255, 226, 226)),
    ("01", "White Tin", (227, 227, 230)),
    ("35", "Fuschia Very Dark", (70, 5, 45)),
    # Source spelling kept as-is: the typo "Darkv" and the lower-case "medium".
    ("3802", "Antique Mauve Very Darkv", (113, 65, 73)),
    ("19", "Autumn Gold medium Light", (247, 201, 95)),
    # The source has a double space in these two names; it collapses to one at load.
    ("552", "Violet Medium", (128, 58, 107)),
    ("158", "Cornflower Blue Very Dark", (76, 82, 110)),
]

# Codes whose loaded name differs from the source cell, and the raw source cell.
NAMES_WITH_COLLAPSED_SPACES = {
    "552": "Violet  Medium",
    "158": "Cornflower Blue  Very Dark",
}


def _source_rows() -> list[dict[str, str]]:
    text = files("cross_stitch.threads").joinpath("dmc.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _codes(threads: tuple[Thread, ...]) -> list[str]:
    return [thread.code for thread in threads]


# ------------------------------------------------------------------------- the data file


def test_shipped_csv_is_byte_for_byte_the_recorded_source() -> None:
    data = files("cross_stitch.threads").joinpath("dmc.csv").read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA256


def test_shipped_csv_is_under_the_pre_commit_size_cap() -> None:
    data = files("cross_stitch.threads").joinpath("dmc.csv").read_bytes()
    assert 0 < len(data) < PRE_COMMIT_SIZE_CAP_BYTES


def test_table_loads_from_a_relocated_package_outside_the_repo(tmp_path: Path) -> None:
    # The package is copied alone into tmp_path and imported from there, in a fresh
    # interpreter whose working directory is tmp_path: a path relative to the repo root or
    # to the working directory finds nothing, only data shipped inside the package loads.
    shutil.copytree(
        Path(cross_stitch.__file__).parent,
        tmp_path / "cross_stitch",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import cross_stitch.threads as threads\n"
        "assert Path(threads.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())\n"
        "print(len(threads.dmc_threads()), threads.dmc_thread('blanc').code)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [str(SOURCE_ROW_COUNT), "Blanc"]


# ------------------------------------------------------------------------------- the table


@pytest.mark.parametrize(
    ("code", "name", "rgb"), PINNED_THREADS, ids=[t[0] for t in PINNED_THREADS]
)
def test_pinned_code_has_its_source_name_and_rgb(code: str, name: str, rgb: Rgb) -> None:
    assert dmc_thread(code) == Thread(code=code, name=name, rgb=rgb)


def test_table_has_the_source_row_count() -> None:
    assert len(dmc_threads()) == SOURCE_ROW_COUNT


def test_table_keeps_the_source_order() -> None:
    codes = _codes(dmc_threads())
    assert codes == [row["code"] for row in _source_rows()]
    assert codes[0] == "3713"
    assert codes[-1] == "35"


def test_every_row_has_the_source_code_and_rgb_exactly() -> None:
    for thread, row in zip(dmc_threads(), _source_rows(), strict=True):
        assert thread.code == row["code"]
        assert thread.rgb == (int(row["r"]), int(row["g"]), int(row["b"])), thread.code


def test_names_equal_the_source_except_the_two_collapsed_double_spaces() -> None:
    changed = {}
    for thread, row in zip(dmc_threads(), _source_rows(), strict=True):
        if thread.name != row["name"]:
            changed[thread.code] = row["name"]
    assert changed == NAMES_WITH_COLLAPSED_SPACES


def test_no_name_has_a_run_of_spaces_or_surrounding_whitespace() -> None:
    for thread in dmc_threads():
        assert thread.name, thread.code
        assert thread.name == thread.name.strip(), thread.code
        assert "  " not in thread.name, thread.code


def test_codes_are_unique_even_when_casefolded() -> None:
    codes = _codes(dmc_threads())
    assert len(set(codes)) == len(codes)
    assert len({code.casefold() for code in codes}) == len(codes)


def test_codes_are_non_empty_strings_without_surrounding_whitespace() -> None:
    for code in _codes(dmc_threads()):
        assert isinstance(code, str)
        assert code
        assert code == code.strip()


def test_every_rgb_component_is_an_int_in_0_255() -> None:
    for thread in dmc_threads():
        assert len(thread.rgb) == 3, thread.code
        for component in thread.rgb:
            # A plain int: not a bool, not a numpy integer (which is no subclass of int).
            assert isinstance(component, int), thread.code
            assert not isinstance(component, bool), thread.code
            assert 0 <= component <= 255, thread.code


def test_no_two_rows_share_an_rgb() -> None:
    rgbs = [thread.rgb for thread in dmc_threads()]
    assert len(set(rgbs)) == len(rgbs)


def test_dmc_threads_returns_the_same_cached_tuple() -> None:
    first = dmc_threads()
    assert isinstance(first, tuple)
    assert dmc_threads() is first


def test_thread_is_frozen() -> None:
    thread = dmc_thread("310")
    with pytest.raises(dataclasses.FrozenInstanceError):
        thread.code = "321"  # type: ignore[misc]


# ------------------------------------------------------------------------ lookup by code


@pytest.mark.parametrize(
    ("query", "stored"),
    [
        ("blanc", "Blanc"),
        ("BLANC", "Blanc"),
        (" Blanc ", "Blanc"),
        ("ecru", "Ecru"),
        ("ECRU", "Ecru"),
        ("b5200", "B5200"),
        ("\t310\n", "310"),
        ("01", "01"),
        (" 35", "35"),
    ],
)
def test_lookup_ignores_case_and_surrounding_whitespace_and_returns_stored_spelling(
    query: str, stored: str
) -> None:
    thread = dmc_thread(query)
    assert thread.code == stored
    assert thread in dmc_threads()


@pytest.mark.parametrize(
    "code",
    ["White", "white", "1", "001", "9999", "3105", "B 5200", "Blanc White", "", "   "],
)
def test_unknown_code_raises_key_error(code: str) -> None:
    with pytest.raises(KeyError):
        dmc_thread(code)


@pytest.mark.parametrize("code", ["9999", "White"])
def test_unknown_code_error_names_the_code(code: str) -> None:
    with pytest.raises(KeyError) as error:
        dmc_thread(code)
    assert code in str(error.value)


# ------------------------------------------------------------------------ nearest_indices


def test_nearest_indices_picks_the_closest_palette_colour() -> None:
    palette = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
    lab = [(10.0, 0.0, 0.0), (60.0, 0.0, 0.0), (95.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
    result = nearest_indices(lab, palette)
    assert result.shape == (4,)
    assert result.dtype == np.intp
    assert result.tolist() == [0, 1, 2, 0]


@pytest.mark.parametrize(
    ("palette", "lab", "expected"),
    [
        ([(50.0, 0.0, 0.0), (50.0, 0.0, 0.0)], (60.0, 0.0, 0.0), 0),
        ([(0.0, 0.0, 0.0), (50.0, 10.0, -10.0), (50.0, 10.0, -10.0)], (50.0, 10.0, -10.0), 1),
        ([(100.0, 0.0, 0.0), (20.0, 5.0, 5.0), (20.0, 5.0, 5.0)], (22.0, 5.0, 5.0), 1),
        # Two distinct greys at exactly the same CIEDE2000 distance (checked below).
        ([(60.0, 0.0, 0.0), (40.0, 0.0, 0.0)], (50.0, 0.0, 0.0), 0),
        ([(40.0, 0.0, 0.0), (60.0, 0.0, 0.0)], (50.0, 0.0, 0.0), 0),
    ],
    ids=[
        "duplicate-pair",
        "duplicate-exact-match",
        "duplicate-after-a-farther-colour",
        "greys-lighter-first",
        "greys-darker-first",
    ],
)
def test_nearest_indices_tie_goes_to_the_lowest_index(
    palette: list[Lab], lab: Lab, expected: int
) -> None:
    assert nearest_indices([lab], palette).tolist() == [expected]


def test_grey_tie_is_exact_so_the_tie_cases_mean_something() -> None:
    query = np.array([50.0, 0.0, 0.0])
    darker = delta_e_2000(query, np.array([40.0, 0.0, 0.0]))
    lighter = delta_e_2000(query, np.array([60.0, 0.0, 0.0]))
    assert float(darker) == float(lighter)


def test_nearest_indices_tie_rule_holds_inside_a_batch() -> None:
    palette = [(40.0, 0.0, 0.0), (60.0, 0.0, 0.0), (60.0, 0.0, 0.0)]
    lab = [(50.0, 0.0, 0.0), (60.0, 0.0, 0.0), (70.0, 0.0, 0.0), (30.0, 0.0, 0.0)]
    assert nearest_indices(lab, palette).tolist() == [0, 1, 1, 0]


def test_nearest_indices_of_no_colours_is_empty() -> None:
    result = nearest_indices(np.zeros((0, 3)), [(50.0, 0.0, 0.0)])
    assert result.shape == (0,)
    assert result.dtype == np.intp


def test_nearest_indices_rejects_an_empty_palette() -> None:
    with pytest.raises(ValueError):
        nearest_indices([(50.0, 0.0, 0.0)], np.zeros((0, 3)))


@pytest.mark.parametrize(
    ("lab", "palette"),
    [
        (np.zeros(3), np.zeros((2, 3))),
        (np.zeros((2, 3)), np.zeros(3)),
        (np.zeros((2, 4)), np.zeros((2, 3))),
        (np.zeros((2, 2, 3)), np.zeros((2, 3))),
    ],
    ids=["lab-1d", "palette-1d", "lab-4-columns", "lab-3d"],
)
def test_nearest_indices_rejects_anything_but_n_by_3(
    lab: npt.NDArray[np.float64], palette: npt.NDArray[np.float64]
) -> None:
    with pytest.raises(ValueError):
        nearest_indices(lab, palette)


# ---------------------------------------------------------------------- nearest DMC thread


def test_pure_black_is_310() -> None:
    assert _codes(nearest_dmc([(0, 0, 0)])) == ["310"]


@pytest.mark.parametrize(
    ("rgb", "code"),
    [
        ((1, 1, 1), "310"),
        ((254, 254, 254), "B5200"),
        ((200, 43, 59), "321"),
        ((19, 71, 126), "797"),
    ],
    ids=["310-plus-1", "b5200-minus-1", "321-red-plus-1", "797-blue-plus-1"],
)
def test_a_hair_off_a_thread_still_finds_it(rgb: Rgb, code: str) -> None:
    assert _codes(nearest_dmc([rgb])) == [code]


def test_every_table_rgb_finds_its_own_row() -> None:
    threads = dmc_threads()
    assert nearest_dmc([thread.rgb for thread in threads]) == threads


def test_every_table_colour_in_lab_finds_its_own_row() -> None:
    threads = dmc_threads()
    lab = srgb_to_lab(np.array([thread.rgb for thread in threads]))
    assert nearest_dmc_lab(lab) == threads


def test_nearest_dmc_returns_the_table_threads() -> None:
    result = nearest_dmc([(199, 43, 59), (252, 251, 248)])
    assert result == (dmc_thread("321"), dmc_thread("Blanc"))
    assert all(isinstance(thread, Thread) for thread in result)


def test_nearest_dmc_batch_equals_one_call_per_colour() -> None:
    rgb = np.random.default_rng(0).integers(0, 256, (300, 3))
    batch = nearest_dmc(rgb)
    assert len(batch) == len(rgb)
    assert batch == tuple(nearest_dmc([colour])[0] for colour in rgb)


def test_nearest_dmc_equals_nearest_dmc_lab_of_the_converted_colours() -> None:
    rgb = np.random.default_rng(1).integers(0, 256, (300, 3))
    assert nearest_dmc(rgb) == nearest_dmc_lab(srgb_to_lab(rgb))


def test_nearest_dmc_gives_the_same_result_for_uint8_and_int_input() -> None:
    rgb = np.random.default_rng(2).integers(0, 256, (100, 3))
    assert nearest_dmc(rgb.astype(np.uint8)) == nearest_dmc(rgb.astype(np.int64))


def test_nearest_dmc_twice_gives_identical_results() -> None:
    rgb = np.random.default_rng(3).integers(0, 256, (300, 3))
    assert nearest_dmc(rgb) == nearest_dmc(rgb)


def test_nearest_dmc_of_no_colours_is_an_empty_tuple() -> None:
    result = nearest_dmc(np.zeros((0, 3), dtype=np.uint8))
    assert isinstance(result, tuple)
    assert not result


def test_nearest_dmc_lab_of_no_colours_is_an_empty_tuple() -> None:
    result = nearest_dmc_lab(np.zeros((0, 3)))
    assert isinstance(result, tuple)
    assert not result


@pytest.mark.parametrize(
    "rgb",
    [np.zeros(3), np.zeros((2, 4)), np.zeros((2, 2, 3)), np.zeros((2, 1))],
    ids=["one-colour-1d", "4-columns", "image-shaped", "1-column"],
)
def test_nearest_dmc_rejects_anything_but_n_by_3(rgb: npt.NDArray[np.float64]) -> None:
    with pytest.raises(ValueError):
        nearest_dmc(rgb)


@pytest.mark.parametrize(
    "lab",
    [np.zeros(3), np.zeros((2, 4)), np.zeros((2, 2, 3))],
    ids=["one-colour-1d", "4-columns", "image-shaped"],
)
def test_nearest_dmc_lab_rejects_anything_but_n_by_3(lab: npt.NDArray[np.float64]) -> None:
    with pytest.raises(ValueError):
        nearest_dmc_lab(lab)


@pytest.mark.parametrize(
    "rgb",
    [[(256, 0, 0)], [(0, -1, 0)], [(0, 0, 0), (0, 0, 300)]],
    ids=["256", "minus-1", "one-bad-in-a-batch"],
)
def test_nearest_dmc_rejects_rgb_outside_0_255(rgb: list[Rgb]) -> None:
    with pytest.raises(ValueError):
        nearest_dmc(rgb)
