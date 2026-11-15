"""The HTTP API: `POST /patterns` turns an uploaded image into a DMC pattern as JSON,
`POST /patterns/pdf` turns the same inputs into a printable PDF chart, and `GET /limits`
says what the tunable inputs accept.

Stateless: the upload is decoded in memory, converted by `cross_stitch.pattern`, and
returned as JSON or rendered by `cross_stitch.export`; nothing is kept between requests.
This module only translates HTTP to and from the core: validation of the HTTP inputs,
decoding, and the JSON shape. Run locally with
`uv run uvicorn cross_stitch.api.app:app --reload`.
"""

import io
import json
import warnings
from dataclasses import asdict, dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.formparsers import MultiPartParser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cross_stitch.export import (
    MAX_OVERLAP,
    MAX_PAGES,
    OVERLAP,
    Orientation,
    Paper,
    Split,
    SymbolInk,
    Variant,
    pattern_symbols,
    render_pdf,
    symbol_ink,
)
from cross_stitch.pattern import (
    EMPTY,
    CleanedPattern,
    Pattern,
    Replaced,
    clean_pattern,
    convert_image,
    isolated_stitches,
    replace_threads,
    stitch_height,
)
from cross_stitch.threads import Thread, dmc_thread, dmc_threads, similar_dmc

__all__ = ["MAX_UPLOAD_BYTES", "app"]


@dataclass(frozen=True)
class _Setting[T: (int, float)]:
    """What one tunable form field accepts, `min` to `max` inclusive, and what a client
    offers: a `step` for a slider and a `default` to start from. The `Form` constraints
    of the routes and `GET /limits` both read these, so they cannot disagree."""

    min: T
    max: T
    step: T
    default: T


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
"""Largest accepted image upload."""
MAX_HEIGHT = 1000
_WIDTH = _Setting(min=1, max=1000, step=1, default=100)
_MAX_COLOURS = _Setting(min=1, max=100, step=1, default=20)
MAX_COLOURS = _MAX_COLOURS.max
# A step of 0.1 is about a twentieth of a just-noticeable difference (CIEDE2000 about
# 2.3); the routes accept any finite value in range.
_MERGE_DISTANCE = _Setting(min=0.0, max=10.0, step=0.1, default=0.0)
_MIN_STITCHES = _Setting(min=0, max=1000, step=1, default=0)
_CONFETTI_SIZE = _Setting(min=0, max=10, step=1, default=0)
# The chart layout of `POST /patterns/pdf`.
_PAGES = _Setting(min=1, max=MAX_PAGES, step=1, default=2)
_OVERLAP = _Setting(min=0, max=MAX_OVERLAP, step=1, default=OVERLAP)
# Room for the multipart framing and the form fields around the image.
_MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
_TOO_LARGE = f"the upload is larger than {MAX_UPLOAD_BYTES} bytes"

# Starlette writes an uploaded file over `spool_max_size` to a temporary file on disk.
# Every accepted upload fits in memory instead, so nothing touches the disk.
MultiPartParser.spool_max_size = _MAX_BODY_BYTES


class KeyEntryOut(BaseModel):
    code: str
    name: str
    rgb: tuple[int, int, int]
    stitches: int
    skeins: int
    symbol: str
    """The chart symbol, from `cross_stitch.export.pattern_symbols` of this pattern."""
    symbol_ink: SymbolInk
    """The symbol's ink on this thread's colour, as the colour chart prints it."""


class ThreadOut(BaseModel):
    code: str
    name: str
    rgb: tuple[int, int, int]


class SimilarThreadOut(ThreadOut):
    distance: float
    """CIEDE2000 distance from the thread asked about."""


NEAREST_DEFAULT = 10
"""How many nearest threads `GET /threads/{code}/nearest` gives unless asked otherwise."""
NEAREST_MAX = 100


class FinishedSizeOut(BaseModel):
    width_in: float
    height_in: float
    width_cm: float
    height_cm: float


class IsolatedStitchesOut(BaseModel):
    """Stitched cells with no neighbour of the same thread, before and after cleanup."""

    before: int
    after: int


