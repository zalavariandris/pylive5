from dataclasses import dataclass
from typing import Annotated, Final, TypeAlias, Tuple

import numpy as np
import numpy.typing as npt


IMAGE_DTYPE: Final = np.dtype(np.float32)
Image: TypeAlias = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Range:
    """Suggested inspector bounds, not validation of function arguments.

    Step is the largest spacing between adjacent slider positions. Editors may
    use a slightly smaller spacing so both endpoints are reachable.
    """

    minimum: float
    maximum: float
    step: float = 0.01


# Type aliases
Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]
Size = Tuple[int, int]
Rect = Tuple[int, int, int, int]
Color = Tuple[float, float, float, float]  # RGBA, including HDR values

# Images use channel-first (C, H, W) indexing. New buffers are C-contiguous;
# crops may be strided views into the original channel planes.
ImageRGBA: TypeAlias = Annotated[
    Image,
    "shape: (4, height, width); planar RGBA; straight alpha",
]

Image_sRGB: TypeAlias = Annotated[
    npt.NDArray[np.uint8],
    "shape: (3, height, width); planar RGB; sRGB",
]


def validate_image_data(
    image_data: Image,
    *,
    channels: int | tuple[int, ...] | None = 4,
) -> None:
    """Reject data outside the pipeline contract without coercing or copying it."""
    if not isinstance(image_data, np.ndarray) or image_data.dtype != IMAGE_DTYPE:
        raise TypeError(
            "image_data must be a float32 NumPy array; "
            f"got {type(image_data)} with dtype {getattr(image_data, 'dtype', None)}"
        )
    if image_data.ndim != 3 or image_data.size == 0:
        raise ValueError(
            "image_data must have nonempty planar shape (channels, height, width); "
            f"got {image_data.shape}"
        )
    allowed = (channels,) if isinstance(channels, int) else channels
    if allowed is not None and image_data.shape[0] not in allowed:
        raise ValueError(
            f"Expected {allowed} channels on axis 0 of a planar image; "
            f"got shape {image_data.shape}"
        )


def from_interleaved(image_data: Image) -> Image:
    """Pack a float32 (H, W, C) image into contiguous (C, H, W) storage.

    This changes layout only; integer normalization and color conversion belong
    to the caller's I/O adapter.
    """
    planar = np.moveaxis(image_data, -1, 0)
    validate_image_data(planar, channels=None)
    return np.ascontiguousarray(planar)


def to_interleaved(image_data: Image) -> Image:
    """Pack a planar float32 image for a library that requires (H, W, C)."""
    validate_image_data(image_data, channels=None)
    return np.ascontiguousarray(np.moveaxis(image_data, 0, -1))
