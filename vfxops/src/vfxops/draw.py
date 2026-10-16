import math

import numpy as np
from numba import njit

from .core import IMAGE_DTYPE, Color, ImageRGBA, Size, Vec2


def checkerboard(
    size: Size,
    square_size: int = 32,
    color: Color = (1.0, 1.0, 1.0, 1.0),
) -> ImageRGBA:
    """Create a planar RGBA checkerboard; size is (width, height)."""
    if square_size <= 0:
        raise ValueError("square_size must be positive")
    width, height = size
    board = np.zeros((4, height, width), dtype=IMAGE_DTYPE)
    rgba = np.asarray(color, dtype=IMAGE_DTYPE)[:, None, None]
    for y in range(0, height, square_size):
        for x in range(0, width, square_size):
            if (x // square_size + y // square_size) % 2 == 0:
                board[:, y:y + square_size, x:x + square_size] = rgba
    return board


def constant(size: Size, color: Color = (1.0, 1.0, 1.0, 1.0)) -> ImageRGBA:
    """Create a constant planar RGBA image; size is (width, height)."""
    width, height = size
    image = np.empty((4, height, width), dtype=IMAGE_DTYPE)
    image[:] = np.asarray(color, dtype=IMAGE_DTYPE)[:, None, None]
    return image


def gradient_naive(
    size: Size,
    direction: Vec2 = (1, 0),
    color_start: Color = (0, 0, 0, 1),
    color_end: Color = (1, 1, 1, 1),
) -> ImageRGBA:
    """Reference implementation of a planar RGBA linear gradient."""
    width, height = size
    dir_x, dir_y = direction
    length = math.hypot(dir_x, dir_y)
    if length == 0:
        raise ValueError("Direction vector cannot be zero")
    dir_x, dir_y = dir_x / length, dir_y / length
    denominator = width * abs(dir_x) + height * abs(dir_y)
    image = np.empty((4, height, width), dtype=IMAGE_DTYPE)
    for channel in range(4):
        for y in range(height):
            for x in range(width):
                t = min(1.0, max(0.0, (x * dir_x + y * dir_y) / denominator))
                image[channel, y, x] = (1.0 - t) * color_start[channel] + t * color_end[channel]
    return image


def gradient(
    size: Size,
    direction: Vec2 = (1, 0),
    color_start: Color = (0, 0, 0, 1),
    color_end: Color = (1, 1, 1, 1),
) -> ImageRGBA:
    """Create a planar RGBA gradient without materializing coordinate grids."""
    width, height = size
    dir_x, dir_y = direction
    length = math.hypot(dir_x, dir_y)
    if length == 0:
        raise ValueError("Direction vector cannot be zero")
    dir_x, dir_y = dir_x / length, dir_y / length
    denominator = np.float32(width * abs(dir_x) + height * abs(dir_y))
    x = np.arange(width, dtype=IMAGE_DTYPE)[None, :] * np.float32(dir_x)
    y = np.arange(height, dtype=IMAGE_DTYPE)[:, None] * np.float32(dir_y)
    t = (x + y) / denominator
    np.clip(t, 0.0, 1.0, out=t)

    start = np.asarray(color_start, dtype=IMAGE_DTYPE)[:, None, None]
    end = np.asarray(color_end, dtype=IMAGE_DTYPE)[:, None, None]
    return (1.0 - t) * start + t * end


def noise(size: Size) -> ImageRGBA:
    """Create planar Gaussian RGB noise with opaque alpha."""
    width, height = size
    image = np.empty((4, height, width), dtype=IMAGE_DTYPE)
    np.random.default_rng().standard_normal(
        (3, height, width), dtype=IMAGE_DTYPE, out=image[:3],
    )
    image[:3] *= np.float32(0.01)
    image[3] = 1.0
    return image


@njit(nogil=True)
def _gradient_numba(
    width: int,
    height: int,
    dir_x: float,
    dir_y: float,
    color_start: Color,
    color_end: Color,
) -> ImageRGBA:
    length = math.sqrt(dir_x * dir_x + dir_y * dir_y)
    if length == 0.0:
        raise ValueError("Direction vector cannot be zero")
    dir_x /= length
    dir_y /= length
    denominator = width * abs(dir_x) + height * abs(dir_y)
    image = np.empty((4, height, width), dtype=IMAGE_DTYPE)
    for channel in range(4):
        for y in range(height):
            for x in range(width):
                t = min(1.0, max(0.0, (x * dir_x + y * dir_y) / denominator))
                image[channel, y, x] = (1.0 - t) * color_start[channel] + t * color_end[channel]
    return image


def gradient_numba(
    size: Size,
    direction: Vec2 = (1, 0),
    color_start: Color = (0, 0, 0, 1),
    color_end: Color = (1, 1, 1, 1),
) -> ImageRGBA:
    """Create the same planar gradient using a compiled channel-major loop."""
    width, height = size
    # Homogeneous tuples allow Numba to index colors inside the channel loop.
    start = tuple(float(value) for value in color_start)
    end = tuple(float(value) for value in color_end)
    return _gradient_numba(width, height, float(direction[0]), float(direction[1]), start, end)
