"""The `changes` field of both pattern routes: replacements and hand edits, one ordered JSON
list applied after cleanup, and `changed_cells`, one count per entry.

Every expected pattern is the core's: `clean_pattern` of the conversion, then
`edit_pattern` with the same entries written as core objects, rendered with the same
`key_json` / `grid_json` shapes the response uses.
"""

import json
from collections.abc import Sequence
from typing import Any

import pytest
from api_helpers import (
    CLEANUP_FORM,
    cleanable,
    core_converted,
    field_image,
    grid_json,
    key_json,
    png,
    stripes,
)
from fastapi.testclient import TestClient
from PIL import Image

from cross_stitch.api.app import MAX_UPLOAD_BYTES, app
from cross_stitch.export import render_pdf
from cross_stitch.pattern import (
    Change,
    Edited,
    Fill,
    Rect,
    Replace,
    Stroke,
    clean_pattern,
    edit_pattern,
    isolated_stitches,
)
from cross_stitch.threads import Thread, dmc_thread

client = TestClient(app)

type Entry = dict[str, Any]

ROUTES = ["/patterns", "/patterns/pdf"]
# The stripes pattern is 40 x 20: 310 in columns 0-9, Blanc 10-19, 321 20-29, 797 30-39.
STRIPES = (40, 20)
CHANGES_LIMITS: dict[str, Any] = {
    "max_entries": 1000,
    "max_bytes": 524288,
    "brush": {"min": 1, "max": 9, "step": 2, "default": 1},
    "max_coordinate": 2000,
}


# ------------------------------------------------------------------------------ images


# ------------------------------------------------------------------------- the request


def _entries_field(changes: Sequence[object] | str) -> str:
    return changes if isinstance(changes, str) else json.dumps(list(changes))


def _post(
    route: str,
    changes: Sequence[object] | str | None,
    image: Image.Image | None = None,
    max_colours: int = 4,
    **extra: str,
) -> Any:
    """`route` with `changes` (a list sent as JSON, or the field's text as it is; `None`
    sends no field) on `image` (the stripes by default) at its own width."""
    image = stripes() if image is None else image
    fields = {"width": str(image.width), "max_colours": str(max_colours), **extra}
    if changes is not None:
        fields["changes"] = _entries_field(changes)
    files = {"image": ("image.png", png(image), "image/png")}
    return client.post(route, data=fields, files=files)


def _body(
    changes: Sequence[object] | str | None,
    image: Image.Image | None = None,
    max_colours: int = 4,
    **extra: str,
) -> dict[str, Any]:
    response = _post("/patterns", changes, image, max_colours, **extra)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _pdf(changes: Sequence[object] | str | None, **extra: str) -> bytes:
    response = _post("/patterns/pdf", changes, None, 4, **extra)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    content: bytes = response.content
    return content


def _replace(source: str, target: str | None) -> Entry:
    return {"op": "replace", "from": source, "to": target}


def _stroke(
    thread: str | None, points: list[list[int]], brush: int = 1, grid: Sequence[int] = STRIPES
) -> Entry:
    return {"op": "stroke", "thread": thread, "brush": brush, "grid": list(grid), "points": points}


def _rect(
    thread: str | None, start: list[int], end: list[int], grid: Sequence[int] = STRIPES
) -> Entry:
    return {"op": "rect", "thread": thread, "grid": list(grid), "from": start, "to": end}


def _fill(thread: str | None, at: list[int], grid: Sequence[int] = STRIPES) -> Entry:
    return {"op": "fill", "thread": thread, "grid": list(grid), "at": at}


# ------------------------------------------------------------------------------ the core


def _dmc(code: str | None) -> Thread | None:
    return None if code is None else dmc_thread(code)


def _core_replace(source: str, target: str | None) -> Replace:
    return Replace(old=dmc_thread(source), new=_dmc(target))


