"""POST /patterns: HTTP in, the core's pattern out as JSON, nothing kept between requests."""

import io
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.formparsers import MultiPartParser

from cross_stitch.api.app import MAX_COLOURS, MAX_UPLOAD_BYTES, app
from cross_stitch.export import SYMBOLS, key_symbols, render_pdf
from cross_stitch.pattern import EMPTY, convert_image
from cross_stitch.threads import dmc_thread

client = TestClient(app)

STRIPE_CODES = ["310", "Blanc", "321", "797"]


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _stripes() -> Image.Image:
    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    for i, code in enumerate(STRIPE_CODES):
        pixels[:, i * 10 : (i + 1) * 10] = dmc_thread(code).rgb
    return Image.fromarray(pixels)


def _half_transparent() -> Image.Image:
    pixels = np.zeros((10, 20, 4), dtype=np.uint8)
    pixels[:, 10:] = (*dmc_thread("310").rgb, 255)
    return Image.fromarray(pixels, mode="RGBA")


def _post(upload: bytes | None, fields: dict[str, str], filename: str = "image.png") -> Any:
    files = {"image": (filename, upload, "image/png")} if upload is not None else None
    return client.post("/patterns", data=fields, files=files)


def _stripes_response(**extra: str) -> dict[str, Any]:
    response = _post(_png(_stripes()), {"width": "40", "max_colours": "4", **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_golden_stripes_give_four_threads_of_200_stitches() -> None:
    body = _stripes_response()
    assert sorted(entry["code"] for entry in body["key"]) == sorted(STRIPE_CODES)
    assert all(entry["stitches"] == 200 for entry in body["key"])
    assert body["total_stitches"] == 800
    assert body["width"] == 40
    assert body["height"] == 20
    assert len(body["grid"]) == 20
    assert all(len(row) == 40 for row in body["grid"])


def test_golden_stripes_key_entries_carry_the_first_four_symbols_in_order() -> None:
    body = _stripes_response()
    assert [entry["symbol"] for entry in body["key"]] == list(SYMBOLS[:4])


def test_the_symbol_list_covers_the_maximum_number_of_colours() -> None:
    assert len(SYMBOLS) == MAX_COLOURS


def test_body_is_exactly_what_the_core_returns() -> None:
    body = _stripes_response(fabric_count="18")
    pattern = convert_image(_stripes(), width=40, max_colours=4, fabric_count=18)
    symbols = key_symbols(pattern.key)
    assert body["key"] == [
        {
            "code": entry.thread.code,
            "name": entry.thread.name,
            "rgb": list(entry.thread.rgb),
            "stitches": entry.stitches,
            "skeins": entry.skeins,
            "symbol": symbol,
        }
        for entry, symbol in zip(pattern.key, symbols, strict=True)
    ]
    assert body["grid"] == [
        [None if cell == EMPTY else cell for cell in row] for row in pattern.grid.tolist()
    ]
    assert body["total_stitches"] == pattern.total_stitches
    assert body["fabric_count"] == 18
    assert body["finished_size"] == {
        "width_in": pattern.width_in,
        "height_in": pattern.height_in,
        "width_cm": pattern.width_cm,
        "height_cm": pattern.height_cm,
    }


def test_fabric_count_defaults_to_14() -> None:
    body = _stripes_response()
    assert body["fabric_count"] == 14
    assert body["finished_size"]["width_in"] == pytest.approx(40 / 14)
    assert body["finished_size"]["width_cm"] == pytest.approx(40 / 14 * 2.54)


def test_the_same_request_twice_gives_identical_bodies() -> None:
    assert _stripes_response() == _stripes_response()


def test_key_counts_sum_to_the_total_and_the_grid_cells() -> None:
    body = _stripes_response()
    assert sum(entry["stitches"] for entry in body["key"]) == body["total_stitches"]
    assert body["total_stitches"] == body["width"] * body["height"]


def test_transparent_cells_are_null_and_not_counted() -> None:
    response = _post(_png(_half_transparent()), {"width": "20", "max_colours": "2"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(cell is None for row in body["grid"] for cell in row[:10])
    assert all(cell == 0 for row in body["grid"] for cell in row[10:])
    assert [entry["code"] for entry in body["key"]] == ["310"]
    assert body["total_stitches"] == 10 * 10


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"max_colours": "4"}, "width"),
        ({"width": "0", "max_colours": "4"}, "width"),
        ({"width": "1001", "max_colours": "4"}, "width"),
        ({"width": "abc", "max_colours": "4"}, "width"),
        ({"width": "40", "max_colours": "0"}, "max_colours"),
        ({"width": "40", "max_colours": "101"}, "max_colours"),
        ({"width": "40"}, "max_colours"),
        ({"width": "40", "max_colours": "4", "fabric_count": "0"}, "fabric_count"),
        ({"width": "40", "max_colours": "4", "fabric_count": "-14"}, "fabric_count"),
        ({"width": "40", "max_colours": "4", "fabric_count": "nan"}, "fabric_count"),
        ({"width": "40", "max_colours": "4", "fabric_count": "inf"}, "fabric_count"),
    ],
)
def test_invalid_settings_give_422_naming_the_field(fields: dict[str, str], field: str) -> None:
    response = _post(_png(_stripes()), fields)
    assert response.status_code == 422
    assert field in response.text


