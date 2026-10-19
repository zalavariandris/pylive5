from os import PathLike, fspath
from typing import Annotated, TYPE_CHECKING
from numba import njit
import numpy as np
if TYPE_CHECKING:
    import PyOpenColorIO as ocio
from .core import ImageRGBA, Range, validate_image_data


def exposure(img, ev:Annotated[float, Range(-10.0, 10.0)]=0.0):
    factor = 2.0 ** ev
    return img * np.array([factor, factor, factor, 1.0], dtype=np.float32)

# @njit(nogil=True)
def grade_naive(
    img: ImageRGBA,
    blackpoint: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    whitepoint: Annotated[float, Range(0.0, 2.0)] = 1.0,
    lift: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    gain: Annotated[float, Range(0.0, 4.0)] = 1.0,
    multiply: Annotated[float, Range(0.0, 4.0)] = 1.0,
    offset: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    gamma: Annotated[float, Range(0.01, 5.0)] = 1.0,
    reverse: bool = False,
    black_clamp: bool = True,
    white_clamp: bool = False,
) -> ImageRGBA:
    """Grade RGB with scalar controls, preserving alpha and the input array."""
    validate_image_data(img)

    input_range = whitepoint - blackpoint
    if abs(input_range) < 1e-8:
        raise ValueError("whitepoint and blackpoint must differ")

    if gamma <= 0:
        raise ValueError("gamma must be positive")

    # Combine the linear controls into: rgb * scale + bias.
    scale = multiply * (gain - lift) / input_range
    bias = offset + lift - scale * blackpoint

    rgb = img[..., :3]

    # Preserve the sign when applying gamma to negative values.
    if reverse:
        if abs(scale) < 1e-8:
            raise ValueError("Cannot reverse a zero-slope grade")

        rgb = np.sign(rgb) * np.power(np.abs(rgb), gamma)
        rgb = (rgb - bias) / scale
    else:
        rgb = rgb * scale + bias
        rgb = np.sign(rgb) * np.power(np.abs(rgb), 1.0 / gamma)

    if black_clamp:
        rgb = np.maximum(rgb, 0.0)

    if white_clamp:
        rgb = np.minimum(rgb, 1.0)

    result = img.copy()
    result[..., :3] = rgb
    return result

import numpy as np
from numba import njit, prange


@njit(parallel=True, cache=True)
def _grade_kernel(
    img, out, scale, bias, power,
    reverse, black_clamp, white_clamp
):
    h, w, _ = img.shape
    use_gamma = power != 1.0

    for y in prange(h):
        for x in range(w):
            for c in range(3):
                v = img[y, x, c]

                if reverse:
                    if use_gamma:
                        v = np.copysign(abs(v) ** power, v)
                    v = (v - bias) / scale
                else:
                    v = v * scale + bias
                    if use_gamma:
                        v = np.copysign(abs(v) ** power, v)

                if black_clamp:
                    v = max(v, 0.0)

                if white_clamp:
                    v = min(v, 1.0)

                out[y, x, c] = v

            out[y, x, 3] = img[y, x, 3]


def grade(
    img: ImageRGBA,
    blackpoint: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    whitepoint: Annotated[float, Range(0.0, 2.0)] = 1.0,
    lift: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    gain: Annotated[float, Range(0.0, 4.0)] = 1.0,
    multiply: Annotated[float, Range(0.0, 4.0)] = 1.0,
    offset: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    gamma: Annotated[float, Range(0.01, 5.0)] = 1.0,
    reverse: bool = False,
    black_clamp: bool = True,
    white_clamp: bool = False,
) -> ImageRGBA:
    """Grade RGB with Numba, preserving alpha and input."""

    # validate_image_data(img)

    input_range = whitepoint - blackpoint
    if abs(input_range) < 1e-8:
        raise ValueError("whitepoint and blackpoint must differ")

    if gamma <= 0:
        raise ValueError("gamma must be positive")

    scale = multiply * (gain - lift) / input_range
    bias = offset + lift - scale * blackpoint

    if reverse and abs(scale) < 1e-8:
        raise ValueError("Cannot reverse a zero-slope grade")

    power = gamma if reverse else 1.0 / gamma

    out = np.empty_like(img)

    _grade_kernel(
        img,
        out,
        np.float32(scale),
        np.float32(bias),
        np.float32(power),
        reverse,
        black_clamp,
        white_clamp,
    )

    return out