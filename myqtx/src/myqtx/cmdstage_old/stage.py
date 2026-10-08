"""Compatibility imports; new code can use from cmdstage import Stage."""

import numpy as np

from myqtx.cmdstage import Image, Stage


class SharedImageViewer(Stage):
    """Preserve the original RGB NumPy/Pillow input API."""

    def show(self, image: object) -> None:
        rgb = np.ascontiguousarray(np.asarray(image, dtype=np.uint8))
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("Expected an H x W x 3 RGB uint8 image")
        super().show(Image(rgb))

__all__ = ["Stage", "SharedImageViewer"]