def test_limits_themselves_are_accepted() -> None:
    image = _png(Image.new("RGB", (4, 2), dmc_thread("321").rgb))
    for fields in ({"width": "1", "max_colours": "1"}, {"width": "1000", "max_colours": "100"}):
        assert _post(image, fields).status_code == 200


def test_an_image_too_tall_for_the_width_gives_422() -> None:
    tall = _png(Image.new("RGB", (1, 1001), (0, 0, 0)))
    response = _post(tall, {"width": "1", "max_colours": "1"})
    assert response.status_code == 422
    assert "height" in response.text
    assert _post(_png(Image.new("RGB", (1, 1000))), {"width": "1", "max_colours": "1"}).is_success


def test_no_image_field_gives_422() -> None:
    response = _post(None, {"width": "40", "max_colours": "4"})
    assert response.status_code == 422
    assert "image" in response.text


@pytest.mark.parametrize(
    "upload",
    [b"this is a text file, not an image\n", b"", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64],
)
def test_an_upload_that_is_not_a_decodable_image_gives_400(upload: bytes) -> None:
    response = _post(upload, {"width": "40", "max_colours": "4"}, filename="notes.txt")
    assert response.status_code == 400
    assert "image" in response.json()["detail"]


def test_an_upload_over_20_mb_gives_413() -> None:
    assert MAX_UPLOAD_BYTES == 20 * 1024 * 1024
    response = _post(b"\x00" * (MAX_UPLOAD_BYTES + 1), {"width": "40", "max_colours": "4"})
    assert response.status_code == 413


def test_a_body_far_over_the_limit_is_refused_from_its_content_length() -> None:
    response = client.post(
        "/patterns",
        content=b"x" * 16,
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": "99999999"},
    )
    assert response.status_code == 413


def test_an_upload_of_exactly_20_mb_is_not_refused_for_its_size() -> None:
    response = _post(b"\x00" * MAX_UPLOAD_BYTES, {"width": "40", "max_colours": "4"})
    assert response.status_code == 400  # not an image, but within the size limit


def test_accepted_uploads_stay_in_memory() -> None:
    # Starlette spools a larger upload to a temporary file on disk; the API is stateless.
    assert MultiPartParser.spool_max_size >= MAX_UPLOAD_BYTES


def test_both_size_refusals_give_the_same_message() -> None:
    by_length = client.post(
        "/patterns",
        content=b"x",
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": "99999999"},
    )
    by_size = _post(b"\x00" * (MAX_UPLOAD_BYTES + 1), {"width": "40", "max_colours": "4"})
    assert by_length.json() == by_size.json()


# --- POST /patterns/pdf --------------------------------------------------------------------


