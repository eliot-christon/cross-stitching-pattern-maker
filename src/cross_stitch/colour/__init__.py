"""Colour spaces and colour difference: sRGB -> CIELAB (D65) and CIEDE2000.

Pure numpy maths, vectorised over arrays of colours whose last axis holds the three
components. Every operation is elementwise (no matrix product, no reduction across
colours) and runs on contiguous 1-D arrays, one per component, whatever the input shape:
one colour goes through the same numpy loops as a batch (never numpy's scalar path), so a
batch call returns bit for bit what one call per colour returns.

References:
- sRGB: IEC 61966-2-1, with the sRGB -> XYZ matrix and D65 white of Lindbloom
  (http://www.brucelindbloom.com).
- CIEDE2000: G. Sharma, W. Wu, E. N. Dalal, "The CIEDE2000 color-difference formula:
  implementation notes, supplementary test data, and mathematical observations",
  Color Research & Application 30(1), 2005, with kL = kC = kH = 1.
"""

import numpy as np
import numpy.typing as npt

__all__ = ["delta_e_2000", "delta_e_2000_matrix", "srgb_to_lab"]

FloatArray = npt.NDArray[np.float64]

# Linear sRGB -> CIE XYZ, D65 (Lindbloom).
_SRGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
# D65 reference white, Y normalised to 1.
_WHITE_D65 = (0.95047, 1.0, 1.08883)

_EPSILON = (6 / 29) ** 3
_KAPPA_SLOPE = 1 / (3 * (6 / 29) ** 2)
_POW25_7 = 25.0**7


def _as_colours(values: npt.ArrayLike, what: str) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 0 or array.shape[-1] != 3:
        raise ValueError(f"{what} must have shape (..., 3), got {array.shape}")
    return array


def _components(colours: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    """The three components of (..., 3) colours, each a contiguous 1-D array."""
    first, second, third = np.ascontiguousarray(colours.reshape(-1, 3).T)
    return first, second, third


def srgb_to_lab(rgb: npt.ArrayLike) -> FloatArray:
    """Convert 8-bit sRGB colours (0-255, shape (..., 3)) to CIELAB under D65.

    Raises `ValueError` if the last axis is not 3 or a component lies outside [0, 255]
    (NaN included).
    """
    srgb = _as_colours(rgb, "sRGB colours")
    if not np.all((srgb >= 0) & (srgb <= 255)):
        raise ValueError("sRGB components must lie in [0, 255]")
    r, g, b = (
        np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        for c in (component / 255.0 for component in _components(srgb))
    )
    xyz = [m0 * r + m1 * g + m2 * b for m0, m1, m2 in _SRGB_TO_XYZ]
    fx, fy, fz = (
        np.where(t > _EPSILON, np.cbrt(t), t * _KAPPA_SLOPE + 4 / 29)
        for t in (component / white for component, white in zip(xyz, _WHITE_D65, strict=True))
    )
    lab = np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)
    return lab.reshape(srgb.shape)


