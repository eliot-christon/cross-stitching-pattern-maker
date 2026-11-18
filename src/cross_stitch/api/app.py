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
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Annotated, Literal

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
    LayoutSettings,
    Orientation,
    Paper,
    Split,
    SymbolInk,
    Variant,
    chart_layout,
    page_options,
    pattern_symbols,
    render_pdf,
    section_name,
    symbol_ink,
)
from cross_stitch.pattern import (
    EMPTY,
    Adjustments,
    CleanedPattern,
    Pattern,
    PixelGrid,
    Replaced,
    adjust_image,
    background_as_fabric,
    clean_pattern,
    colours_with_headroom,
    convert_image,
    fabric_weave,
    find_pixel_grid,
    find_stitch_grid,
    isolated_stitches,
    pixel_art_colours,
    replace_threads,
    stitch_height,
    symbols_only,
    unscale_pixel_art,
    unstitch,
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
# The image adjustments, as `Adjustments` reads them: percentages, degrees and a gamma.
_TONE = _Setting(min=-100, max=100, step=1, default=0)
_HUE = _Setting(min=-180, max=180, step=1, default=0)
_GAMMA = _Setting(min=0.25, max=4.0, step=0.05, default=1.0)
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


ReadAs = Literal["picture", "pixel_art", "stitched"]
"""How the pattern routes read an upload. `picture` resamples it to `width`; every other
kind is a grid kind: the source's own grid of cells, one stitch per cell (`pixel_art`:
flat cells, `find_pixel_grid`; `stitched`: textured stitches or a chart's cells under
symbols, `find_stitch_grid`)."""


class SourceGridOut(BaseModel):
    width: int
    """Cells across the source's grid: the pattern's width when read as its kind."""
    height: int
    colours: int
    """Colours a stitcher would tell apart, at most the colour limit."""


class InspectOut(BaseModel):
    kind: ReadAs | None
    """How the upload reads best, sent back as `read_as`; `null` when it is no image."""
    description: str
    """What was found, in words, for the page to show."""
    grid: SourceGridOut | None
    """The source's grid for a grid kind, else `null`."""
    warnings: list[str]
    """What the reading changed or could not do."""
    refusal: str | None
    """Why the upload cannot be read as found, else `null`."""


class BandOut(BaseModel):
    start: int
    """First cell, 0-based."""
    end: int
    """One past the last cell."""
    repeated: int
    """Leading cells repeated from the previous page."""


class LayoutOut(BaseModel):
    cell_mm: float
    columns: list[BandOut]
    rows: list[BandOut]
    sections: list[list[str]]
    """Section names, by row then column: `sections[row][column]`."""


class PageOptionOut(BaseModel):
    cell_mm: float | None
    """The chart cell of this pages split, or `null` where it is refused."""
    columns: int
    """Cells across the widest page."""
    rows: int
    """Cells down the tallest page."""


class ChartLayoutOut(BaseModel):
    layout: LayoutOut | None
    """How the chart is cut, or `null` when the split is refused."""
    message: str | None
    """Why the split is refused, as `POST /patterns/pdf` would say it."""
    pages: list[list[PageOptionOut]]
    """Every pages split, `pages[down - 1][across - 1]`, 1 to 20 each way."""


class SettingOut(BaseModel):
    min: int | float
    max: int | float
    step: int | float
    default: int | float


class LimitsOut(BaseModel):
    max_upload_bytes: int
    settings: dict[str, SettingOut]
    """Keyed by form field name: the conversion settings both pattern routes take, the
    image adjustments every route reading an image takes, then the chart layout settings
    `POST /patterns/pdf` takes."""


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
            "brightness": _TONE,
            "contrast": _TONE,
            "saturation": _TONE,
            "hue": _HUE,
            "gamma": _GAMMA,
            "sharpness": _TONE,
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


PDF_REFUSAL = "PDF charts cannot be read: upload an image of the pattern (PNG or JPEG)"


def _is_pdf(upload: bytes) -> bool:
    return upload.startswith(b"%PDF-")


def _decode(upload: bytes) -> Image.Image:
    """Decode an upload with Pillow, upright per its EXIF orientation; 400 if it is a PDF
    or not an image Pillow can read (or is a decompression bomb)."""
    if _is_pdf(upload):
        raise HTTPException(400, PDF_REFUSAL)
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


def _read_bytes(upload: UploadFile) -> bytes:
    """The uploaded file's bytes; 413 over `MAX_UPLOAD_BYTES`."""
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise _BodyTooLarge
    return data


CropField = Annotated[
    str | None,
    Form(
        description="Keep only this box of the upright image before reading it: "
        "left,top,right,bottom in pixels, right and bottom excluded"
    ),
]


def _cropped(image: Image.Image, crop: str | None) -> Image.Image:
    """The image inside the `crop` box, in pixels of the upright image; the whole image
    with no box. A box that is not four whole numbers, empty, inverted or not inside the
    image is a 422 naming `crop`."""
    if not crop:
        return image
    try:
        left, top, right, bottom = (int(part) for part in crop.split(","))
    except ValueError:
        raise _crop_error(crop, "is not left,top,right,bottom in whole pixels") from None
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise _crop_error(
            crop, f"is not a non-empty box inside the {image.width} x {image.height} image"
        )
    return image.crop((left, top, right, bottom))


def _crop_error(crop: str, problem: str) -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "loc": ("body", "crop"),
                "msg": f"{crop!r} {problem}",
                "type": "value_error",
                "input": crop,
            }
        ]
    )