class ConvertedOut(BaseModel):
    """The pattern before cleanup. Width, height, fabric count and finished size are the
    cleaned pattern's: cleanup never changes them."""

    grid: list[list[int | None]]
    """Rows of indices into this object's `key`; `null` is an empty cell (bare fabric)."""
    key: list[KeyEntryOut]
    total_stitches: int


class PatternOut(BaseModel):
    width: int
    height: int
    fabric_count: float
    grid: list[list[int | None]]
    """Rows of key indices; `null` is an empty cell (bare fabric)."""
    key: list[KeyEntryOut]
    total_stitches: int
    finished_size: FinishedSizeOut
    isolated_stitches: IsolatedStitchesOut
    converted: ConvertedOut | None
    """The pattern before cleanup, or `null` when every cleanup setting is 0."""
    ignored_replacements: list[int] = Field(
        description="0-based positions of the `replace` pairs that did nothing"
    )


class SettingOut(BaseModel):
    min: int | float
    max: int | float
    step: int | float
    default: int | float


class LimitsOut(BaseModel):
    max_upload_bytes: int
    settings: dict[str, SettingOut]
    """Keyed by form field name: the conversion settings both pattern routes take, then
    the chart layout settings `POST /patterns/pdf` takes."""


_LIMITS = LimitsOut(
    max_upload_bytes=MAX_UPLOAD_BYTES,
    settings={
        name: SettingOut(**asdict(setting))
        for name, setting in {
            "width": _WIDTH,
            "max_colours": _MAX_COLOURS,
            "merge_distance": _MERGE_DISTANCE,
            "min_stitches": _MIN_STITCHES,
            "confetti_size": _CONFETTI_SIZE,
            "pages_across": _PAGES,
            "pages_down": _PAGES,
            "overlap": _OVERLAP,
        }.items()
    },
)


class _BodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(413, _TOO_LARGE)


def _limit_body(inner: ASGIApp) -> ASGIApp:
    """ASGI guard: refuse a request body over `_MAX_BODY_BYTES` before it is parsed, from
    its Content-Length when given and by counting the bytes received otherwise."""

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > _MAX_BODY_BYTES:
            await _send_too_large(send)
            return
        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > _MAX_BODY_BYTES:
                    raise _BodyTooLarge
            return message

        await inner(scope, counting_receive, send)

    return guarded