def _core(changes: Sequence[Change]) -> Edited:
    """The core's stripes pattern, no cleanup, with `changes` applied."""
    cleaned = clean_pattern(
        core_converted(stripes(), 4), merge_distance=0.0, min_stitches=0, confetti_size=0
    )
    return edit_pattern(cleaned.pattern, changes)


def _assert_body_is(body: dict[str, Any], expected: Edited) -> None:
    assert body["grid"] == grid_json(expected.pattern)
    assert body["key"] == key_json(expected.pattern)
    assert body["total_stitches"] == expected.pattern.total_stitches
    assert body["changed_cells"] == list(expected.changed)


def _counts(body: dict[str, Any]) -> list[tuple[str, int]]:
    return [(entry["code"], entry["stitches"]) for entry in body["key"]]


def _code_at(body: dict[str, Any], column: int, row: int) -> str | None:
    index = body["grid"][row][column]
    return None if index is None else str(body["key"][index]["code"])


# ------------------------------------------------------------------------- replacements


def test_a_replace_entry_swaps_the_thread_and_gives_the_core_pattern() -> None:
    expected = _core([_core_replace("310", "3865")])
    body = _body([_replace("310", "3865")])

    assert ("3865", 200) in _counts(body)
    assert "310" not in [entry["code"] for entry in body["key"]]
    assert body["changed_cells"] == [200]
    assert body["total_stitches"] == 800
    _assert_body_is(body, expected)


def test_a_replace_onto_a_thread_in_the_key_merges_and_comes_first() -> None:
    body = _body([_replace("310", "Blanc")])
    assert len(body["key"]) == 3
    assert _counts(body)[0] == ("Blanc", 400)
    assert body["total_stitches"] == 800
    assert sum(entry["stitches"] for entry in body["key"]) == 800
    _assert_body_is(body, _core([_core_replace("310", "Blanc")]))


def test_replace_entries_apply_in_the_order_sent() -> None:
    body = _body([_replace("310", "321"), _replace("321", "797")])
    assert _counts(body)[0] == ("797", 600)
    assert sorted(code for code, _ in _counts(body)) == ["797", "Blanc"]
    assert body["changed_cells"] == [200, 400]
    _assert_body_is(body, _core([_core_replace("310", "321"), _core_replace("321", "797")]))

    reverse = _body([_replace("321", "797"), _replace("310", "321")])
    assert reverse["changed_cells"] == [200, 200]
    _assert_body_is(reverse, _core([_core_replace("321", "797"), _core_replace("310", "321")]))
    assert reverse["key"] != body["key"]


def test_a_replace_to_null_leaves_the_thread_s_cells_bare() -> None:
    body = _body([_replace("310", None)])
    _assert_body_is(body, _core([_core_replace("310", None)]))
    assert body["total_stitches"] == 600
    assert sum(row.count(None) for row in body["grid"]) == 200
    assert body["changed_cells"] == [200]


def test_a_replace_of_a_thread_not_in_the_pattern_counts_zero_and_changes_nothing() -> None:
    plain = _body(None)
    body = _body([_replace("3865", "310")])
    assert body["changed_cells"] == [0]
    assert {**body, "changed_cells": []} == plain


def test_only_the_entries_that_did_nothing_count_zero() -> None:
    body = _body([_replace("3865", "310"), _replace("310", "321"), _replace("310", "797")])
    assert body["changed_cells"] == [0, 200, 0]
    assert _counts(body)[0] == ("321", 400)


def test_replace_codes_are_case_insensitive_and_keep_their_stored_spelling() -> None:
    body = _body([_replace("blanc", "b5200")])
    codes = [entry["code"] for entry in body["key"]]
    assert "B5200" in codes
    assert "Blanc" not in codes
    assert body["changed_cells"] == [200]
    _assert_body_is(body, _core([_core_replace("Blanc", "B5200")]))


# --------------------------------------------------------------------------- hand edits


