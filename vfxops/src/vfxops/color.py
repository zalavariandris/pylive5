from __future__ import annotations
from os import PathLike, fspath
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import PyOpenColorIO as ocio
from .core import ImageRGBA, validate_image_data

def grade(img:ImageRGBA, lift:float, gamma:float, gain:float) -> ImageRGBA:
    validate_image_data(img)
    return (img + lift) ** gamma * gain