async def _send_too_large(send: Send) -> None:
    body = json.dumps({"detail": _TOO_LARGE}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


app = FastAPI(title="Cross-stitch pattern maker")
app.add_middleware(_limit_body)


def _decode(upload: bytes) -> Image.Image:
    """Decode an upload with Pillow, upright per its EXIF orientation; 400 if it is not an
    image Pillow can read (or is a decompression bomb)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(upload))
            image.load()
        return ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise HTTPException(400, "the upload is not a decodable image") from error
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(400, "the image has too many pixels") from error


def _grid_json(pattern: Pattern) -> list[list[int | None]]:
    return [[None if cell == EMPTY else cell for cell in row] for row in pattern.grid.tolist()]


def _key_json(pattern: Pattern) -> list[KeyEntryOut]:
    return [
        KeyEntryOut(
            code=entry.thread.code,
            name=entry.thread.name,
            rgb=entry.thread.rgb,
            stitches=entry.stitches,
            skeins=entry.skeins,
            symbol=symbol,
            symbol_ink=symbol_ink(entry.thread.rgb),
        )
        for entry, symbol in zip(pattern.key, pattern_symbols(pattern), strict=True)
    ]


def _to_json(cleaned: CleanedPattern, replaced: Replaced, *, with_converted: bool) -> PatternOut:
    pattern = replaced.pattern
    converted = cleaned.converted
    return PatternOut(
        width=pattern.width,
        height=pattern.height,
        fabric_count=pattern.fabric_count,
        grid=_grid_json(pattern),
        key=_key_json(pattern),
        total_stitches=pattern.total_stitches,
        finished_size=FinishedSizeOut(
            width_in=pattern.width_in,
            height_in=pattern.height_in,
            width_cm=pattern.width_cm,
            height_cm=pattern.height_cm,
        ),
        isolated_stitches=IsolatedStitchesOut(
            before=cleaned.isolated_before, after=isolated_stitches(pattern)
        ),
        converted=ConvertedOut(
            grid=_grid_json(converted),
            key=_key_json(converted),
            total_stitches=converted.total_stitches,
        )
        if with_converted
        else None,
        ignored_replacements=list(replaced.ignored),
    )


@dataclass(frozen=True)
class _Cleanup:
    """The cleanup settings of a request, applied by `_converted` with the core's
    `clean_pattern`."""

    merge_distance: float
    min_stitches: int
    confetti_size: int

    @property
    def on(self) -> bool:
        """Whether any setting is non-zero; all at 0 leave the pattern as converted."""
        return bool(self.merge_distance or self.min_stitches or self.confetti_size)

    def __call__(self, pattern: Pattern) -> CleanedPattern:
        return clean_pattern(pattern, **asdict(self))


@dataclass(frozen=True)
class _Converted:
    """What `_converted` hands the routes: the cleaned pattern and whether any cleanup
    setting was on."""

    cleaned: CleanedPattern
    cleanup_on: bool
    replaced: Replaced
    """The cleaned pattern after the `replace` pairs: the pattern shown and printed."""


def _cleanup(
    merge_distance: Annotated[
        float,
        Form(
            ge=_MERGE_DISTANCE.min,
            le=_MERGE_DISTANCE.max,
            allow_inf_nan=False,
            description="Merge threads closer than this (CIEDE2000); 0 is off",
        ),
    ] = _MERGE_DISTANCE.default,
    min_stitches: Annotated[
        int,
        Form(
            ge=_MIN_STITCHES.min,
            le=_MIN_STITCHES.max,
            description="Fold threads with fewer stitches; 0 is off",
        ),
    ] = _MIN_STITCHES.default,
    confetti_size: Annotated[
        int,
        Form(
            ge=_CONFETTI_SIZE.min,
            le=_CONFETTI_SIZE.max,
            description="Merge clusters up to this size; 0 is off",
        ),
    ] = _CONFETTI_SIZE.default,
) -> _Cleanup:
    """The cleanup settings, taken by `_converted` so both routes share them."""
    return _Cleanup(
        merge_distance=merge_distance, min_stitches=min_stitches, confetti_size=confetti_size
    )


def _replacement(value: str) -> tuple[Thread, Thread]:
    """One `FROM:TO` value of the `replace` field, as two DMC threads."""
    parts = value.split(":")
    try:
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise KeyError(value)
        return dmc_thread(parts[0]), dmc_thread(parts[1])
    except KeyError:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "replace"),
                    "msg": f"{value!r} is not FROM:TO with two DMC codes",
                    "type": "value_error",
                    "input": value,
                }
            ]
        ) from None


# Each parameter is a form field FastAPI reads; grouping them would hide them from /docs.
def _converted(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    image: Annotated[UploadFile, File(description="The image to convert")],
    width: Annotated[int, Form(ge=_WIDTH.min, le=_WIDTH.max, description="Width in stitches")],
    max_colours: Annotated[
        int,
        Form(ge=_MAX_COLOURS.min, le=_MAX_COLOURS.max, description="Most threads used"),
    ],
    cleanup: Annotated[_Cleanup, Depends(_cleanup)],
    fabric_count: Annotated[
        float, Form(gt=0, allow_inf_nan=False, description="Stitches per inch")
    ] = 14.0,
    replace: Annotated[
        list[str] | None,
        Form(description="Thread swaps FROM:TO (DMC codes), repeated, applied in order"),
    ] = None,
) -> _Converted:
    """The conversion inputs both routes share: validated, decoded and converted here, so
    `POST /patterns` and `POST /patterns/pdf` accept and refuse exactly the same requests.

    The settings come back with the pattern rather than through a second `Depends(_cleanup)`
    in a route: a dependency met twice reports each of its validation errors twice."""
    replacements = [_replacement(value) for value in replace or []]
    upload = image.file.read(MAX_UPLOAD_BYTES + 1)
    if len(upload) > MAX_UPLOAD_BYTES:
        raise _BodyTooLarge
    decoded = _decode(upload)
    height = stitch_height(decoded.width, decoded.height, width)
    if height > MAX_HEIGHT:
        raise HTTPException(
            422,
            f"height would be {height} stitches at width {width}; at most {MAX_HEIGHT}",
        )
    pattern = convert_image(
        decoded, width=width, max_colours=max_colours, fabric_count=fabric_count
    )
    cleaned = cleanup(pattern)
    return _Converted(
        cleaned=cleaned,
        cleanup_on=cleanup.on,
        replaced=replace_threads(cleaned.pattern, replacements),
    )


@app.get("/limits")
def limits() -> LimitsOut:
    """What the tunable inputs of `POST /patterns` accept, keyed by form field, with a
    slider step and a starting value for each, and the largest image upload."""
    return _LIMITS


@app.get("/threads")
def threads() -> list[ThreadOut]:
    """Every DMC thread, in the source table's order."""
    return [ThreadOut(code=t.code, name=t.name, rgb=t.rgb) for t in dmc_threads()]


@app.get("/threads/{code}/nearest")
def nearest_threads(
    code: str,
    count: Annotated[
        int, Query(ge=1, le=NEAREST_MAX, description="How many threads to return")
    ] = NEAREST_DEFAULT,
) -> list[SimilarThreadOut]:
    """The DMC threads nearest to one thread (CIEDE2000), itself excluded, nearest first."""
    try:
        thread = dmc_thread(code)
    except KeyError:
        raise HTTPException(404, f"unknown DMC code: {code}") from None
    return [
        SimilarThreadOut(code=t.code, name=t.name, rgb=t.rgb, distance=distance)
        for t, distance in similar_dmc(thread, count)
    ]


@app.post("/patterns")
def create_pattern(
    converted: Annotated[_Converted, Depends(_converted)],
) -> PatternOut:
    """Convert an image into a DMC cross-stitch pattern, with the pattern before cleanup
    when any cleanup setting is on."""
    return _to_json(converted.cleaned, converted.replaced, with_converted=converted.cleanup_on)


@app.post("/patterns/pdf", response_class=Response)
# Each parameter is a form field FastAPI reads; grouping them would hide them from /docs.
def create_pattern_pdf(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    converted: Annotated[_Converted, Depends(_converted)],
    variant: Annotated[Variant, Form(description="Colour or black and white")] = "colour",
    paper: Annotated[Paper, Form(description="Paper size")] = "A4",
    orientation: Annotated[Orientation, Form(description="Page orientation")] = "portrait",
    split: Annotated[
        Split, Form(description="cells: a 3 mm cell; pages: exactly pages_across x pages_down")
    ] = "cells",
    pages_across: Annotated[
        int, Form(ge=_PAGES.min, le=_PAGES.max, description="Pages across, split=pages")
    ] = _PAGES.default,
    pages_down: Annotated[
        int, Form(ge=_PAGES.min, le=_PAGES.max, description="Pages down, split=pages")
    ] = _PAGES.default,
    overlap: Annotated[
        int,
        Form(ge=_OVERLAP.min, le=_OVERLAP.max, description="Columns or rows pages repeat"),
    ] = _OVERLAP.default,
    centre_lines: Annotated[
        bool, Form(description="Draw the centre column and row through the chart")
    ] = False,
) -> Response:
    """Convert an image as `POST /patterns` does and return it as a printable PDF chart.

    The same request always gives the same bytes, so a client can ask again for the chart
    of the pattern it shows; nothing is stored between requests. A pages split that would
    need cells under 2 mm is a 422 naming the fewest pages that fit.
    """
    try:
        pdf = render_pdf(
            converted.replaced.pattern,
            variant=variant,
            paper=paper,
            orientation=orientation,
            split=split,
            pages_across=pages_across,
            pages_down=pages_down,
            overlap=overlap,
            centre_lines=centre_lines,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="pattern.pdf"'},
    )