def test_hand_edit_codes_are_case_insensitive_and_keep_their_stored_spelling() -> None:
    body = _body([_stroke("blanc", [[0, 0]]), _fill("b5200", [35, 10])])
    assert _code_at(body, 0, 0) == "Blanc"
    assert _code_at(body, 35, 10) == "B5200"
    assert "797" not in [entry["code"] for entry in body["key"]]
    assert body["changed_cells"] == [1, 200]


def test_a_stroke_then_a_replace_of_its_thread_moves_the_painted_cell_too() -> None:
    body = _body([_stroke("310", [[12, 5]]), _replace("310", "300")])

    assert _code_at(body, 12, 5) == "300"
    assert ("300", 201) in _counts(body)
    assert body["changed_cells"] == [1, 201]
    expected = _core(
        [
            Stroke(thread=dmc_thread("310"), brush=1, grid=STRIPES, points=((12, 5),)),
            _core_replace("310", "300"),
        ]
    )
    _assert_body_is(body, expected)


def test_every_kind_of_hand_edit_gives_the_core_pattern() -> None:
    changes = [
        _stroke("3865", [[0, 0], [39, 19], [39, 0]], brush=3),
        _rect(None, [14, 6], [5, 2]),
        _fill("300", [25, 10]),
        _stroke(None, [[22, 15]], brush=5),
    ]
    expected = _core(
        [
            Stroke(dmc_thread("3865"), brush=3, grid=STRIPES, points=((0, 0), (39, 19), (39, 0))),
            Rect(thread=None, grid=STRIPES, start=(14, 6), end=(5, 2)),
            Fill(thread=dmc_thread("300"), grid=STRIPES, at=(25, 10)),
            Stroke(thread=None, brush=5, grid=STRIPES, points=((22, 15),)),
        ]
    )
    assert all(count > 0 for count in expected.changed)

    body = _body(changes)

    _assert_body_is(body, expected)
    assert sum(entry["stitches"] for entry in body["key"]) == body["total_stitches"]


def test_coordinates_off_the_grid_are_accepted_and_clipped() -> None:
    changes = [_stroke("3865", [[-3, -3], [45, 25]], brush=3), _rect("300", [-9, 18], [3, 99])]
    expected = _core(
        [
            Stroke(dmc_thread("3865"), brush=3, grid=STRIPES, points=((-3, -3), (45, 25))),
            Rect(thread=dmc_thread("300"), grid=STRIPES, start=(-9, 18), end=(3, 99)),
        ]
    )
    _assert_body_is(_body(changes), expected)


@pytest.mark.parametrize("coordinate", [-1, 1])
def test_the_reported_coordinate_bound_is_accepted_and_one_more_refused(coordinate: int) -> None:
    bound = coordinate * CHANGES_LIMITS["max_coordinate"]
    accepted = [_stroke("3865", [[0, 0], [bound, bound]]), _rect("300", [bound, 0], [0, bound])]
    assert _post("/patterns", accepted).status_code == 200
    beyond = bound + coordinate
    for refused in (
        _stroke("3865", [[0, 0], [beyond, 0]]),
        _rect("300", [0, beyond], [0, 0]),
        _fill("300", [beyond, 0]),
    ):
        response = _post("/patterns", [refused])
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][:3] == ["body", "changes", 0]


@pytest.mark.parametrize("grid", [[20, 40], [40, 21], [41, 20], [39, 20]])
@pytest.mark.parametrize("kind", ["stroke", "rect", "fill"])
def test_a_hand_edit_drawn_on_another_size_counts_zero_and_changes_nothing(
    kind: str, grid: list[int]
) -> None:
    entry = {
        "stroke": _stroke("3865", [[0, 0], [5, 5]], brush=3, grid=grid),
        "rect": _rect("3865", [0, 0], [5, 5], grid=grid),
        "fill": _fill("3865", [0, 0], grid=grid),
    }[kind]
    plain = _body(None)

    body = _body([entry])

    assert body["changed_cells"] == [0]
    assert {**body, "changed_cells": []} == plain