# Each parameter is a form field FastAPI reads; grouping them would hide them from /docs.
def _adjustments(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    brightness: Annotated[
        int,
        Form(ge=_TONE.min, le=_TONE.max, description="Brightness, % (-100 is black; 0 is off)"),
    ] = _TONE.default,
    contrast: Annotated[
        int,
        Form(ge=_TONE.min, le=_TONE.max, description="Contrast, % (-100 is flat; 0 is off)"),
    ] = _TONE.default,
    saturation: Annotated[
        int,
        Form(ge=_TONE.min, le=_TONE.max, description="Saturation, % (-100 is greys; 0 is off)"),
    ] = _TONE.default,
    hue: Annotated[
        int,
        Form(ge=_HUE.min, le=_HUE.max, description="Hue turn around the colour wheel, degrees"),
    ] = _HUE.default,
    gamma: Annotated[
        float,
        Form(
            ge=_GAMMA.min,
            le=_GAMMA.max,
            allow_inf_nan=False,
            description="Gamma (above 1 lightens the mid-tones; 1 is off)",
        ),
    ] = _GAMMA.default,
    sharpness: Annotated[
        int,
        Form(ge=_TONE.min, le=_TONE.max, description="Sharpness, % (below 0 softens; 0 is off)"),
    ] = _TONE.default,
) -> Adjustments:
    """The image adjustments, applied right after the crop, so the inspection, every
    reader and the conversion see the adjusted image."""
    return Adjustments(
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
        hue=hue,
        gamma=gamma,
        sharpness=sharpness,
    )


def _read_image(upload: UploadFile, crop: str | None, adjustments: Adjustments) -> Image.Image:
    """The uploaded image, decoded, cropped to `crop` and adjusted; 413 over
    `MAX_UPLOAD_BYTES`, 400 if not an image, 422 for a bad box."""
    return adjust_image(_cropped(_decode(_read_bytes(upload)), crop), adjustments)


@dataclass(frozen=True)
class _Reader:
    """How a grid kind finds its grid in an image and reduces the image to it."""

    find: Callable[[Image.Image], PixelGrid | None]
    reduce: Callable[[Image.Image, PixelGrid], Image.Image]
    label: str
    """The kind in words, as the inspection describes it."""
    cells: str
    """What its cells are, for the 422 when there is no grid."""


_READERS: dict[ReadAs, _Reader] = {
    "pixel_art": _Reader(find_pixel_grid, unscale_pixel_art, "Pixel art", "art pixels"),
    "stitched": _Reader(find_stitch_grid, unstitch, "Stitched", "stitches"),
}
"""The grid kinds, in the order the inspection tries them: flat pixel art first, so every
image it reads stays read that way."""

WEAVE_REFUSAL = (
    "Fabric weave found but no grid of stitches: photograph the stitching flat and face "
    "on, or treat the image as a photo"
)
SYMBOLS_REFUSAL = (
    "The chart's cells hold symbols, not thread colours (its colours are only in its "
    "key): use a colour chart, or treat the image as a photo"
)
PITCH_WARNING = 0.02
"""Relative difference between a grid's cell width and height worth a warning."""


def _source_grid(image: Image.Image, read_as: ReadAs) -> Image.Image:
    """The image reduced to one pixel per cell of its own grid, as `read_as` reads it;
    422 naming `read_as` when it has no such grid. A picture is returned as it is."""
    if read_as == "picture":
        return image
    reader = _READERS[read_as]
    grid = reader.find(image)
    if grid is None:
        raise HTTPException(422, f"read_as: no grid of {reader.cells} found in the image")
    return reader.reduce(image, grid)


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

    def colours_to_convert(self, max_colours: int) -> int:
        """Threads to convert with: more than asked when cleanup will remove some, since
        `clean_pattern` caps the result at `max_colours` anyway."""
        return colours_with_headroom(max_colours) if self.on else max_colours

    def __call__(self, pattern: Pattern, max_colours: int) -> CleanedPattern:
        return clean_pattern(pattern, **asdict(self), max_colours=max_colours)


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


