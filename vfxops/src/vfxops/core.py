
from typing import Tuple
import math
from dataclasses import dataclass

import numpy as np
import cv2


# Type aliases
Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]
Size = Tuple[int, int]
Rect = Tuple[int, int, int, int]

# Image type aliases
from typing import Annotated
import numpy as np
import numpy.typing as npt

# Semantic type hint
ImageRGBA = Annotated[npt.NDArray[np.float32], "(H, W, 4)"] # consider using jaxtyping library for runtime exceptions
Color = Tuple[float, float, float, float]  # RGBA float32 (0-1)
Image_sRGB = np.ndarray   # HxWx3 RG uint8