def test_an_explicit_empty_list_is_the_same_as_no_field() -> None:
    body = _body("[]")
    assert body["changed_cells"] == []
    assert body == _body(None)


def test_the_same_request_twice_gives_identical_bodies() -> None:
    changes = [_replace("310", "321"), _stroke("797", [[3, 3], [30, 3]], brush=3)]
    assert _body(changes) == _body(changes)


# ---------------------------------------------------------------------------- cleanup on


def test_changes_leave_converted_as_the_raw_conversion_and_count_isolation_after() -> None:
    image = field_image((7, 9), {(1, 1): "321", (5, 7): "321"})
    converted = core_converted(image, 2)
    cleaned = clean_pattern(converted, merge_distance=0.1, min_stitches=0, confetti_size=0)
    final = edit_pattern(cleaned.pattern, [_core_replace("797", "321")])
    # The replacement reconnects the two lone stitches, so the count after differs.
    assert (cleaned.isolated_before, cleaned.isolated_after) == (2, 2)
    assert isolated_stitches(final.pattern) == 0

    body = _body([_replace("797", "321")], image, 2, merge_distance="0.1")

    assert body["converted"] == {
        "grid": grid_json(converted),
        "key": key_json(converted),
        "total_stitches": converted.total_stitches,
    }
    assert body["isolated_stitches"] == {"before": 2, "after": 0}
    _assert_body_is(body, final)


def test_a_hand_edit_after_confetti_cleanup_counts_its_own_isolated_stitch() -> None:
    image = field_image((7, 9), {(3, 4): "321"})
    converted = core_converted(image, 2)
    cleaned = clean_pattern(converted, merge_distance=0.0, min_stitches=0, confetti_size=1)
    stroke = Stroke(thread=dmc_thread("321"), brush=1, grid=(9, 7), points=((0, 0),))
    final = edit_pattern(cleaned.pattern, [stroke])
    # Cleanup removes the lone red stitch; the edit puts one back in a corner.
    assert (cleaned.isolated_before, cleaned.isolated_after) == (1, 0)
    assert isolated_stitches(final.pattern) == 1

    body = _body([_stroke("321", [[0, 0]], grid=[9, 7])], image, 2, confetti_size="1")

    _assert_body_is(body, final)
    assert body["isolated_stitches"] == {"before": 1, "after": 1}
    assert body["converted"]["grid"] == grid_json(converted)
    converted_codes = [entry["code"] for entry in body["converted"]["key"]]
    assert converted_codes[body["converted"]["grid"][3][4]] == "321"
    assert converted_codes[body["converted"]["grid"][0][0]] == "797"


def test_changes_apply_after_every_cleanup_step() -> None:
    image = cleanable()
    converted = core_converted(image, 5)
    cleaned = clean_pattern(converted, merge_distance=3.0, min_stitches=5, confetti_size=1)
    assert cleaned.pattern.key[0].thread.code == "797"
    final = edit_pattern(cleaned.pattern, [_core_replace("797", "3865")])

    body = _body([_replace("797", "3865")], image, 5, **CLEANUP_FORM)

    _assert_body_is(body, final)
    assert body["isolated_stitches"] == {
        "before": cleaned.isolated_before,
        "after": isolated_stitches(final.pattern),
    }
    assert "3865" not in [entry["code"] for entry in body["converted"]["key"]]
    assert body["converted"]["grid"] == grid_json(converted)


# ----------------------------------------------------------------------------------- PDF


def test_the_pdf_is_what_the_core_renders_of_the_replaced_pattern() -> None:
    expected = render_pdf(_core([_core_replace("310", "3865")]).pattern)
    content = _pdf([_replace("310", "3865")])
    assert content == expected
    assert content != _pdf(None)


