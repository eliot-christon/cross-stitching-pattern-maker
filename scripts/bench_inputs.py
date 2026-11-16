"""Run every file of a folder through the API in process and draw one before/after sheet.

    uv run python scripts/bench_inputs.py [INPUT_DIR] [OUTPUT_DIR]

Defaults: `input_examples/` in, `out/bench/` out. Each file, in name order, is inspected
(`POST /images/inspect`) and then converted (`POST /patterns`) with what the inspection
suggests, through FastAPI's `TestClient`, so the bench sees exactly what the page sees.
The sheet holds one row per file: its name, a thumbnail, what the inspection said, the
pattern one block per cell (bare fabric checked grey) and how long each request took. The
same rows go to stdout as a table. A file that fails never stops the run.

This is a dev tool for judging the readers on a local corpus, not a test: the corpus is
not in git and tests never read it.
"""

import argparse
import sys
import textwrap
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from cross_stitch.api.app import app

SHEET_NAME = "bench.png"
TILE = 220
"""Side of the source thumbnail and of the pattern drawing, in sheet pixels."""
TEXT_WIDTH = 420
MARGIN = 10
BACKGROUND = (255, 255, 255)
PLACEHOLDER = (236, 236, 236)
BARE = ((228, 228, 228), (246, 246, 246))
"""The two greys bare fabric is checked in, so it never reads as a white thread."""


@dataclass(frozen=True)
class Row:
    """What the bench found for one file."""

    name: str
    inspection: dict[str, Any] | None
    """The inspection's JSON, or `None` when it failed."""
    inspection_error: str | None
    pattern: dict[str, Any] | None
    """The `POST /patterns` JSON, or `None` when it failed."""
    pattern_error: str | None
    inspect_seconds: float
    pattern_seconds: float

    @property
    def found(self) -> str:
        """What the inspection said, in a few words."""
        if self.inspection is None:
            return f"error: {self.inspection_error}"
        found = f"{self.inspection['kind'] or 'unread'}: {self.inspection['description']}"
        if self.inspection["refusal"]:
            found += f" (refused: {self.inspection['refusal']})"
        return "; ".join([found, *self.inspection["warnings"]])

    @property
    def result(self) -> str:
        """The pattern's size and threads, or the conversion's error."""
        if self.pattern is None:
            return f"error: {self.pattern_error}"
        return (
            f"{self.pattern['width']} x {self.pattern['height']}, "
            f"{len(self.pattern['key'])} threads"
        )


def _detail(response: Any) -> str:
    """The API's message for a failed request, as the page would show it."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "; ".join(f"{'.'.join(map(str, d['loc'][1:]))}: {d['msg']}" for d in detail)
    return f"HTTP {response.status_code}"


def _settings(client: TestClient, inspection: dict[str, Any] | None) -> dict[str, str]:
    """The form fields the page would send after this inspection: the source grid's for
    a grid kind, read as that kind; otherwise the `/limits` defaults, as a picture."""
    grid = (inspection or {}).get("grid")
    if grid:
        return {
            "width": str(grid["width"]),
            "max_colours": str(grid["colours"]),
            "read_as": inspection["kind"] if inspection else "picture",
        }
    defaults = client.get("/limits").json()["settings"]
    return {
        "width": str(defaults["width"]["default"]),
        "max_colours": str(defaults["max_colours"]["default"]),
    }


def bench_file(client: TestClient, path: Path) -> Row:
    """Inspect one file, then convert it as the inspection suggests."""
    data = path.read_bytes()
    files = {"image": (path.name, data, "application/octet-stream")}

    start = time.perf_counter()
    response = client.post("/images/inspect", files=files)
    inspect_seconds = time.perf_counter() - start
    inspection = response.json() if response.status_code == 200 else None
    inspection_error = None if inspection is not None else _detail(response)

    refusal = (inspection or {}).get("refusal")
    pattern: dict[str, Any] | None = None
    pattern_error: str | None = refusal
    pattern_seconds = 0.0
    if not refusal:
        # As the page: a refused upload is not converted until "Treat as a photo".
        start = time.perf_counter()
        response = client.post("/patterns", data=_settings(client, inspection), files=files)
        pattern_seconds = time.perf_counter() - start
        pattern = response.json() if response.status_code == 200 else None
        pattern_error = None if pattern is not None else _detail(response)

    return Row(
        name=path.name,
        inspection=inspection,
        inspection_error=inspection_error,
        pattern=pattern,
        pattern_error=pattern_error,
        inspect_seconds=inspect_seconds,
        pattern_seconds=pattern_seconds,
    )


def bench(folder: Path) -> list[Row]:
    """One row per file of the folder, in name order."""
    client = TestClient(app)
    paths = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name)
    return [bench_file(client, path) for path in paths]


def pattern_image(pattern: dict[str, Any]) -> Image.Image:
    """The pattern one pixel per cell, in its threads' colours, bare fabric checked."""
    image = Image.new("RGB", (pattern["width"], pattern["height"]))
    colours = [tuple(entry["rgb"]) for entry in pattern["key"]]
    image.putdata(
        [
            BARE[(x + y) % 2] if cell is None else colours[cell]
            for y, row in enumerate(pattern["grid"])
            for x, cell in enumerate(row)
        ]
    )
    return image


