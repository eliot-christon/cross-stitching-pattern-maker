"""`POST /chart/layout`: how the PDF would cut a pattern, and every pages split."""

from typing import Any

from fastapi.testclient import TestClient

from cross_stitch.api.app import app
from cross_stitch.export import chart_layout, page_options

client = TestClient(app)


def _layout(**fields: str) -> Any:
    response = client.post("/chart/layout", data={"width": "100", "height": "100", **fields})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_pages_split_gives_its_bands_cell_and_section_names() -> None:
    body = _layout(split="pages", pages_across="2", pages_down="2")
    expected = chart_layout(100, 100, split="pages", pages_across=2, pages_down=2)

    assert body["message"] is None
    assert body["layout"]["cell_mm"] == expected.cell_mm
    assert body["layout"]["columns"] == [
        {"start": band.start, "end": band.end, "repeated": band.repeated}
        for band in expected.columns
    ]
    assert body["layout"]["sections"] == [["A1", "B1"], ["A2", "B2"]]


def test_the_defaults_are_the_pdf_route_s_cells_split() -> None:
    body = _layout()
    expected = chart_layout(100, 100)

    assert body["layout"]["cell_mm"] == 3.0
    assert len(body["layout"]["columns"]) == len(expected.columns)
    assert len(body["layout"]["sections"]) == len(expected.rows)


def test_a_refused_split_gives_no_layout_and_the_pdf_route_s_message() -> None:
    response = client.post(
        "/chart/layout",
        data={"width": "1000", "height": "1000", "split": "pages", "pages_across": "1"},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["layout"] is None
    assert "2.0 mm" in body["message"]


def test_every_pages_split_is_listed_by_down_then_across() -> None:
    body = _layout(orientation="landscape", overlap="1")
    options = page_options(100, 100, orientation="landscape", overlap=1)

    assert len(body["pages"]) == 20
    assert all(len(row) == 20 for row in body["pages"])
    assert body["pages"][1][2] == {
        "cell_mm": options[1][2].cell_mm,
        "columns": options[1][2].columns,
        "rows": options[1][2].rows,
    }


def test_a_size_out_of_range_is_a_422_naming_it() -> None:
    response = client.post("/chart/layout", data={"width": "0", "height": "100"})
    assert response.status_code == 422
    assert any("width" in error["loc"] for error in response.json()["detail"])
