"""`GET /threads` and `GET /threads/{code}/nearest`: the DMC table and nearest threads."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cross_stitch.api.app import app
from cross_stitch.threads import dmc_thread, dmc_threads, similar_dmc

client = TestClient(app)


def _get(url: str) -> Any:
    return client.get(url)


def test_threads_lists_the_whole_dmc_table_in_order() -> None:
    response = _get("/threads")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 489
    assert body == [{"code": t.code, "name": t.name, "rgb": list(t.rgb)} for t in dmc_threads()]


def test_nearest_gives_ten_threads_as_the_core_ranks_them() -> None:
    response = _get("/threads/310/nearest")

    assert response.status_code == 200
    assert response.json() == [
        {"code": t.code, "name": t.name, "rgb": list(t.rgb), "distance": d}
        for t, d in similar_dmc(dmc_thread("310"), 10)
    ]


@pytest.mark.parametrize("count", [3, 100])
def test_nearest_gives_the_count_asked_for(count: int) -> None:
    response = _get(f"/threads/310/nearest?count={count}")

    assert response.status_code == 200
    assert len(response.json()) == count


@pytest.mark.parametrize("count", ["0", "101", "x"])
def test_a_count_out_of_range_is_a_422_naming_count(count: str) -> None:
    response = _get(f"/threads/310/nearest?count={count}")

    assert response.status_code == 422
    assert any(error["loc"][-1] == "count" for error in response.json()["detail"])


def test_the_code_is_case_insensitive_and_excluded_from_its_nearest() -> None:
    response = _get("/threads/blanc/nearest")

    assert response.status_code == 200
    assert "Blanc" not in [entry["code"] for entry in response.json()]


def test_an_unknown_code_is_a_404_naming_it() -> None:
    response = _get("/threads/XYZ/nearest")

    assert response.status_code == 404
    assert "XYZ" in response.json()["detail"]


def test_both_routes_are_described_in_the_docs() -> None:
    paths = app.openapi()["paths"]

    assert paths["/threads"]["get"]["description"]
    assert paths["/threads/{code}/nearest"]["get"]["description"]
