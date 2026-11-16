"""The `crop` field of `POST /images/inspect` and the pattern routes."""

import io
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageOps
from pypdf import PdfReader

from cross_stitch.api.app import app
from cross_stitch.threads import nearest_dmc

client = TestClient(app)

RED = (214, 40, 40)
BLUE = (40, 70, 200)
PALETTE = np.array([[0, 0, 0], [255, 255, 255], [214, 64, 52], [60, 120, 200]], dtype=np.uint8)
ART = PALETTE[np.random.default_rng(5).integers(0, len(PALETTE), size=(10, 12))]


def _png(image: Image.Image, **params: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **params)
    return buffer.getvalue()


def _halves() -> bytes:
    """40 x 30: the left half red, the right half blue."""
    image = Image.new("RGB", (40, 30), RED)
    image.paste(BLUE, (20, 0, 40, 30))
    return _png(image)


def _codes(body: dict[str, Any]) -> set[str]:
    return {entry["code"] for entry in body["key"]}


def _nearest(rgb: tuple[int, int, int]) -> str:
    return nearest_dmc(np.array([rgb], dtype=np.uint8))[0].code


def _pattern(upload: bytes, route: str = "/patterns", **fields: str) -> Any:
    data = {"width": "20", "max_colours": "4", **fields}
    return client.post(route, data=data, files={"image": ("a.png", upload, "image/png")})


def _inspect(upload: bytes, **fields: str) -> Any:
    return client.post(
        "/images/inspect", data=fields, files={"image": ("a.png", upload, "image/png")}
    )


def test_a_box_keeps_only_what_is_inside_it() -> None:
    body = _pattern(_halves(), crop="20,0,40,30").json()

    assert _codes(body) == {_nearest(BLUE)}


def test_no_box_reads_the_whole_image() -> None:
    assert _codes(_pattern(_halves()).json()) == {_nearest(RED), _nearest(BLUE)}


def test_inspection_reads_the_cropped_image() -> None:
    art = Image.fromarray(ART).resize((120, 100), Image.Resampling.NEAREST)
    ramp = np.linspace(0, 255, 300).astype(np.uint8)
    page = Image.fromarray(np.tile(ramp, (200, 1))).convert("RGB")
    page.paste(art, (37, 23))
    upload = _png(page)

    # Uncropped, the page around the art is read too (at one pixel per cell, here).
    assert _inspect(upload).json()["grid"] != {"width": 12, "height": 10, "colours": 4}
    body = _inspect(upload, crop="37,23,157,123").json()
    assert body["kind"] == "pixel_art"
    assert body["grid"] == {"width": 12, "height": 10, "colours": 4}


def test_the_box_is_in_pixels_of_the_upright_image() -> None:
    upright = Image.new("RGB", (20, 40), RED)
    upright.paste(BLUE, (0, 20, 20, 40))
    stored = upright.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to show upright.
    upload = _png(stored, exif=exif)
    assert ImageOps.exif_transpose(Image.open(io.BytesIO(upload))).size == (20, 40)

    body = _pattern(upload, crop="0,0,20,20").json()

    assert _codes(body) == {_nearest(RED)}


@pytest.mark.parametrize(
    "box",
    [
        "10,10,10,20",  # empty
        "30,0,10,30",  # right before left
        "0,0,41,30",  # past the right edge
        "-1,0,10,10",  # past the left edge
        "0,0,10",  # not four numbers
        "a,b,c,d",
    ],
)
def test_a_bad_box_is_a_422_naming_crop(box: str) -> None:
    for response in (_inspect(_halves(), crop=box), _pattern(_halves(), crop=box)):
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "crop"]


def test_both_routes_take_the_same_box() -> None:
    pattern = _pattern(_halves(), crop="20,0,40,30")
    pdf = _pattern(_halves(), route="/patterns/pdf", crop="20,0,40,30")

    assert pattern.status_code == pdf.status_code == 200
    assert (pattern.json()["width"], pattern.json()["height"]) == (20, 30)
    cover = next(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Size: 20 x 30 stitches" in cover