def test_the_pdf_is_what_the_core_renders_of_the_hand_edited_pattern() -> None:
    changes = [_stroke("3865", [[2, 2], [8, 2]], brush=3), _rect(None, [12, 0], [15, 19])]
    expected = _core(
        [
            Stroke(dmc_thread("3865"), brush=3, grid=STRIPES, points=((2, 2), (8, 2))),
            Rect(thread=None, grid=STRIPES, start=(12, 0), end=(15, 19)),
        ]
    )

    content = _pdf(changes, variant="bw")

    assert content == render_pdf(expected.pattern, variant="bw")
    assert content != _pdf(None, variant="bw")


@pytest.mark.parametrize("changes", [None, "[]"], ids=["no field", "empty list"])
def test_the_pdf_without_changes_is_unchanged(changes: str | None) -> None:
    assert _pdf(changes) == render_pdf(core_converted(stripes(), 4))


# -------------------------------------------------------------------------------- errors

OK_REPLACE = _replace("310", "3865")
OK_STROKE = _stroke("310", [[0, 0]])
OK_RECT = _rect("310", [0, 0], [1, 1])
OK_FILL = _fill("310", [0, 0])


def _without(entry: Entry, field: str) -> Entry:
    return {name: value for name, value in entry.items() if name != field}


# Each is refused as one entry: `ENTRY_ERRORS[name]` is sent third, after two good ones.
ENTRY_ERRORS: dict[str, object] = {
    "a number": 5,
    "a string": "310:3865",
    "a list": ["replace", "310", "3865"],
    "null": None,
    "no op": _without(OK_REPLACE, "op"),
    "unknown op": {**OK_REPLACE, "op": "circle"},
    "op not a string": {**OK_REPLACE, "op": 1},
    "unknown from": _replace("XYZ", "310"),
    "unknown to": _replace("310", "XYZ"),
    "fabric is no code": _replace("310", "fabric"),
    "code as a number": {**OK_REPLACE, "from": 310},
    "unknown stroke thread": {**OK_STROKE, "thread": "XYZ"},
    "unknown rect thread": {**OK_RECT, "thread": "XYZ"},
    "unknown fill thread": {**OK_FILL, "thread": "XYZ"},
    "replace without from": _without(OK_REPLACE, "from"),
    "replace without to": _without(OK_REPLACE, "to"),
    "stroke without thread": _without(OK_STROKE, "thread"),
    "stroke without brush": _without(OK_STROKE, "brush"),
    "stroke without grid": _without(OK_STROKE, "grid"),
    "stroke without points": _without(OK_STROKE, "points"),
    "rect without from": _without(OK_RECT, "from"),
    "rect without to": _without(OK_RECT, "to"),
    "rect without grid": _without(OK_RECT, "grid"),
    "fill without thread": _without(OK_FILL, "thread"),
    "fill without at": _without(OK_FILL, "at"),
    "replace with a thread": {**OK_REPLACE, "thread": "310"},
    "stroke with a colour": {**OK_STROKE, "colour": "red"},
    "rect with points": {**OK_RECT, "points": [[0, 0]]},
    "fill with a brush": {**OK_FILL, "brush": 1},
    "point x 1.5": {**OK_STROKE, "points": [[0, 0], [1.5, 0]]},
    "point y as a string": {**OK_STROKE, "points": [[0, "1"]]},
    "point of one number": _stroke("310", [[1]]),
    "point of three numbers": _stroke("310", [[1, 2, 3]]),
    "point as an object": {**OK_STROKE, "points": [{"x": 1, "y": 2}]},
    "points not a list": {**OK_STROKE, "points": "0,0"},
    "empty points": _stroke("310", []),
    "rect from 1.5": {**OK_RECT, "from": [0, 1.5]},
    "rect to as strings": {**OK_RECT, "to": ["1", "1"]},
    "fill at 1.5": {**OK_FILL, "at": [1.5, 1]},
    "fill at as strings": {**OK_FILL, "at": ["0", "0"]},
    "grid width 40.5": {**OK_FILL, "grid": [40.5, 20]},
    "grid height as a string": {**OK_RECT, "grid": [40, "20"]},
    "grid of one number": {**OK_STROKE, "grid": [40]},
    "grid of three numbers": {**OK_STROKE, "grid": [40, 20, 1]},
    "brush 2": _stroke("310", [[0, 0]], brush=2),
    "brush 4": _stroke("310", [[0, 0]], brush=4),
    "brush 0": _stroke("310", [[0, 0]], brush=0),
    "brush -1": _stroke("310", [[0, 0]], brush=-1),
    "brush 11": _stroke("310", [[0, 0]], brush=11),
    "brush 1.5": {**OK_STROKE, "brush": 1.5},
    "brush as a string": {**OK_STROKE, "brush": "3"},
}


