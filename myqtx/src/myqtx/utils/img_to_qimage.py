import numpy as np
from qtpy.QtGui import QImage, QPixmap

def img_to_qimage(data: np.ndarray | QImage | QPixmap) -> QImage:
    if isinstance(data, QImage):
        return data.copy()
    if isinstance(data, QPixmap):
        return data.toImage().copy()
    if not isinstance(data, np.ndarray):
        raise TypeError("Image data must be a NumPy array, QImage, or QPixmap")
    if data.ndim == 2:
        channels = 1
    elif data.ndim == 3 and data.shape[2] in (1, 3, 4):
        channels = data.shape[2]
    else:
        raise ValueError(
            "Expected an image with shape (H, W), (H, W, 1), (H, W, 3), or (H, W, 4)"
        )
    if data.shape[0] == 0 or data.shape[1] == 0:
        raise ValueError("Image dimensions must be positive")
    if data.dtype in (np.dtype(np.float32), np.dtype(np.float64)):
        data = (np.clip(data, 0.0, 1.0) * 255).astype(np.uint8)
    elif data.dtype != np.uint8:
        raise TypeError("Image dtype must be uint8, float32, or float64")
    data = np.ascontiguousarray(data)
    image_format = {
        1: QImage.Format.Format_Grayscale8,
        3: QImage.Format.Format_RGB888,
        4: QImage.Format.Format_RGBA8888,
    }[channels]
    # The caller may modify or release its array after display() returns.
    return QImage(
        data.data, data.shape[1], data.shape[0], data.strides[0], image_format,
    ).copy()
