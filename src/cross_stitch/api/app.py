"""The HTTP API: `POST /patterns` turns an uploaded image into a DMC pattern as JSON.

Stateless: the upload is decoded in memory, converted by `cross_stitch.pattern`, and
returned; nothing is kept between requests. This module only translates HTTP to and from
the core: validation of the HTTP inputs, decoding, and the JSON shape. Run locally with
`uv run uvicorn cross_stitch.api.app:app --reload`.
"""

import io
import json
import warnings
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
from starlette.formparsers import MultiPartParser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cross_stitch.pattern import EMPTY, Pattern, convert_image, stitch_height

__all__ = ["MAX_UPLOAD_BYTES", "app"]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
"""Largest accepted image upload."""
MAX_WIDTH = 1000
MAX_HEIGHT = 1000
MAX_COLOURS = 100
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


class FinishedSizeOut(BaseModel):
    width_in: float
    height_in: float
    width_cm: float
    height_cm: float


class PatternOut(BaseModel):
    width: int
    height: int
    fabric_count: float
    grid: list[list[int | None]]
    """Rows of key indices; `null` is an empty cell (bare fabric)."""
    key: list[KeyEntryOut]
    total_stitches: int
    finished_size: FinishedSizeOut


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


def _to_json(pattern: Pattern) -> PatternOut:
    return PatternOut(
        width=pattern.width,
        height=pattern.height,
        fabric_count=pattern.fabric_count,
        grid=[[None if cell == EMPTY else cell for cell in row] for row in pattern.grid.tolist()],
        key=[
            KeyEntryOut(
                code=entry.thread.code,
                name=entry.thread.name,
                rgb=entry.thread.rgb,
                stitches=entry.stitches,
                skeins=entry.skeins,
            )
            for entry in pattern.key
        ],
        total_stitches=pattern.total_stitches,
        finished_size=FinishedSizeOut(
            width_in=pattern.width_in,
            height_in=pattern.height_in,
            width_cm=pattern.width_cm,
            height_cm=pattern.height_cm,
        ),
    )


@app.post("/patterns")
def create_pattern(
    image: Annotated[UploadFile, File(description="The image to convert")],
    width: Annotated[int, Form(ge=1, le=MAX_WIDTH, description="Width in stitches")],
    max_colours: Annotated[int, Form(ge=1, le=MAX_COLOURS, description="Most threads used")],
    fabric_count: Annotated[
        float, Form(gt=0, allow_inf_nan=False, description="Stitches per inch")
    ] = 14.0,
) -> PatternOut:
    """Convert an image into a DMC cross-stitch pattern."""
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
    return _to_json(
        convert_image(decoded, width=width, max_colours=max_colours, fabric_count=fabric_count)
    )
