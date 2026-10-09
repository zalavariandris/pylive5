from dataclasses import dataclass
import math
import numpy as np

from .core import (
    ImageRGBA, 
    Color, 
    Vec2, 
    Size, 
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

def gradient(size:Size, direction:Vec2=(1,0), color_start:Color=(0,0,0,1), color_end:Color=(1,1,1,1)) -> ImageRGBA:
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
