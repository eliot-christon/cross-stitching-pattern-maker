"""The image adjustment fields of `POST /images/inspect` and the pattern routes."""

from typing import Any

import numpy as np
import pytest
from api_helpers import ADJUSTMENT_LIMITS, png, stripes
from fastapi.testclient import TestClient
from PIL import Image

from cross_stitch.api.app import app
from cross_stitch.export import render_pdf
from cross_stitch.pattern import (
    EMPTY,
    Adjustments,
    Pattern,
    adjust_image,
    convert_image,
    find_pixel_grid,
    unscale_pixel_art,
)

client = TestClient(app)

ADJUSTMENTS: dict[str, dict[str, float]] = ADJUSTMENT_LIMITS
ROUTES = ["/images/inspect", "/patterns", "/patterns/pdf"]


def _post(route: str, image: Image.Image, **fields: str) -> Any:
    data = fields if route == "/images/inspect" else {"width": "40", "max_colours": "4", **fields}
    return client.post(route, data=data, files={"image": ("a.png", png(image), "image/png")})


def _ok(route: str, image: Image.Image, **fields: str) -> Any:
    response = _post(route, image, **fields)
    assert response.status_code == 200, response.text
    return response


def _codes(body: dict[str, Any]) -> set[str]:
    return {entry["code"] for entry in body["key"]}


def _cells(body: dict[str, Any]) -> list[list[str | None]]:
    """Each cell's DMC code, `None` for bare fabric."""
    codes = [entry["code"] for entry in body["key"]]
    return [[None if cell is None else codes[cell] for cell in row] for row in body["grid"]]


def _core_cells(pattern: Pattern) -> list[list[str | None]]:
    codes = [entry.thread.code for entry in pattern.key]
    return [[None if cell == EMPTY else codes[cell] for cell in row] for row in pattern.grid]


def test_limits_report_the_six_adjustments() -> None:
    settings = client.get("/limits").json()["settings"]

    assert {name: settings[name] for name in ADJUSTMENTS} == ADJUSTMENTS


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("name", list(ADJUSTMENTS))
def test_a_value_out_of_range_is_a_422_naming_the_field(route: str, name: str) -> None:
    setting = ADJUSTMENTS[name]
    for value in (setting["min"] - setting["step"], setting["max"] + setting["step"], "nan"):
        response = _post(route, stripes(), **{name: str(value)})

        assert response.status_code == 422, (name, value)
        assert response.json()["detail"][0]["loc"] == ["body", name]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("name", list(ADJUSTMENTS))
def test_each_reported_bound_is_accepted(route: str, name: str) -> None:
    for bound in ("min", "max"):
        _ok(route, stripes(), **{name: str(ADJUSTMENTS[name][bound])})


def test_no_saturation_leaves_only_greys_in_the_key() -> None:
    body = _ok("/patterns", stripes(), saturation="-100").json()

    assert not _codes(body) & {"321", "797"}


def _edge_outside_the_box() -> Image.Image:
    """20 x 10: grey 100 on the left half, grey 200 from column 10, the box's right edge."""
    pixels = np.full((10, 20, 3), 100, dtype=np.uint8)
    pixels[:, 10:] = 200
    return Image.fromarray(pixels)


def test_the_crop_comes_before_the_adjustments() -> None:
    image = _edge_outside_the_box()
    sharper = Adjustments(sharpness=100)
    box = (0, 0, 10, 10)

    body = _ok(
        "/patterns", image, width="10", max_colours="2", crop="0,0,10,10", sharpness="100"
    ).json()

    cropped_first = convert_image(adjust_image(image.crop(box), sharper), width=10, max_colours=2)
    adjusted_first = convert_image(adjust_image(image, sharper).crop(box), width=10, max_colours=2)
    assert _cells(body) == _core_cells(cropped_first)
    assert _core_cells(cropped_first) != _core_cells(adjusted_first)


# Two colours of about the same luma (Rec. 601, the greys of no saturation) and white.
ART_PALETTE = np.array([[200, 80, 80], [60, 150, 90], [255, 255, 255]], dtype=np.uint8)


def _pixel_art() -> Image.Image:
    """12 x 10 art pixels of `ART_PALETTE`, each 8 x 8 pixels."""
    indices = np.random.default_rng(7).integers(0, len(ART_PALETTE), size=(10, 12))
    art = Image.fromarray(ART_PALETTE[indices])
    return art.resize((96, 80), Image.Resampling.NEAREST)


def test_the_inspection_reads_the_adjusted_image() -> None:
    plain = _ok("/images/inspect", _pixel_art()).json()
    grey = _ok("/images/inspect", _pixel_art(), saturation="-100").json()

    assert plain["grid"] == {"width": 12, "height": 10, "colours": 3}
    assert grey["grid"] == {"width": 12, "height": 10, "colours": 2}


def test_a_grid_kind_reduces_the_adjusted_image() -> None:
    adjusted = adjust_image(_pixel_art(), Adjustments(hue=180))
    grid = find_pixel_grid(adjusted)
    assert grid is not None
    expected = convert_image(unscale_pixel_art(adjusted, grid), width=grid.columns, max_colours=4)

    body = _ok("/patterns", _pixel_art(), read_as="pixel_art", hue="180").json()

    assert _cells(body) == _core_cells(expected)


def test_the_pdf_shows_the_adjusted_image() -> None:
    expected = convert_image(
        adjust_image(stripes(), Adjustments(saturation=-100)), width=40, max_colours=4
    )

    pdf = _ok("/patterns/pdf", stripes(), saturation="-100").content

    assert pdf == render_pdf(expected)
    assert pdf != _ok("/patterns/pdf", stripes()).content


@pytest.mark.parametrize("route", ROUTES)
def test_defaults_sent_explicitly_change_nothing(route: str) -> None:
    defaults = {name: str(setting["default"]) for name, setting in ADJUSTMENTS.items()}

    assert _ok(route, stripes(), **defaults).content == _ok(route, stripes()).content
