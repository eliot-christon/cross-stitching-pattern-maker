"""DMC stranded cotton threads: the table and nearest-thread lookup.

The table is `dmc.csv`, shipped inside the package byte for byte as its source published
it; `DMC_SOURCE.md` next to it names the source, commit, licence (CC BY 4.0) and hash.
At load, runs of whitespace in a name collapse to one space and surrounding whitespace
is stripped; nothing else changes.

Nearest-thread lookup measures CIEDE2000 in CIELAB (`cross_stitch.colour`). A tie goes
to the lowest palette index, which for DMC is the earliest row of the source file.
"""

import csv
import functools
import io
from dataclasses import dataclass
from importlib import resources

import numpy as np
import numpy.typing as npt

from cross_stitch.colour import delta_e_2000_matrix, srgb_to_lab

__all__ = [
    "Thread",
    "dmc_thread",
    "dmc_threads",
    "nearest_dmc",
    "nearest_dmc_lab",
    "nearest_indices",
]


@dataclass(frozen=True)
class Thread:
    """One thread colour: its brand code, name and sRGB colour (0-255 per component)."""

    code: str
    name: str
    rgb: tuple[int, int, int]


@functools.cache
def dmc_threads() -> tuple[Thread, ...]:
    """All DMC threads, in the order of the source file."""
    text = resources.files(__package__).joinpath("dmc.csv").read_text(encoding="utf-8")
    return tuple(
        Thread(
            code=row["code"],
            name=" ".join(row["name"].split()),
            rgb=(int(row["r"]), int(row["g"]), int(row["b"])),
        )
        for row in csv.DictReader(io.StringIO(text, newline=""))
    )


@functools.cache
def _by_code() -> dict[str, Thread]:
    return {thread.code.casefold(): thread for thread in dmc_threads()}


@functools.cache
def _dmc_lab() -> npt.NDArray[np.float64]:
    return srgb_to_lab([thread.rgb for thread in dmc_threads()])


def dmc_thread(code: str) -> Thread:
    """The DMC thread with this code, ignoring case and surrounding whitespace.

    Raises `KeyError` for an unknown code. There are no aliases: "White" is not "Blanc".
    """
    try:
        return _by_code()[code.strip().casefold()]
    except KeyError:
        raise KeyError(f"unknown DMC code: {code!r}") from None


def nearest_indices(lab: npt.ArrayLike, palette_lab: npt.ArrayLike) -> npt.NDArray[np.intp]:
    """Index of the nearest palette colour (CIEDE2000) for each Lab colour.

    `lab` is (N, 3) and `palette_lab` (M, 3); the result is (N,). A tie goes to the lowest
    palette index. Raises `ValueError` on an empty palette or a wrong shape.
    """
    palette = np.asarray(palette_lab, dtype=np.float64)
    if palette.ndim == 2 and palette.shape[0] == 0:
        raise ValueError("the palette is empty")
    indices: npt.NDArray[np.intp] = np.argmin(delta_e_2000_matrix(lab, palette), axis=1)
    return indices


def nearest_dmc_lab(lab: npt.ArrayLike) -> tuple[Thread, ...]:
    """The nearest DMC thread for each Lab colour of an (N, 3) array."""
    threads = dmc_threads()
    return tuple(threads[i] for i in nearest_indices(lab, _dmc_lab()))


def nearest_dmc(rgb: npt.ArrayLike) -> tuple[Thread, ...]:
    """The nearest DMC thread for each 8-bit sRGB colour of an (N, 3) array."""
    return nearest_dmc_lab(srgb_to_lab(rgb))