FABRIC = "fabric"
"""The `TO` of a `replace` value that removes a thread, leaving its cells bare fabric. No
DMC code reads like it, whatever the case."""


def _replacement(value: str) -> tuple[Thread, Thread | None]:
    """One `FROM:TO` value of the `replace` field: a DMC thread and the DMC thread taking
    its stitches, or `None` for `FABRIC`."""
    parts = value.split(":")
    try:
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise KeyError(value)
        source, target = parts
        if target.strip().casefold() == FABRIC:
            return dmc_thread(source), None
        return dmc_thread(source), dmc_thread(target)
    except KeyError:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "replace"),
                    "msg": f"{value!r} is not FROM:TO with two DMC codes (TO may be {FABRIC!r})",
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
        Form(
            ge=_MAX_COLOURS.min,
            le=_MAX_COLOURS.max,
            description="Threads of the pattern, after cleanup (fewer only if the image "
            "or the cleanup leaves fewer)",
        ),
    ],
    cleanup: Annotated[_Cleanup, Depends(_cleanup)],
    adjustments: Annotated[Adjustments, Depends(_adjustments)],
    fabric_count: Annotated[
        float, Form(gt=0, allow_inf_nan=False, description="Stitches per inch")
    ] = 14.0,
    replace: Annotated[
        list[str] | None,
        Form(
            description="Thread swaps FROM:TO (DMC codes; TO 'fabric' removes FROM), "
            "repeated, applied in order"
        ),
    ] = None,
    read_as: Annotated[
        ReadAs,
        Form(
            description="How to read the image: picture (resampled to width) or a grid "
            "kind from POST /images/inspect (one stitch per cell of its own grid; width "
            "unused)"
        ),
    ] = "picture",
    crop: CropField = None,
    background_fabric: Annotated[
        bool,
        Form(
            alias="background_as_fabric",
            description="Leave the background bare: the thread most frequent on the border, "
            "where it joins the border",
        ),
    ] = False,
) -> _Converted:
    """The conversion inputs both routes share: validated, decoded and converted here, so
    `POST /patterns` and `POST /patterns/pdf` accept and refuse exactly the same requests.

    The settings come back with the pattern rather than through a second `Depends(_cleanup)`
    in a route: a dependency met twice reports each of its validation errors twice."""
    replacements = [_replacement(value) for value in replace or []]
    decoded = _source_grid(_read_image(image, crop, adjustments), read_as)
    if read_as != "picture":
        width = decoded.width
        if width > _WIDTH.max:
            raise HTTPException(
                422, f"read_as: the grid is {width} stitches wide; at most {_WIDTH.max}"
            )
    height = stitch_height(decoded.width, decoded.height, width)
    if height > MAX_HEIGHT:
        raise HTTPException(
            422,
            f"height would be {height} stitches at width {width}; at most {MAX_HEIGHT}",
        )
    # The background takes a thread away: convert with one more, so `max_colours` stitched
    # threads remain when the image has that many besides it (cleanup caps the rest).
    pattern = convert_image(
        decoded,
        width=width,
        max_colours=cleanup.colours_to_convert(max_colours) + int(background_fabric),
        fabric_count=fabric_count,
    )
    if background_fabric:
        pattern = background_as_fabric(pattern)
    cleaned = cleanup(pattern, max_colours)
    return _Converted(
        cleaned=cleaned,
        cleanup_on=cleanup.on,
        replaced=replace_threads(cleaned.pattern, replacements),
    )


@app.post("/images/inspect")
def inspect_image(
    image: Annotated[UploadFile, File(description="The image to look at")],
    adjustments: Annotated[Adjustments, Depends(_adjustments)],
    crop: CropField = None,
) -> InspectOut:
    """What the upload is and how it reads best: its `kind` (sent back as `read_as`), the
    source grid of a grid kind with the settings that give one stitch per cell, what the
    reading changes, and why it cannot be read when it cannot. A PDF is refused here, with
    a 200; bytes that are no image are a 400, as on the pattern routes."""
    data = _read_bytes(image)
    if _is_pdf(data):
        return InspectOut(
            kind=None, description="PDF document", grid=None, warnings=[], refusal=PDF_REFUSAL
        )
    decoded = adjust_image(_cropped(_decode(data), crop), adjustments)
    found = _found_grid(decoded)
    if found is None:
        return _picture(WEAVE_REFUSAL if fabric_weave(decoded) else None)
    kind, grid = found
    # Flat white cells under symbols are pixel art to its reader: checked for every kind.
    if symbols_only(decoded, grid):
        return _picture(SYMBOLS_REFUSAL)
    reader = _READERS[kind]
    return _grid_inspection(kind, reader, grid, reader.reduce(decoded, grid))


