from os import PathLike, fspath
from typing import Annotated, TYPE_CHECKING
import numpy as np
if TYPE_CHECKING:
    import PyOpenColorIO as ocio
from .core import ImageRGBA, Range, validate_image_data


def exposure(img: ImageRGBA, ev:Annotated[float, Range(-10.0, 10.0)]=0.0):
    factor = 2.0 ** ev
    scale = np.asarray((factor, factor, factor, 1.0), dtype=img.dtype) # keep it float32
    return img * scale


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
