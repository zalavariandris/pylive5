from typing import Annotated
import numpy as np
from .core import ImageRGBA, Range, validate_image_data


def exposure(img: ImageRGBA, ev:Annotated[float, Range(-10.0, 10.0)]=0.0) -> ImageRGBA:
    """Adjust planar RGB exposure, preserving alpha and the input."""
    validate_image_data(img)
    result = img.copy(order="C")
    result[:3] *= np.float32(2.0 ** ev)
    return result


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
    scale = np.float32(multiply * (gain - lift) / input_range)
    bias = np.float32(offset + lift - scale * blackpoint)

    result = img.copy(order="C")
    rgb = result[:3]

    # Preserve the sign when applying gamma to negative values.
    if reverse:
        if abs(scale) < 1e-8:
            raise ValueError("Cannot reverse a zero-slope grade")

        if gamma != 1.0:
            rgb[:] = np.sign(rgb) * np.power(np.abs(rgb), np.float32(gamma))
        rgb -= bias
        rgb /= scale
    else:
        rgb *= scale
        rgb += bias
        if gamma != 1.0:
            rgb[:] = np.sign(rgb) * np.power(np.abs(rgb), np.float32(1.0 / gamma))

    if black_clamp:
        np.maximum(rgb, 0.0, out=rgb)

    if white_clamp:
        np.minimum(rgb, 1.0, out=rgb)

    return result
