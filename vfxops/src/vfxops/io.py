# IO
from pathlib import Path
from typing import Union
import cv2
import numpy as np
from .core import (
    ImageRGBA, 
    Image_sRGB
)


def read_image(path:Union[str, Path]) -> ImageRGBA:
    """Read image from disk as RGBA float32 (0-1)"""
    if not Path(path).exists():
        raise FileNotFoundError(f"File does not exist: {path}")

    img_bgr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img_bgr is None:
        raise Exception(f"Failed to read image from path: {path}")

    nr_of_channels = img_bgr.shape[2]

    match nr_of_channels:
        case 1:
            # grayscale to BGRA
            img = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2RGBA)
            return img.astype(np.float32) / 255.0
        
        case 3:
            # BGR to BGRA
            img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
            return img.astype(np.float32) / 255.0
        
        case 4:
            rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGBA)
            return rgba.astype(np.float32) / 255.0
        
        case _:
            raise Exception(f"Unsupported number of channels: {nr_of_channels} in image: {path}")

def to_sRGB(img: ImageRGBA) -> Image_sRGB:
    """Convert RGBA float32 (0-1) to RGB uint8 (0-255)."""
    return cv2.convertScaleAbs(img*255).astype(np.uint8)[:,:,:3]

# image
def encode_jpg(img: ImageRGBA, quality:int=75) -> bytes:
    extension = ".jpg"
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    _, buffer = cv2.imencode(extension, to_sRGB(img), params)
    return buffer.tobytes()

