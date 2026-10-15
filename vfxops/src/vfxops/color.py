from __future__ import annotations
from os import PathLike, fspath
from typing import Annotated, TYPE_CHECKING
import numpy as np
if TYPE_CHECKING:
    import PyOpenColorIO as ocio
from .core import ImageRGBA, Range, validate_image_data


def grade(
    img: np.ndarray,
    blackpoint: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    whitepoint: Annotated[float, Range(0.0, 2.0)] = 1.0,
    lift: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    gain: Annotated[float, Range(0.0, 4.0)] = 1.0,
    multiply: Annotated[float, Range(0.0, 4.0)] = 1.0,
    offset: Annotated[float, Range(-1.0, 1.0)] = 0.0,
    gamma: Annotated[float, Range(0.01, 5.0)] = 1.0,
    reverse:bool=False,
    black_clamp:bool=True,
    white_clamp:bool=False,
    channels:str="rgb",
    mask:ImageRGBA|None=None,
    invert_mask:bool=False,
    unpremult:bool=False,
    mix: Annotated[float, Range(0.0, 1.0)] = 1.0,
):
    """
    Nuke-style Grade.

    img: float32 RGBA image, shape (H, W, 4)

    Color parameters accept a scalar or
    per-channel RGB/RGBA values.

    Range annotations suggest slider bounds for scalar editing; they do not
    restrict values supplied by callers.

    Returns a new float32 array.
    """
    validate_image_data(img)

    img = np.asarray(img)

    if img.ndim != 3 or img.shape[-1] != 4:
        raise ValueError("Expected RGBA image (H, W, 4)")

    if img.dtype != np.float32:
        raise ValueError("Expected float32 image")

    original = img
    result = img.copy()

    # Channel selection
    channel_map = {
        "r": 0,
        "g": 1,
        "b": 2,
        "a": 3,
    }

    if channels == "rgb":
        indices = [0, 1, 2]
    elif channels == "rgba":
        indices = [0, 1, 2, 3]
    else:
        indices = [channel_map[c] for c in channels]

    def param(value):
        arr = np.asarray(value, dtype=np.float32)

        if arr.ndim == 0:
            return np.full(len(indices), arr, dtype=np.float32)

        if arr.shape == (4,):
            return arr[indices]

        if arr.shape == (3,) and all(i < 3 for i in indices):
            return arr[indices]

        if arr.shape == (len(indices),):
            return arr

        raise ValueError("Invalid parameter shape")

    bp = param(blackpoint)
    wp = param(whitepoint)
    l = param(lift)
    g = param(gain)
    m = param(multiply)
    o = param(offset)
    gam = param(gamma)

    if np.any(np.abs(wp - bp) < 1e-8):
        raise ValueError("whitepoint and blackpoint must differ")

    if np.any(gam <= 0):
        raise ValueError("gamma must be positive")

    # Working pixels
    x = result[..., indices].copy()

    # Unpremultiply RGB before grading
    alpha = original[..., 3:4]

    if unpremult:
        for j, channel in enumerate(indices):
            if channel < 3:
                x[..., j] = np.divide(
                    x[..., j],
                    alpha[..., 0],
                    out=np.zeros_like(x[..., j]),
                    where=alpha[..., 0] != 0,
                )

    # Nuke Grade linear coefficients
    A = m * (g - l) / (wp - bp)
    B = o + l - A * bp

    def signed_pow(v, exponent):
        return np.sign(v) * np.power(np.abs(v), exponent)

    if reverse:
        if np.any(np.abs(A) < 1e-8):
            raise ValueError("Cannot reverse a zero-slope grade")

        x = signed_pow(x, gam)
        x = (x - B) / A
    else:
        x = A * x + B
        x = signed_pow(x, 1.0 / gam)

    # Clamping
    if black_clamp:
        x = np.maximum(x, 0.0)

    if white_clamp:
        x = np.minimum(x, 1.0)

    # Premultiply back
    if unpremult:
        for j, channel in enumerate(indices):
            if channel < 3:
                x[..., j] *= alpha[..., 0]

    # Mask
    if mask is not None:
        mask = np.asarray(mask, dtype=np.float32)

        if mask.ndim == 3:
            mask = mask[..., 3] if mask.shape[-1] == 4 else mask[..., 0]

        if mask.shape != img.shape[:2]:
            raise ValueError("Mask dimensions must match image")

        mask = np.clip(mask, 0.0, 1.0)

        if invert_mask:
            mask = 1.0 - mask

        weight = mask[..., None] * mix
    else:
        weight = mix

    # Original / graded blend
    result[..., indices] = (
        original[..., indices] * (1.0 - weight)
        + x * weight
    )

    return result