def _fit(image: Image.Image, resample: Image.Resampling) -> Image.Image:
    """The image scaled to fit a tile, keeping its shape."""
    scale = TILE / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.convert("RGB").resize(size, resample)


def _thumbnail(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as source:
            return _fit(source, Image.Resampling.LANCZOS)
    except UnidentifiedImageError, OSError:
        return None


def draw_sheet(rows: Sequence[Row], folder: Path) -> Image.Image:
    """One band per row: text, the source, the pattern."""
    font = ImageFont.load_default(size=15)
    band = TILE + 2 * MARGIN
    sheet = Image.new("RGB", (TEXT_WIDTH + 2 * TILE + 4 * MARGIN, band * len(rows)), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        top = index * band + MARGIN
        lines = [
            row.name,
            f"inspect: {row.found}",
            f"pattern: {row.result}",
            f"{row.inspect_seconds:.2f} s + {row.pattern_seconds:.2f} s",
        ]
        draw.multiline_text((MARGIN, top), "\n".join(_wrap(lines)), fill=(0, 0, 0), font=font)
        left = TEXT_WIDTH + 2 * MARGIN
        draw.rectangle((left, top, left + TILE - 1, top + TILE - 1), fill=PLACEHOLDER)
        thumbnail = _thumbnail(folder / row.name)
        if thumbnail is None:
            draw.text((left + MARGIN, top + MARGIN), "no preview", fill=(0, 0, 0), font=font)
        else:
            sheet.paste(thumbnail, (left, top))
        if row.pattern is not None:
            sheet.paste(
                _fit(pattern_image(row.pattern), Image.Resampling.NEAREST),
                (left + TILE + MARGIN, top),
            )
        draw.line((0, top + band - MARGIN, sheet.width, top + band - MARGIN), fill=PLACEHOLDER)
    return sheet


def _wrap(lines: Sequence[str], width: int = 48) -> list[str]:
    """Lines wrapped between words to fit the text column."""
    return [part for line in lines for part in textwrap.wrap(line, width) or [""]]


def table(rows: Sequence[Row]) -> str:
    """The rows as a plain-text table."""
    lines = [f"{'file':32} {'inspect':40} {'pattern':40} seconds"]
    lines += [
        f"{row.name:32} {row.found[:40]:40} {row.result[:40]:40} "
        f"{row.inspect_seconds + row.pattern_seconds:.2f}"
        for row in rows
    ]
    return "\n".join(lines)


def run(folder: Path, output: Path) -> list[Row]:
    """Bench the folder and write the sheet into `output`; no sheet for an empty folder."""
    rows = bench(folder)
    if rows:
        output.mkdir(parents=True, exist_ok=True)
        draw_sheet(rows, folder).save(output / SHEET_NAME)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("input", nargs="?", type=Path, default=Path("input_examples"))
    parser.add_argument("output", nargs="?", type=Path, default=Path("out/bench"))
    args = parser.parse_args(argv)
    if not args.input.is_dir():
        print(f"no such folder: {args.input}", file=sys.stderr)
        return 2
    start = time.perf_counter()
    rows = run(args.input, args.output)
    print(table(rows))
    print(
        f"{len(rows)} files in {time.perf_counter() - start:.1f} s; sheet: "
        f"{args.output / SHEET_NAME if rows else 'none (empty folder)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
