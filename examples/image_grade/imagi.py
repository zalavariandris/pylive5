
import numpy as np
import pathlib
from dataclasses import dataclass

@dataclass(frozen=True)
class ColorData:
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    a: float = 1.0

@dataclass
class ImageRGBA:
    data: np.ndarray

def constant(width: int=512, height: int=512, color: ColorData=ColorData(0.5, 0.5, 0.5))->ImageRGBA:
    return ImageRGBA(np.full((height, width, 4), [color.r, color.g, color.b, color.a], dtype=np.float32))

def read(path: pathlib.Path)->ImageRGBA:
    return ImageRGBA(np.zeros((1, 1, 4), dtype=np.float32))

def cornerpin(img: ImageRGBA)->ImageRGBA:
    return img

def exposure(img: ImageRGBA, factor: float=0.0)->ImageRGBA:
    return img

def temperature(img: ImageRGBA, value: float=0.0)->ImageRGBA:
    return img

def img_to_np(img: ImageRGBA) -> np.ndarray:
    return img.data

def merge(fg: ImageRGBA, bg: ImageRGBA) -> ImageRGBA:
    return fg+bg

__all__ = [
    "constant",
    "read",
    "cornerpin",
    "exposure",
    "temperature",
    "img_to_np",
    "merge"
]
