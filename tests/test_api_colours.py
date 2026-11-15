"""`max_colours` on the pattern routes: the thread count of the pattern returned, after
cleanup."""

import io
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cross_stitch.api.app import app
from cross_stitch.pattern import EMPTY, clean_pattern, colours_with_headroom, convert_image

client = TestClient(app)


def _busy() -> Image.Image:
    """A seeded 60 x 40 image of random colours: hundreds of distinct colours, many
    isolated cells."""
    pixels = np.random.default_rng(7).integers(0, 256, size=(40, 60, 3), dtype=np.uint8)
    return Image.fromarray(pixels)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _post(**fields: str) -> dict[str, Any]:
    response = client.post(
        "/patterns",
        data={"width": "60", **fields},
        files={"image": ("busy.png", _png(_busy()), "image/png")},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_without_cleanup_the_pattern_has_the_colours_asked_for() -> None:
    body = _post(max_colours="8")
    assert len(body["key"]) == 8
    assert body["converted"] is None


@pytest.mark.parametrize("cleanup", [{"confetti_size": "2"}, {"min_stitches": "40"}])
def test_with_cleanup_the_colours_asked_for_are_counted_after_it(cleanup: dict[str, str]) -> None:
    body = _post(max_colours="8", **cleanup)

    assert len(body["key"]) == 8
    # The pattern before cleanup was converted with room for the threads cleanup removes.
    assert len(body["converted"]["key"]) == colours_with_headroom(8)
    assert sum(entry["stitches"] for entry in body["key"]) == body["total_stitches"]


def test_the_route_returns_what_the_core_steps_give() -> None:
    body = _post(max_colours="8", confetti_size="2")
    converted = convert_image(_busy(), width=60, max_colours=colours_with_headroom(8))
    cleaned = clean_pattern(
        converted, merge_distance=0.0, min_stitches=0, confetti_size=2, max_colours=8
    ).pattern

    assert [entry["code"] for entry in body["key"]] == [e.thread.code for e in cleaned.key]
    assert body["grid"] == [
        [None if cell == EMPTY else cell for cell in row] for row in cleaned.grid.tolist()
    ]
