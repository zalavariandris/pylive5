from .core import (
    Vec2,
    Size, 
    Color, 
    ImageRGBA
)

# draw
def checkerboard(size:Size, square_size:int=32, color:Color=(1.0, 1.0, 1.0, 1.0)) -> ImageRGBA:
    """create an RGBA checkerboard image of given size"""
    width, height = size
    rows = math.ceil(height/square_size)
    cols = math.ceil(width/square_size)

    board = np.zeros( (rows*square_size, cols*square_size, 4), dtype=np.float32 )
    for y in range(rows):
        for x in range(cols):
            if (x+y)%2 == 0:
                board[y*square_size:(y+1)*square_size, x*square_size:(x+1)*square_size] = color
    # return an RGBA image cropped to the requested size
    return board[:height, :width]

def constant(size:Size, color:Color=(1.0, 1.0, 1.0, 1.0)) -> ImageRGBA:
    """create an RGBA constant color image of given size"""
    width, height = size
    img = np.zeros( (height, width, 4), dtype=np.float32 )
    img[:,:,:] = color
    return img

def gradient_naive(size:Size, direction:Vec2=(1,0), color_start:Color=(0,0,0,1), color_end:Color=(1,1,1,1)) -> ImageRGBA:
    """create an RGBA gradient image of given size"""
    width, height = size
    dir_x, dir_y = direction
    length = math.sqrt(dir_x**2 + dir_y**2)
    if length == 0:
        raise ValueError("Direction vector cannot be zero.")
    dir_x /= length
    dir_y /= length

    img = np.zeros( (height, width, 4), dtype=np.float32 )
    for y in range(height):
        for x in range(width):
            t = (x * dir_x + y * dir_y) / (width * abs(dir_x) + height * abs(dir_y))
            t = np.clip(t, 0.0, 1.0)
            img[y,x,:] = [
                (1-t)*color_start[0] + t*color_end[0],
                (1-t)*color_start[1] + t*color_end[1],
                (1-t)*color_start[2] + t*color_end[2],
                (1-t)*color_start[3] + t*color_end[3],
            ]
    return img

def gradient(size: Size, direction: Vec2 = (1, 0), color_start: Color = (0, 0, 0, 1), color_end: Color = (1, 1, 1, 1)) -> ImageRGBA:
    """create an RGBA gradient image of given size"""
    width, height = size
    dir_x, dir_y = direction
    length = math.sqrt(dir_x**2 + dir_y**2)
    if length == 0:
        raise ValueError("Direction vector cannot be zero.")
    dir_x /= length
    dir_y /= length

    # Create coordinate grids
    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)  # shape: (height, width)

    # Project onto the direction vector and normalize to [0, 1]
    denom = width * abs(dir_x) + height * abs(dir_y)
    t = (xx * dir_x + yy * dir_y) / denom
    t = np.clip(t, 0.0, 1.0)  # shape: (height, width)

    # Linear interpolation between colors (broadcast over channels)
    color_start = np.asarray(color_start, dtype=np.float32)
    color_end = np.asarray(color_end, dtype=np.float32)
    img = (1 - t[..., None]) * color_start + t[..., None] * color_end

    return img

import math
import numpy as np
from numba import njit

@njit(nogil=True)
def _gradient_numba(width, height, dir_x, dir_y, cs0, cs1, cs2, cs3, ce0, ce1, ce2, ce3):
    length = math.sqrt(dir_x * dir_x + dir_y * dir_y)
    if length == 0.0:
        raise ValueError("Direction vector cannot be zero.")
    dir_x /= length
    dir_y /= length

    denom = width * abs(dir_x) + height * abs(dir_y)
    if denom == 0.0:
        denom = 1.0

    img = np.empty((height, width, 4), dtype=np.float32)

    for y in range(height):
        for x in range(width):
            proj = x * dir_x + y * dir_y
            t = proj / denom
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            inv_t = 1.0 - t
            img[y, x, 0] = inv_t * cs0 + t * ce0
            img[y, x, 1] = inv_t * cs1 + t * ce1
            img[y, x, 2] = inv_t * cs2 + t * ce2
            img[y, x, 3] = inv_t * cs3 + t * ce3

    return img

def gradient_numba(size: Size, direction: Vec2 = (1, 0), color_start: Color = (0, 0, 0, 1), color_end: Color = (1, 1, 1, 1)) -> ImageRGBA:
    width, height = size
    return _gradient_numba(
        width, height,
        direction[0], direction[1],
        color_start[0], color_start[1], color_start[2], color_start[3],
        color_end[0], color_end[1], color_end[2], color_end[3]
    )
