from dataclasses import dataclass
from typing import Tuple
import math
import warnings

import numpy as np
import glm
import cv2

from .core import (
    IMAGE_DTYPE,
    Image,
    Vec2, 
    Vec3, 
    ImageRGBA,
    validate_image_data,
)

from .merge import premultiply, unpremultiply

# dataclasses
@dataclass
class Camera:
    eye: Vec3=(0,0,0)
    target: Vec3=(0,0,1)
    fov: float=math.radians(90)
    aspect: float=1.0
    near: float=1.0
    far: float=100.0
    tiltshift:Vec2=(0,0)

    def __post_init__(self) -> None:
        """normalize parameters"""
        self.eye = glm.vec3(self.eye)
        self.target = glm.vec3(self.target)
        self.tiltshift = glm.vec2(self.tiltshift)

    @property
    def projection(self) -> glm.mat4:
        aspect = self.aspect
        tiltshift = glm.vec2(self.tiltshift)/self.near
        projection = glm.frustum(-1*aspect, 1*aspect, -1+tiltshift.y, 1+tiltshift.y, self.near, self.far) # left right, bottom, top, near, far
        return projection

    @property
    def view(self) -> glm.mat4:
        return glm.lookAt(self.eye, self.target, (0,1,0))


# transform
def crop_to_size(img: Image, size:Tuple[int,int], pivot:Tuple[float, float]=(0.5,0.5)) -> Image:
    """Crop image to specified size
    
    Parameters
    ----------
    size:tuple[int,int]
        size defined in absolute pixels
    pivot: tuple[int,int]
        pivot point of crop rectangle defined in relative coordinates. (0,0) is top left corner and (1,1) is bottom right corner"""
    
    validate_image_data(img, channels=None)
    x1 = img.shape[2]*pivot[0]-size[0]/2
    x2 = x1 + size[0]
    y1 = img.shape[1]*pivot[1]-size[1]/2
    y2 = y1+size[1]

    x1, x2, y1, y2 = int(x1), int(x2), int(y1), int(y2)
    img = img[:, y1:y2, x1:x2]
    return img

def crop_to_rect(img: Image, x1:int, x2:int, y1:int, y2:int) -> Image:
    """Crop image to rectangle
    
    Parameters
    ----------
    rectangle defined in pixels.
    x1:int
        left edge of rectangle
    x2:int
        right edge of rectangle
    y1:int
        bottom edge of rectangle
    y2:int
        top edge of rectangle"""

    validate_image_data(img, channels=None)
    return img[:, y1:y2, x1:x2]

def transform(img: Image, translate: Vec2=(0,0), scale: Vec2=(1,1), pivot: Vec2=(0.5, 0.5)) -> Image:
    """Apply an affine transform independently to each float32 channel plane."""
    validate_image_data(img, channels=None)
    # 1. Calculate dimensions based on scale
    width = img.shape[2] * scale[0]
    height = img.shape[1] * scale[1]

    # 2. Calculate pivot-based offset AND add translation
    # The pivot logic finds the "anchor," and translate moves it from there.
    x = (img.shape[2] - width) * pivot[0] + translate[0]
    y = (img.shape[1] - height) * pivot[1] + translate[1]

    # 3. Precision Check
    # Using float32 epsilon is generally safer for CV2 operations
    e = np.finfo(IMAGE_DTYPE).eps
    if (scale[0] <= e or scale[1] <= e):
        return np.zeros(img.shape, dtype=IMAGE_DTYPE)

    # 4. Construct the Affine Matrix
    # M = [ [sx, 0, tx], [0, sy, ty] ]
    M = np.array([
        [scale[0], 0, x],
        [0, scale[1], y]
    ], dtype=IMAGE_DTYPE)

    # 5. Warp
    result = np.empty(img.shape, dtype=IMAGE_DTYPE)
    for channel in range(img.shape[0]):
        cv2.warpAffine(img[channel], M, (img.shape[2], img.shape[1]), dst=result[channel])
    return result
    
def card3D(img: Image, translate:Vec3=(0,0,0), rotate:Vec3=(0,0,0), scale:Vec3=(1,1,1), camera: Camera=Camera(fov=math.radians(90), eye=(0,0,0), target=(0,0,1))) -> ImageRGBA:
    """
    Apply 3D perspective transform to an image.
    
    Input is planar RGB or RGBA float32. RGB gets an opaque alpha plane.
    Output is always planar RGBA float32.
    
    @fov: field of view in radians
    """
    validate_image_data(img, channels=(3, 4))
    channels, height, width = img.shape

    """ Create MVP matrix """
    # projection
    # near = 1.0
    # far = 100.0

    
    # aspect = width/height
    # tiltshift = glm.vec2(tiltshift)/near
    # eye = glm.vec3(eye)
    # projection = glm.frustum(-1*aspect, 1*aspect, -1+tiltshift.y, 1+tiltshift.y, near, far) # left right, bottom, top, near, far
    # tilt_shift = glm.vec2(0,0)
    # projection = glm.perspective(fov, width/height, 1.0, 100.0)
    # view = glm.lookAt(eye, eye+(0, 0,100), (0,1,0))
    model = glm.translate(glm.mat4(), translate)
    MVP = camera.projection * camera.view * model

    """Project corners"""
    # normalize image corner positions
    src_pts = np.array([(0,0), (width, 0), (width, height), (0, height)], dtype=IMAGE_DTYPE)
    center = np.array((width / 2, height / 2), dtype=IMAGE_DTYPE)
    position = (src_pts - center) / np.float32(max(width, height))
    position = [glm.vec4(pos[0], pos[1], 0, 1) for pos in position]

    # project vertices
    projected = [MVP*pos for pos in position] # viewspace
    projected = [proj/proj.w for proj in projected] # NDC space
    projected = [(vec.xy+(0.5, 0.5))*(width, height) for vec in projected] # screenspace
    
    dst_pts = np.array([vec.xy for vec in projected], dtype=IMAGE_DTYPE) # keep 2d coords

    """Calculate perspective transform"""
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)

    """Warp image"""
    # make sure the image has an alpha channel and is float32
    if channels == 3:
        warnings.warn("Input image has no alpha channel, adding opaque alpha channel.")
        rgba = np.ones((4, height, width), dtype=IMAGE_DTYPE)
        rgba[:3] = img
        img = rgba

    # Convert to premultiplied alpha before warping to avoid color bleeding at edges
    # This prevents interpolation from introducing incorrect colors at semi-transparent edges
    img_premult = premultiply(img)
    
    # Warp with premultiplied alpha - edges will correctly interpolate to (0,0,0,0)
    result_premult = np.empty(img_premult.shape, dtype=IMAGE_DTYPE)
    for channel in range(4):
        cv2.warpPerspective(
            img_premult[channel], M, (width, height),
            dst=result_premult[channel], borderValue=0,
        )
    
    # Convert back to straight alpha
    result = unpremultiply(result_premult)
    return result

def reformat(img: Image, size: Tuple[int,int], interpolation: int=cv2.INTER_LINEAR) -> Image:
    """Resize every channel plane; size is (width, height)."""
    validate_image_data(img, channels=None)
    width, height = size
    result = np.empty((img.shape[0], height, width), dtype=IMAGE_DTYPE)
    for channel in range(img.shape[0]):
        cv2.resize(img[channel], size, dst=result[channel], interpolation=interpolation)
    return result