def _post_pdf(upload: bytes | None, fields: dict[str, str], filename: str = "image.png") -> Any:
    files = {"image": (filename, upload, "image/png")} if upload is not None else None
    return client.post("/patterns/pdf", data=fields, files=files)


def _stripes_pdf(**extra: str) -> bytes:
    response = _post_pdf(_png(_stripes()), {"width": "40", "max_colours": "4", **extra})
    assert response.status_code == 200, response.text
    body: bytes = response.content
    return body


def _core_pdf(**options: Any) -> bytes:
    pattern = convert_image(_stripes(), width=40, max_colours=4, fabric_count=14)
    return render_pdf(pattern, **options)


def test_the_pdf_is_an_attachment_of_type_pdf() -> None:
    response = _post_pdf(_png(_stripes()), {"width": "40", "max_colours": "4"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert disposition.rstrip('"').endswith(".pdf")
    assert response.content.startswith(b"%PDF")


def test_the_pdf_is_exactly_what_the_core_renders_by_default() -> None:
    assert _stripes_pdf() == _core_pdf()
    assert _stripes_pdf() == _core_pdf(variant="colour", paper="A4", orientation="portrait")


def test_the_pdf_follows_the_variant_paper_and_orientation_asked_for() -> None:
    assert _stripes_pdf(variant="bw") == _core_pdf(variant="bw")
    assert _stripes_pdf(paper="A3", orientation="landscape") == _core_pdf(
        paper="A3", orientation="landscape"
    )
    assert _stripes_pdf(variant="bw") != _stripes_pdf()


def test_the_pdf_uses_the_fabric_count_given() -> None:
    pattern = convert_image(_stripes(), width=40, max_colours=4, fabric_count=18)
    assert _stripes_pdf(fabric_count="18") == render_pdf(pattern)


def test_the_same_pdf_request_twice_gives_identical_bytes() -> None:
    assert _stripes_pdf(paper="A5") == _stripes_pdf(paper="A5")


@pytest.mark.parametrize(
    ("field", "value"),
    [("variant", "sepia"), ("paper", "A6"), ("orientation", "diagonal")],
)
def test_an_unknown_pdf_choice_gives_422_naming_the_field(field: str, value: str) -> None:
    response = _post_pdf(_png(_stripes()), {"width": "40", "max_colours": "4", field: value})
    assert response.status_code == 422
    assert field in response.text


@pytest.mark.parametrize(
    "fields",
    [
        {"max_colours": "4"},
        {"width": "0", "max_colours": "4"},
        {"width": "40", "max_colours": "101"},
        {"width": "40", "max_colours": "4", "fabric_count": "0"},
    ],
)
def test_the_pdf_refuses_the_settings_patterns_refuses_alike(fields: dict[str, str]) -> None:
    by_json = _post(_png(_stripes()), fields)
    by_pdf = _post_pdf(_png(_stripes()), fields)
    assert by_json.status_code == by_pdf.status_code == 422
    assert by_json.json() == by_pdf.json()


@pytest.mark.parametrize(
    ("upload", "status"),
    [
        (None, 422),
        (b"this is a text file, not an image\n", 400),
        (b"\x00" * (MAX_UPLOAD_BYTES + 1), 413),
        (_png(Image.new("RGB", (1, 1001), (0, 0, 0))), 422),
    ],
    ids=["no image", "not an image", "over 20 MB", "too tall"],
)
def test_the_pdf_refuses_uploads_patterns_refuses_alike(upload: bytes | None, status: int) -> None:
    fields = {"width": "1" if status == 422 and upload else "40", "max_colours": "4"}
    by_json = _post(upload, fields)
    by_pdf = _post_pdf(upload, fields)
    assert by_json.status_code == by_pdf.status_code == status
    assert by_json.json() == by_pdf.json()


def test_the_json_route_is_unchanged_by_the_pdf_fields() -> None:
    assert _stripes_response(variant="bw", paper="A3") == _stripes_response()
