"""`read_as=stitched` and what the inspection says of stitched renders and charts."""

from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from stitch_helpers import ART_COLUMNS, ART_ROWS, art, chart, gradient, png, stitched, weave

from cross_stitch.api.app import SYMBOLS_REFUSAL, WEAVE_REFUSAL, app

client = TestClient(app)

CELLS = art()


def _inspect(upload: bytes) -> Any:
    return client.post("/images/inspect", files={"image": ("a.png", upload, "image/png")}).json()


def _pattern(upload: bytes, **fields: str) -> Any:
    data = {"width": "30", "max_colours": "4", **fields}
    return client.post("/patterns", data=data, files={"image": ("a.png", upload, "image/png")})


def test_a_render_is_inspected_as_stitched() -> None:
    body = _inspect(png(stitched(CELLS, 16)))

    assert body["kind"] == "stitched"
    assert body["grid"] == {"width": ART_COLUMNS, "height": ART_ROWS, "colours": 4}
    assert body["warnings"] == []
    assert body["refusal"] is None
    assert body["description"].startswith("Stitched, 20 x 15 stitches")


def test_unequal_pitches_give_one_warning() -> None:
    body = _inspect(png(stitched(CELLS, 16.3, 17.0)))

    assert body["kind"] == "stitched"
    assert len(body["warnings"]) == 1
    assert "not square" in body["warnings"][0]


def test_read_as_stitched_gives_one_stitch_per_stitch() -> None:
    response = _pattern(png(stitched(CELLS, 16)), read_as="stitched")

    assert response.status_code == 200
    body = response.json()
    assert (body["width"], body["height"]) == (ART_COLUMNS, ART_ROWS)
    assert len(body["key"]) == 4


def test_read_as_stitched_with_no_grid_is_a_422_naming_it() -> None:
    response = _pattern(png(gradient()), read_as="stitched")

    assert response.status_code == 422
    assert "read_as" in response.json()["detail"]


def test_a_chart_of_symbols_only_and_a_weave_are_refused_in_different_words() -> None:
    symbols = _inspect(png(chart(CELLS, 14, palette=np.full((4, 3), 255.0))))
    woven = _inspect(png(weave()))

    assert (symbols["kind"], symbols["refusal"]) == ("picture", SYMBOLS_REFUSAL)
    assert (woven["kind"], woven["refusal"]) == ("picture", WEAVE_REFUSAL)
    assert SYMBOLS_REFUSAL != WEAVE_REFUSAL
