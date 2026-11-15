"""The chart layout fields of `POST /patterns/pdf`: split, pages, overlap, centre lines."""

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cross_stitch.api.app import app
from cross_stitch.export import render_pdf
from cross_stitch.pattern import convert_image

client = TestClient(app)


def _image(width: int = 40, height: int = 20) -> Image.Image:
    """Vertical stripes of four colours, so every page of a split has cells to draw."""
    image = Image.new("RGB", (width, height))
    colours = [(0, 0, 0), (252, 251, 248), (199, 43, 59), (19, 71, 125)]
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), colours[(x * 4) // width])
    return image


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _post_pdf(fields: dict[str, str], image: Image.Image | None = None) -> Any:
    upload = _png(image or _image())
    data = {"width": "40", "max_colours": "4", **fields}
    return client.post("/patterns/pdf", data=data, files={"image": ("i.png", upload, "image/png")})


def test_the_layout_fields_give_the_bytes_the_core_renders() -> None:
    fields = {
        "split": "pages",
        "pages_across": "3",
        "pages_down": "1",
        "overlap": "0",
        "centre_lines": "true",
    }
    response = _post_pdf(fields)

    assert response.status_code == 200, response.text
    pattern = convert_image(_image(), width=40, max_colours=4)
    expected = render_pdf(
        pattern, split="pages", pages_across=3, pages_down=1, overlap=0, centre_lines=True
    )
    assert response.content == expected


@pytest.mark.parametrize(
    ("name", "lowest", "highest"),
    [("pages_across", 1, 20), ("pages_down", 1, 20), ("overlap", 0, 5)],
)
def test_the_bounds_are_accepted_and_one_past_refused_naming_the_field(
    name: str, lowest: int, highest: int
) -> None:
    # A wide image, so even 20 pages across with an overlap of 5 keep a legible cell.
    wide = {"width": "200"}
    for value in (lowest, highest):
        assert _post_pdf({**wide, name: str(value)}).status_code == 200, (name, value)
    for value in (lowest - 1, highest + 1):
        response = _post_pdf({**wide, name: str(value)})
        assert response.status_code == 422, (name, value)
        assert any(error["loc"][-1] == name for error in response.json()["detail"])


def test_an_unknown_split_is_refused_naming_it() -> None:
    response = _post_pdf({"split": "rows"})

    assert response.status_code == 422
    assert any(error["loc"][-1] == "split" for error in response.json()["detail"])


def test_a_split_needing_cells_under_2_mm_is_a_422_saying_so() -> None:
    response = _post_pdf(
        {"width": "300", "split": "pages", "pages_across": "1", "pages_down": "1"},
        image=_image(300, 30),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "2.0 mm" in detail


def test_the_pattern_route_ignores_layout_fields() -> None:
    upload = _png(_image())
    fields = {"width": "40", "max_colours": "4"}
    files = {"image": ("i.png", upload, "image/png")}
    plain = client.post("/patterns", data=fields, files=files)
    files = {"image": ("i.png", upload, "image/png")}
    with_overlap = client.post("/patterns", data={**fields, "overlap": "9"}, files=files)

    assert with_overlap.status_code == 200
    assert with_overlap.json() == plain.json()


def test_the_fabric_colour_gives_the_bytes_the_core_renders() -> None:
    response = _post_pdf({"fabric_colour": "#C81E3C"})

    assert response.status_code == 200
    pattern = convert_image(_image(), width=40, max_colours=4)
    assert response.content == render_pdf(pattern, fabric_rgb=(200, 30, 60))


@pytest.mark.parametrize("value", ["red", "#c81e3", "c81e3c", "#c81e3cff", "#gggggg"])
def test_a_fabric_colour_not_written_as_hex_is_refused_naming_it(value: str) -> None:
    response = _post_pdf({"fabric_colour": value})

    assert response.status_code == 422
    assert any("fabric_colour" in error["loc"] for error in response.json()["detail"])