def _changes_errors(changes: Sequence[object] | str) -> list[dict[str, Any]]:
    """The 422 errors both routes give for `changes`, after checking they give the same."""
    by_json = _post("/patterns", changes)
    by_pdf = _post("/patterns/pdf", changes)
    assert by_json.status_code == by_pdf.status_code == 422, (by_json.text, by_pdf.text)
    assert by_json.json() == by_pdf.json()
    errors: list[dict[str, Any]] = by_json.json()["detail"]
    assert errors
    assert all(error["loc"][:2] == ["body", "changes"] for error in errors), errors
    return errors


@pytest.mark.parametrize("bad", list(ENTRY_ERRORS.values()), ids=list(ENTRY_ERRORS))
def test_a_refused_entry_is_a_422_naming_changes_and_its_position(bad: object) -> None:
    errors = _changes_errors([OK_REPLACE, OK_STROKE, bad])
    assert errors[0]["loc"][2] == 2, errors


@pytest.mark.parametrize("position", [0, 1, 3])
def test_the_position_named_is_the_refused_entry_s(position: int) -> None:
    changes: list[object] = [OK_REPLACE, OK_STROKE, OK_RECT, OK_FILL]
    changes.insert(position, _stroke("310", [[0, 0]], brush=2))
    errors = _changes_errors(changes)
    assert errors[0]["loc"][2] == position, errors


def test_with_two_refused_entries_the_first_error_names_the_first() -> None:
    changes: list[object] = [OK_REPLACE, _replace("XYZ", "310"), OK_FILL, _stroke("310", [])]
    errors = _changes_errors(changes)
    assert errors[0]["loc"][2] == 1, errors
    assert {error["loc"][2] for error in errors} <= {1, 3}


def _padded(entries: Sequence[object], size: int) -> str:
    """`entries` as JSON of exactly `size` UTF-8 bytes, spaces inside the brackets."""
    text = json.dumps(list(entries))
    padding = size - len(text.encode())
    assert padding >= 0
    return "[" + " " * padding + text[1:]


WHOLE_FIELD_ERRORS: dict[str, str] = {
    "unclosed": "[{",
    "no JSON": "op: replace",
    "two lists": "[] []",
    "an object": json.dumps(OK_REPLACE),
    "a string": json.dumps("310:3865"),
    "a number": "42",
    "one entry too many": json.dumps(
        [_replace("310", "310")] * (CHANGES_LIMITS["max_entries"] + 1)
    ),
    "one byte too many": _padded([OK_REPLACE], CHANGES_LIMITS["max_bytes"] + 1),
    # Two bytes a character: under the limit in characters, over it in bytes.
    "UTF-8 bytes, not characters": json.dumps([_replace("310", "é" * 300_000)], ensure_ascii=False),
}


@pytest.mark.parametrize("field", list(WHOLE_FIELD_ERRORS.values()), ids=list(WHOLE_FIELD_ERRORS))
def test_a_refused_field_is_a_422_naming_changes_alone(field: str) -> None:
    errors = _changes_errors(field)
    assert all(error["loc"] == ["body", "changes"] for error in errors), errors