def _found_grid(image: Image.Image) -> tuple[ReadAs, PixelGrid] | None:
    """The first grid kind whose reader finds a grid in `image`, and that grid. A pixel art
    at its own size (one pixel per cell) is the last resort: a grid of larger cells that a
    later reader finds is what the image shows."""
    fallback: tuple[ReadAs, PixelGrid] | None = None
    for kind, reader in _READERS.items():
        grid = reader.find(image)
        if grid is None:
            continue
        if grid.pitch_x > 1 or grid.pitch_y > 1:
            return kind, grid
        fallback = fallback or (kind, grid)
    return fallback


def _picture(refusal: str | None) -> InspectOut:
    return InspectOut(
        kind="picture", description="Picture", grid=None, warnings=[], refusal=refusal
    )


def _grid_inspection(
    kind: ReadAs, reader: _Reader, grid: PixelGrid, reduced: Image.Image
) -> InspectOut:
    """The inspection of a source read as `kind`: its grid, colours and warnings."""
    colours = pixel_art_colours(reduced)
    warnings_ = []
    if abs(grid.pitch_x - grid.pitch_y) > PITCH_WARNING * max(grid.pitch_x, grid.pitch_y):
        warnings_.append(
            f"Cells are {grid.pitch_x:.1f} x {grid.pitch_y:.1f} pixels, not square: the image "
            "may be stretched; the pattern follows its grid"
        )
    if colours > _MAX_COLOURS.max:
        warnings_.append(
            f"{colours} colours found; patterns hold at most {_MAX_COLOURS.max}, "
            "so the closest ones merge"
        )
        colours = _MAX_COLOURS.max
    return InspectOut(
        kind=kind,
        description=f"{reader.label}, {grid.columns} x {grid.rows} stitches, {colours} colours",
        grid=SourceGridOut(width=grid.columns, height=grid.rows, colours=colours),
        warnings=warnings_,
        refusal=None,
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


# Each parameter is a form field FastAPI reads; grouping them would hide them from /docs.
def _layout(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
) -> LayoutSettings:
    """The chart layout settings of `POST /patterns/pdf`, as `render_pdf` takes them."""
    return LayoutSettings(
        paper=paper,
        orientation=orientation,
        split=split,
        pages_across=pages_across,
        pages_down=pages_down,
        overlap=overlap,
    )


def _hex_rgb(colour: str) -> tuple[int, int, int]:
    """A `#rrggbb` colour, already checked by its form field, as (r, g, b)."""
    value = int(colour[1:], 16)
    return (value >> 16, (value >> 8) & 0xFF, value & 0xFF)


@app.post("/chart/layout")
def chart_layout_route(
    width: Annotated[int, Form(ge=_WIDTH.min, le=_WIDTH.max, description="Pattern width")],
    height: Annotated[int, Form(ge=1, le=MAX_HEIGHT, description="Pattern height")],
    layout: Annotated[LayoutSettings, Depends(_layout)],
) -> ChartLayoutOut:
    """How `POST /patterns/pdf` would cut a pattern of this size into pages with these
    layout fields, and the cell of every pages split, for choosing one."""
    # `_layout` fills every field, with the PDF route's defaults.
    options = page_options(
        width,
        height,
        paper=layout["paper"],
        orientation=layout["orientation"],
        overlap=layout["overlap"],
    )
    pages = [[PageOptionOut(**asdict(option)) for option in row] for row in options]
    try:
        cut = chart_layout(width, height, **layout)
    except ValueError as error:
        return ChartLayoutOut(layout=None, message=str(error), pages=pages)
    return ChartLayoutOut(
        layout=LayoutOut(
            cell_mm=cut.cell_mm,
            columns=[BandOut(**asdict(band)) for band in cut.columns],
            rows=[BandOut(**asdict(band)) for band in cut.rows],
            sections=[
                [section_name(column, row) for column in range(len(cut.columns))]
                for row in range(len(cut.rows))
            ],
        ),
        message=None,
        pages=pages,
    )


@app.post("/patterns/pdf", response_class=Response)
def create_pattern_pdf(
    converted: Annotated[_Converted, Depends(_converted)],
    layout: Annotated[LayoutSettings, Depends(_layout)],
    variant: Annotated[Variant, Form(description="Colour or black and white")] = "colour",
    centre_lines: Annotated[
        bool, Form(description="Draw the centre column and row through the chart")
    ] = False,
    fabric_colour: Annotated[
        str,
        Form(
            pattern=r"^#[0-9a-fA-F]{6}$",
            description="Fabric colour as #rrggbb, for bare fabric in the thumbnails",
        ),
    ] = "#ffffff",
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
            centre_lines=centre_lines,
            fabric_rgb=_hex_rgb(fabric_colour),
            **layout,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="pattern.pdf"'},
    )
