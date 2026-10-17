# IO
from pathlib import Path
from typing import Union

import cv2
import av
import numpy as np


from vfxops.core import ImageRGBA

def read_image(path: Path) -> ImageRGBA:
    """Read image as RGBA float32.
    Preserve HDR values for EXR."""
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")

    with av.open(str(path)) as container:
        frame = next(container.decode(video=0), None)

        if frame is None:
            raise ValueError(f"Failed to read image: {path}")

        fmt = frame.format.name

        # Float EXR: preserve native values and precision
        if fmt.startswith(("gbrpf32", "gbrapf32")):
            img = frame.to_ndarray()

        elif fmt.startswith("grayf32"):
            img = frame.to_ndarray()[..., None]

        # 16-bit integer formats
        elif (
            fmt.startswith(("rgb48", "bgr48", "rgba64", "bgra64"))
            or fmt.startswith(("gray16", "gbrp16", "gbrap16"))
        ):
            img = frame.to_ndarray(format="rgba64le")
            img = img.astype(np.float32) / 65535.0
            return img

        # Standard 8-bit images
        else:
            img = frame.to_ndarray(format="rgba")
            return img.astype(np.float32) / 255.0

    # Float images: add opaque alpha if missing
    if img.ndim == 2:
        img = img[..., None]

    if img.shape[-1] == 1:
        img = np.repeat(img, 3, axis=-1)

    if img.shape[-1] == 3:
        alpha = np.ones((*img.shape[:2], 1), dtype=np.float32)
        img = np.concatenate((img, alpha), axis=-1)

    return img.astype(np.float32, copy=False)

# from vfxops.core import ImageRGBA, Image_sRGB
# def to_sRGB(img: ImageRGBA) -> Image_sRGB:
#     """Convert RGBA float32 (0-1) to RGB uint8 (0-255)."""
#     return cv2.convertScaleAbs(img*255).astype(np.uint8)[:,:,:3]

def encode_jpg(image: ImageRGBA, quality:int=75) -> bytes:
    # clip to [0, 1] and convert to 8-bit integers
    # clip to [0, 1] and convert to 8-bit integers
    image = np.clip(image, 0, 1)
    rgba = np.rint(np.clip(image, 0, 1) * 255).astype(np.uint8)
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)

    extension = ".jpg"
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    _, buffer = cv2.imencode(extension, bgra, params)
    image_bytes = buffer.tobytes()
    return image_bytes

def encode_png(image: ImageRGBA) -> bytes:
    """Encode one input as an in-memory PNG upload."""
    import numpy as np
    import cv2

    # clip to [0, 1] and convert to 8-bit integers
    image = np.clip(image, 0, 1)
    rgba = np.rint(np.clip(image, 0, 1) * 255).astype(np.uint8)
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)

    #
    extension = ".png"
    success, encoded = cv2.imencode(extension, bgra)
    if not success:
        raise RuntimeError(f"Could not encode as PNG.")
    
    image_bytes = encoded.tobytes()
    return image_bytes