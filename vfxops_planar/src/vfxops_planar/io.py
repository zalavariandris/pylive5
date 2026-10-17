from pathlib import Path

import av
import cv2
import numpy as np
import numpy.typing as npt

from .core import IMAGE_DTYPE, ImageRGBA, validate_image_data


def _frame_to_rgba(frame: av.VideoFrame) -> ImageRGBA:
    """Decode a PyAV frame into contiguous float32 (4, H, W) RGBA."""
    fmt = frame.format.name
    if fmt.startswith(("gbrpf32", "gbrapf32", "grayf32", "gbrpf16", "gbrapf16", "grayf16")):
        # PyAV exposes RGB float formats as HWC, despite FFmpeg's planar storage.
        pixels = frame.to_ndarray()
        divisor = np.float32(1.0)
    elif any(component.bits > 8 for component in frame.format.components):
        pixels = frame.to_ndarray(format="rgba64le")
        divisor = np.float32(65535.0)
    else:
        pixels = frame.to_ndarray(format="rgba")
        divisor = np.float32(255.0)

    height, width = pixels.shape[:2]
    result = np.ones((4, height, width), dtype=IMAGE_DTYPE)
    if pixels.ndim == 2:
        result[:3] = pixels
    elif pixels.shape[2] == 1:
        result[:3] = pixels[..., 0]
    elif pixels.shape[2] in (3, 4):
        result[:pixels.shape[2]] = np.moveaxis(pixels, -1, 0)
    else:
        raise ValueError(f"Unsupported decoded image shape: {pixels.shape}")

    if divisor != 1.0:
        # Integer formats above are decoded as RGBA, including integer alpha.
        result /= divisor
    return result


def read_image(path: Path) -> ImageRGBA:
    """Read planar RGBA float32, preserving HDR values in floating-point images."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")

    with av.open(str(path)) as container:
        frame = next(container.decode(video=0), None)
        if frame is None:
            raise ValueError(f"Failed to read image: {path}")
        return _frame_to_rgba(frame)


def _packed_rgba8(image: ImageRGBA) -> npt.NDArray[np.uint8]:
    """Quantize and pack only at the image encoder boundary."""
    validate_image_data(image)
    pixels = np.clip(image, 0.0, 1.0)
    pixels *= np.float32(255.0)
    np.rint(pixels, out=pixels)
    return np.ascontiguousarray(np.moveaxis(pixels.astype(np.uint8), 0, -1))


def encode_jpg(image: ImageRGBA, quality: int = 75) -> bytes:
    """Encode planar RGBA as JPEG, discarding alpha."""
    bgr = cv2.cvtColor(_packed_rgba8(image), cv2.COLOR_RGBA2BGR)
    success, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise RuntimeError("Could not encode as JPEG")
    return encoded.tobytes()


def encode_png(image: ImageRGBA) -> bytes:
    """Encode planar RGBA as PNG, preserving alpha."""
    bgra = cv2.cvtColor(_packed_rgba8(image), cv2.COLOR_RGBA2BGRA)
    success, encoded = cv2.imencode(".png", bgra)
    if not success:
        raise RuntimeError("Could not encode as PNG")
    return encoded.tobytes()
