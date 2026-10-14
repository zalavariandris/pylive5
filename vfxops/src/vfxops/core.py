from typing import TypeAlias, Tuple, TYPE_CHECKING


# Type aliases
Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]
Size = Tuple[int, int]
Rect = Tuple[int, int, int, int]
Color = Tuple[float, float, float, float]  # RGBA float32 (0-1)

# Image type aliases
from typing import Annotated
if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

# Semantic type hint
ImageRGBA: TypeAlias = Annotated[
    "npt.NDArray[np.float32]",
    "shape: (height, width, 4); RGBA; straight alpha",
] # consider using jaxtyping library for runtime exceptions

if TYPE_CHECKING:
    Image_sRGB = np.ndarray   # HxWx3 RG uint8

def validate_image_data(image_data: ImageRGBA) -> None:
    """Reject data outside the pipeline contract without coercing or copying it."""
    import numpy as np
    if not isinstance(image_data, np.ndarray) or image_data.dtype != np.float32:
        raise TypeError(f"image_data must be a float32 NumPy RGBA array. got {type(image_data)} with dtype {getattr(image_data, 'dtype', None)}")
    if image_data.ndim != 3 or image_data.shape[-1] != 4 or image_data.size == 0:
        raise ValueError(f"image_data must be a nonempty (height, width, 4) RGBA array. got shape {getattr(image_data, 'shape', None)}")