def _primed_chroma_hue(
    a1: FloatArray, b1: FloatArray, a2: FloatArray, b2: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """C' and h' (degrees in [0, 360)) of both colours, a* rescaled by the G factor."""
    c_bar7 = ((np.hypot(a1, b1) + np.hypot(a2, b2)) / 2) ** 7
    scale = 1 + 0.5 * (1 - np.sqrt(c_bar7 / (c_bar7 + _POW25_7)))
    c1p, c2p = np.hypot(scale * a1, b1), np.hypot(scale * a2, b2)
    h1p = np.degrees(np.arctan2(b1, scale * a1)) % 360
    h2p = np.degrees(np.arctan2(b2, scale * a2)) % 360
    return c1p, h1p, c2p, h2p


def _hue_difference_and_mean(
    h1p: FloatArray, h2p: FloatArray, chroma_zero: npt.NDArray[np.bool_]
) -> tuple[FloatArray, FloatArray]:
    """Delta h' and mean h', both the short way round the hue circle.

    When either chroma is zero the hue is undefined: delta h' is 0 and mean h' is the sum.
    """
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    h_sum = h1p + h2p
    hp_bar = np.where(
        np.abs(h1p - h2p) <= 180,
        h_sum / 2,
        np.where(h_sum < 360, (h_sum + 360) / 2, (h_sum - 360) / 2),
    )
    return np.where(chroma_zero, 0.0, dh), np.where(chroma_zero, h_sum, hp_bar)


def _weights(
    lp_bar: FloatArray, cp_bar: FloatArray, hp_bar: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """The weighting functions S_L, S_C, S_H and the rotation term R_T."""
    t = (
        1
        - 0.17 * np.cos(np.radians(hp_bar - 30))
        + 0.24 * np.cos(np.radians(2 * hp_bar))
        + 0.32 * np.cos(np.radians(3 * hp_bar + 6))
        - 0.20 * np.cos(np.radians(4 * hp_bar - 63))
    )
    d_theta = 30 * np.exp(-(((hp_bar - 275) / 25) ** 2))
    cp_bar7 = cp_bar**7
    r_c = 2 * np.sqrt(cp_bar7 / (cp_bar7 + _POW25_7))
    l50 = (lp_bar - 50) ** 2
    s_l = 1 + 0.015 * l50 / np.sqrt(20 + l50)
    s_c = 1 + 0.045 * cp_bar
    s_h = 1 + 0.015 * cp_bar * t
    r_t = -np.sin(np.radians(2 * d_theta)) * r_c
    return s_l, s_c, s_h, r_t


def _broadcast_shape(first: FloatArray, second: FloatArray) -> tuple[int, ...]:
    try:
        return np.broadcast_shapes(first.shape, second.shape)
    except ValueError as error:
        raise ValueError(
            f"Lab colours of shapes {first.shape} and {second.shape} do not broadcast"
        ) from error


def delta_e_2000(lab1: npt.ArrayLike, lab2: npt.ArrayLike) -> FloatArray:
    """CIEDE2000 difference between Lab colours, elementwise.

    `lab1` and `lab2` have shape (..., 3) and broadcast against each other; the result has
    the broadcast shape without the last axis. Raises `ValueError` on a wrong shape or a
    non-finite component.
    """
    first = _as_colours(lab1, "Lab colours")
    second = _as_colours(lab2, "Lab colours")
    if not (np.all(np.isfinite(first)) and np.all(np.isfinite(second))):
        raise ValueError("Lab components must be finite")
    shape = _broadcast_shape(first, second)
    l1, a1, b1 = _components(np.broadcast_to(first, shape))
    l2, a2, b2 = _components(np.broadcast_to(second, shape))
    return _ciede2000(l1, l2, _primed_chroma_hue(a1, b1, a2, b2)).reshape(shape[:-1])


def _ciede2000(
    l1: FloatArray, l2: FloatArray, primed: tuple[FloatArray, FloatArray, FloatArray, FloatArray]
) -> FloatArray:
    """The difference itself, from L* and the primed chroma and hue of both colours."""
    c1p, h1p, c2p, h2p = primed
    dh, hp_bar = _hue_difference_and_mean(h1p, h2p, (c1p * c2p) == 0)
    s_l, s_c, s_h, r_t = _weights((l1 + l2) / 2, (c1p + c2p) / 2, hp_bar)
    # Delta C' and delta H', each scaled by its weight (delta L' is scaled in the sum).
    dc_term = (c2p - c1p) / s_c
    dh_term = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2) / s_h
    return np.sqrt(((l2 - l1) / s_l) ** 2 + dc_term**2 + dh_term**2 + r_t * dc_term * dh_term)


def delta_e_2000_matrix(lab1: npt.ArrayLike, lab2: npt.ArrayLike) -> FloatArray:
    """CIEDE2000 between every pair: `lab1` (N, 3) against `lab2` (M, 3) gives (N, M).

    Entry [i, j] equals `delta_e_2000(lab1[i], lab2[j])`. Raises `ValueError` unless both
    inputs are 2-D with 3 columns.
    """
    first = _as_colours(lab1, "Lab colours")
    second = _as_colours(lab2, "Lab colours")
    if first.ndim != 2 or second.ndim != 2:
        raise ValueError(
            f"Lab colour lists must have shape (N, 3), got {first.shape} and {second.shape}"
        )
    return delta_e_2000(first[:, np.newaxis, :], second[np.newaxis, :, :])
