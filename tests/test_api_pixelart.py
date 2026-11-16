"""`POST /images/inspect` and the `read_as` field of the pattern routes."""

import io
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from cross_stitch.api.app import MAX_COLOURS, app
from cross_stitch.threads import nearest_dmc

client = TestClient(app)

PALETTE = np.array([[0, 0, 0], [255, 255, 255], [214, 64, 52], [60, 120, 200]], dtype=np.uint8)
ART = PALETTE[np.random.default_rng(5).integers(0, len(PALETTE), size=(10, 12))]
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _enlarged() -> bytes:
    """The 12 x 10 art enlarged 10.4 times, as pixel art is often shared."""
    return _png(Image.fromarray(ART).resize((125, 104), Image.Resampling.NEAREST))


def _gradient() -> bytes:
    ramp = np.linspace(0, 255, 200).astype(np.uint8)
    return _png(Image.fromarray(np.tile(ramp, (120, 1))))


def _inspect(upload: bytes) -> Any:
    return client.post("/images/inspect", files={"image": ("art.png", upload, "image/png")})


def _pattern(upload: bytes, **fields: str) -> Any:
    data = {"width": "12", "max_colours": "4", **fields}
    return client.post("/patterns", data=data, files={"image": ("art.png", upload, "image/png")})


def test_inspect_gives_the_kind_grid_and_description_of_pixel_art() -> None:
    response = _inspect(_enlarged())

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "pixel_art"
    assert body["grid"] == {"width": 12, "height": 10, "colours": 4}
    assert body["warnings"] == []
    assert body["refusal"] is None
    assert "12 x 10" in body["description"]


def test_inspect_gives_picture_for_an_image_with_no_grid() -> None:
    body = _inspect(_gradient()).json()

    assert body["kind"] == "picture"
    assert body["grid"] is None
    assert body["refusal"] is None


def test_inspect_caps_the_colours_at_the_limit_and_warns() -> None:
    levels = np.arange(30 * 30, dtype=np.int64)
    art = np.stack([levels % 30 * 8, levels // 30 * 8, (levels * 7) % 256], -1).astype(np.uint8)
    upload = _png(
        Image.fromarray(art.reshape(30, 30, 3)).resize((90, 90), Image.Resampling.NEAREST)
    )

    body = _inspect(upload).json()

    assert body["grid"]["colours"] == MAX_COLOURS
    assert len(body["warnings"]) == 1
    assert str(MAX_COLOURS) in body["warnings"][0]


def test_a_pdf_is_refused_in_words_on_inspect_and_on_the_pattern_routes() -> None:
    inspected = _inspect(PDF)

    assert inspected.status_code == 200
    body = inspected.json()
    assert body["kind"] is None
    assert "PDF" in body["refusal"]
    converted = _pattern(PDF)
    assert converted.status_code == 400
    assert converted.json()["detail"] == body["refusal"]


def test_bytes_that_are_no_image_are_a_400_on_both() -> None:
    assert _inspect(b"not an image").status_code == 400
    assert _pattern(b"not an image").status_code == 400


def test_read_as_pixel_art_gives_one_stitch_per_art_pixel_whatever_the_width() -> None:
    response = _pattern(_enlarged(), width="50", read_as="pixel_art")

    assert response.status_code == 200
    body = response.json()
    assert (body["width"], body["height"]) == (12, 10)
    codes = [body["key"][cell]["code"] for row in body["grid"] for cell in row]
    assert codes == [thread.code for thread in nearest_dmc(ART.reshape(-1, 3))]


def test_read_as_picture_is_the_default_and_converts_as_a_picture() -> None:
    # Cropped by 5 pixels, as a screenshot is: stitches no longer line up on art pixels.
    shifted = Image.open(io.BytesIO(_enlarged())).crop((5, 5, 125, 104))
    upload = _png(shifted)
    plain = _pattern(upload, max_colours="20").json()
    assert plain == _pattern(upload, max_colours="20", read_as="picture").json()
    # As a picture, stitches straddle art pixels and blend them into more colours.
    assert len(plain["key"]) > len(PALETTE)
    art = _pattern(upload, max_colours="20", read_as="pixel_art").json()
    assert len(art["key"]) == len(PALETTE)


def test_read_as_pixel_art_on_an_image_with_no_grid_is_a_422_naming_it() -> None:
    response = _pattern(_gradient(), read_as="pixel_art")

    assert response.status_code == 422
    assert "read_as" in response.json()["detail"]


def test_an_unknown_read_as_is_a_422_naming_it() -> None:
    response = _pattern(_enlarged(), read_as="sideways")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "read_as"]


def test_both_routes_take_read_as() -> None:
    files = {"image": ("art.png", _enlarged(), "image/png")}
    data = {"width": "12", "max_colours": "4", "read_as": "pixel_art"}
    response = client.post("/patterns/pdf", data=data, files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
