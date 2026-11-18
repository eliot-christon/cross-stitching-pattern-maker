"""The `changes` form field of the pattern routes: an ordered JSON list of thread
replacements and hand edits, read into the core's `Change`s.

Every error is a 422 whose `loc` starts with `("body", "changes")`; an error in one entry
carries that entry's 0-based position next, so a client can point at it.
"""

from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi.exceptions import RequestValidationError
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from cross_stitch.api.grid import MAX_HEIGHT, MAX_WIDTH
from cross_stitch.pattern import Change, Fill, Rect, Replace, Stroke
from cross_stitch.threads import Thread, dmc_thread

__all__ = [
    "BRUSH_DEFAULT",
    "BRUSH_MAX",
    "BRUSH_MIN",
    "BRUSH_STEP",
    "MAX_BYTES",
    "MAX_COORDINATE",
    "MAX_ENTRIES",
    "read_changes",
]

MAX_ENTRIES = 1000
"""Most entries in one `changes` list."""
MAX_BYTES = 512 * 1024
"""Most UTF-8 bytes of the `changes` field: under Starlette's 1 MiB limit on one part."""
BRUSH_MIN, BRUSH_MAX, BRUSH_STEP, BRUSH_DEFAULT = 1, 9, 2, 1
"""The brush sizes a stroke takes: odd, 1 to 9 cells across."""
MAX_COORDINATE = 2 * max(MAX_WIDTH, MAX_HEIGHT)
"""Largest coordinate of a point, either sign: twice the largest grid, so a pointer that
leaves the grid while drawing stays in range and no line can be made arbitrarily long."""


def _odd(brush: int) -> int:
    if brush % 2 == 0:
        raise ValueError("the brush must be odd")
    return brush


_Coordinate = Annotated[StrictInt, Field(ge=-MAX_COORDINATE, le=MAX_COORDINATE)]
_Point = tuple[_Coordinate, _Coordinate]
_Size = tuple[StrictInt, StrictInt]
_Brush = Annotated[StrictInt, Field(ge=BRUSH_MIN, le=BRUSH_MAX), AfterValidator(_odd)]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ReplaceIn(_Entry):
    op: Literal["replace"]
    source: str = Field(alias="from")
    to: str | None


class _StrokeIn(_Entry):
    op: Literal["stroke"]
    thread: str | None
    brush: _Brush
    grid: _Size
    points: list[_Point] = Field(min_length=1)


class _RectIn(_Entry):
    op: Literal["rect"]
    thread: str | None
    grid: _Size
    source: _Point = Field(alias="from")
    to: _Point


class _FillIn(_Entry):
    op: Literal["fill"]
    thread: str | None
    grid: _Size
    at: _Point


type _EntryIn = _ReplaceIn | _StrokeIn | _RectIn | _FillIn
_LIST: TypeAdapter[list[Any]] = TypeAdapter(list[Any])
_ENTRY: TypeAdapter[_EntryIn] = TypeAdapter(
    Annotated[_ReplaceIn | _StrokeIn | _RectIn | _FillIn, Field(discriminator="op")]
)


def read_changes(field: str | None) -> list[Change]:
    """The core's changes for the `changes` field, in order; none for no field.

    A 422 for anything that is not such a list: one error naming `changes` for the field
    as a whole (too long, not JSON, not a list, too many entries), else one per problem,
    in the order of the entries, each naming its entry's position."""
    if not field:
        return []
    if len(field.encode()) > MAX_BYTES:
        raise RequestValidationError([_issue((), f"is longer than {MAX_BYTES} bytes")])
    try:
        entries = _LIST.validate_json(field)
    except PydanticValidationError as error:
        raise RequestValidationError(_issues((), error)) from None
    if len(entries) > MAX_ENTRIES:
        problem = f"holds {len(entries)} entries; at most {MAX_ENTRIES}"
        raise RequestValidationError([_issue((), problem)])
    changes: list[Change] = []
    issues: list[dict[str, Any]] = []
    for position, entry in enumerate(entries):
        try:
            changes.append(_change(_ENTRY.validate_python(entry)))
        except PydanticValidationError as error:
            issues.extend(_issues((position,), error))
        except _UnknownCodeError as unknown:
            issues.append(_issue((position, unknown.name), f"{unknown.code!r} is not a DMC code"))
    if issues:
        raise RequestValidationError(issues)
    return changes


class _UnknownCodeError(Exception):
    """A code no DMC thread has, in the entry field `name`."""

    def __init__(self, name: str, code: str) -> None:
        super().__init__(name, code)
        self.name, self.code = name, code


def _change(entry: _EntryIn) -> Change:
    """One entry as the core's change; `_UnknownCodeError` for a code no thread has."""
    if isinstance(entry, _ReplaceIn):
        return Replace(_known("from", entry.source), _optional("to", entry.to))
    thread = _optional("thread", entry.thread)
    if isinstance(entry, _StrokeIn):
        return Stroke(thread, entry.brush, entry.grid, tuple(entry.points))
    if isinstance(entry, _RectIn):
        return Rect(thread, entry.grid, entry.source, entry.to)
    return Fill(thread, entry.grid, entry.at)


def _optional(name: str, code: str | None) -> Thread | None:
    """The DMC thread of `code`, `None` (bare fabric) for none."""
    return None if code is None else _known(name, code)


def _known(name: str, code: str) -> Thread:
    """The DMC thread of `code`, any case."""
    try:
        return dmc_thread(code)
    except KeyError:
        raise _UnknownCodeError(name, code) from None


def _issues(where: Sequence[Any], error: PydanticValidationError) -> list[dict[str, Any]]:
    """Pydantic's errors as the route reports them, under `changes` and `where`."""
    return [
        {
            "loc": ("body", "changes", *where, *issue["loc"]),
            "msg": issue["msg"],
            "type": issue["type"],
        }
        for issue in error.errors(include_url=False, include_context=False)
    ]


def _issue(where: Sequence[Any], problem: str) -> dict[str, Any]:
    return {"loc": ("body", "changes", *where), "msg": problem, "type": "value_error"}
