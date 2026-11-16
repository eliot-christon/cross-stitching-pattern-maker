"""`scripts/bench_inputs.py`, on folders of generated files only."""

from pathlib import Path

import numpy as np
import pytest
from bench_inputs import SHEET_NAME, main, run
from PIL import Image

PALETTE = np.array([[0, 0, 0], [255, 255, 255], [214, 64, 52], [60, 120, 200]], dtype=np.uint8)
ART = PALETTE[np.random.default_rng(5).integers(0, len(PALETTE), size=(10, 12))]


@pytest.fixture(name="inputs")
def _inputs(tmp_path: Path) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    Image.fromarray(ART).resize((120, 100), Image.Resampling.NEAREST).save(folder / "art.png")
    ramp = np.linspace(0, 255, 200).astype(np.uint8)
    Image.fromarray(np.tile(ramp, (120, 1))).save(folder / "gradient.png")
    (folder / "x.pdf").write_bytes(b"%PDF-1.4 not really")
    return folder


def test_one_sheet_and_one_row_per_file_in_name_order(inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"

    rows = run(inputs, output)

    assert [row.name for row in rows] == ["art.png", "gradient.png", "x.pdf"]
    assert [p.name for p in output.iterdir()] == [SHEET_NAME]
    with Image.open(output / SHEET_NAME) as sheet:
        assert sheet.format == "PNG"


def test_each_row_says_what_was_found_and_made(inputs: Path, tmp_path: Path) -> None:
    art, gradient, pdf = run(inputs, tmp_path / "out")

    assert art.inspection is not None
    assert art.inspection["kind"] == "pixel_art"
    assert art.inspection["grid"] == {"width": 12, "height": 10, "colours": 4}
    assert art.found.startswith("pixel_art: ")
    assert art.pattern is not None
    assert (art.pattern["width"], art.pattern["height"]) == (12, 10)
    assert gradient.found.startswith("picture: ")
    assert gradient.pattern is not None
    assert pdf.inspection is not None
    assert pdf.inspection["refusal"]
    assert pdf.inspection["refusal"] in pdf.found
    assert pdf.pattern is None
    assert pdf.pattern_error == pdf.inspection["refusal"]


def test_a_file_that_is_no_image_carries_the_apis_error(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "notes.txt").write_bytes(b"not an image")

    (row,) = run(folder, tmp_path / "out")

    assert row.inspection is None
    assert row.found == f"error: {row.inspection_error}"
    assert row.pattern is None
    assert row.pattern_error


def test_an_empty_folder_gives_no_rows_and_no_sheet(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    output = tmp_path / "out"

    assert run(folder, output) == []
    assert not output.exists()


def test_a_missing_folder_exits_non_zero_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere"

    assert main([str(missing), str(tmp_path / "out")]) != 0
    assert str(missing) in capsys.readouterr().err


def test_main_prints_the_table(
    inputs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(inputs), str(tmp_path / "out")]) == 0

    printed = capsys.readouterr().out
    for name in ("art.png", "gradient.png", "x.pdf"):
        assert name in printed