def test_the_utf8_case_is_under_the_limit_in_characters_and_over_it_in_bytes() -> None:
    field = WHOLE_FIELD_ERRORS["UTF-8 bytes, not characters"]
    assert len(field) <= CHANGES_LIMITS["max_bytes"] < len(field.encode())


# -------------------------------------------------------------------------------- limits


def _changes_limits() -> dict[str, Any]:
    response = client.get("/limits")
    assert response.status_code == 200, response.text
    limits: dict[str, Any] = response.json()["changes"]
    return limits


def test_the_limits_report_the_changes_contract() -> None:
    assert _changes_limits() == CHANGES_LIMITS


def test_the_reported_brush_default_is_within_its_bounds_and_odd() -> None:
    brush = _changes_limits()["brush"]
    assert brush["min"] <= brush["default"] <= brush["max"]
    assert brush["default"] % 2 == 1


def test_every_brush_the_limits_allow_is_accepted() -> None:
    brush = _changes_limits()["brush"]
    for size in range(brush["min"], brush["max"] + 1, brush["step"]):
        body = _body([_stroke("3865", [[20, 10]], brush=size)])
        assert body["changed_cells"] == [size * size], size


@pytest.mark.parametrize(("bound", "direction"), [("min", -1), ("max", 1)])
def test_one_step_beyond_a_reported_brush_bound_is_refused(bound: str, direction: int) -> None:
    brush = _changes_limits()["brush"]
    size = brush[bound] + direction * brush["step"]
    errors = _changes_errors([_stroke("3865", [[20, 10]], brush=size)])
    assert errors[0]["loc"][2] == 0, errors


def test_the_reported_number_of_entries_is_accepted_and_one_more_refused() -> None:
    limit = _changes_limits()["max_entries"]
    entries = [_replace("310", "310")] * limit

    assert _body(entries)["changed_cells"] == [0] * limit
    errors = _changes_errors([*entries, _replace("310", "310")])
    assert all(error["loc"] == ["body", "changes"] for error in errors), errors


@pytest.mark.parametrize("route", ROUTES)
def test_a_field_of_exactly_the_reported_bytes_is_accepted(route: str) -> None:
    size = _changes_limits()["max_bytes"]
    field = _padded([OK_REPLACE], size)
    assert len(field.encode()) == size

    response = _post(route, field)

    assert response.status_code == 200, response.text
    if route == "/patterns":
        assert response.json()["changed_cells"] == [200]


def test_one_byte_over_the_reported_bytes_is_a_422_not_a_413_or_a_400() -> None:
    size = _changes_limits()["max_bytes"]
    errors = _changes_errors(_padded([OK_REPLACE], size + 1))
    assert all(error["loc"] == ["body", "changes"] for error in errors), errors


def test_the_largest_upload_with_the_largest_changes_is_not_refused_for_its_size() -> None:
    size = _changes_limits()["max_bytes"]
    fields = {"width": "40", "max_colours": "4", "changes": _padded([OK_REPLACE], size)}
    upload = b"\x00" * MAX_UPLOAD_BYTES
    for route in ROUTES:
        response = client.post(
            route, data=fields, files={"image": ("image.png", upload, "image/png")}
        )
        # Not an image, but within every size limit.
        assert response.status_code == 400, (route, response.status_code)
        assert "image" in response.json()["detail"]


# ---------------------------------------------------------------------------------- docs


def _schema_properties(name: str) -> list[dict[str, Any]]:
    schemas = app.openapi()["components"]["schemas"]
    return [
        schema["properties"][name]
        for schema in schemas.values()
        if name in schema.get("properties", {})
    ]


def test_changes_and_changed_cells_are_described_in_the_docs() -> None:
    for name in ("changes", "changed_cells"):
        properties = _schema_properties(name)
        assert properties, name
        assert all(prop.get("description") for prop in properties), name


def test_the_repeated_replace_field_is_gone_from_the_docs() -> None:
    assert not _schema_properties("replace")
    assert not _schema_properties("ignored_replacements")
