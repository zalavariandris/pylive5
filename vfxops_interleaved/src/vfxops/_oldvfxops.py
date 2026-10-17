from typing import TypeAlias, Union, Tuple
from dataclasses import dataclass
from pathlib import Path
import math
import warnings

import numpy as np
import cv2
import glm


# Type aliases
from .core import (
    Vec3, 
    Vec2, 
    Size, 
    Rect, 
    Color, 
    ImageRGBA, 
    Image_sRGB, 
    validate_image_data
)

