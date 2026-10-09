from dataclasses import dataclass
from typing import Tuple
import math
import warnings
import glm
import numpy as np
import cv2


from .core import (
    ImageRGBA,
    Vec2,
    Vec3,
)

from .filter import premultiply_alpha, unpremultiply_alpha


@dataclass
class Camera:
    eye: Vec3=(0,0,0)
    target: Vec3=(0,0,1)
    fov: float=math.radians(90)
    aspect: float=1.0
    near: float=1.0
    far: float=100.0
    tiltshift:Vec2=(0,0)

    def __post_init__(self):
        """normalize parameters"""
        self.eye = glm.vec3(self.eye)
        self.target = glm.vec3(self.target)
        self.tiltshift = glm.vec2(self.tiltshift)

    @property
    def projection(self):
        aspect = self.aspect
        tiltshift = glm.vec2(self.tiltshift)/self.near
        projection = glm.frustum(-1*aspect, 1*aspect, -1+tiltshift.y, 1+tiltshift.y, self.near, self.far) # left right, bottom, top, near, far
        return projection

    @property
    def view(self):
        return glm.lookAt(self.eye, self.target, (0,1,0))

# transform
def crop_to_size(img: ImageRGBA, size:Tuple[int,int], pivot:Tuple[float, float]=(0.5,0.5)) -> ImageRGBA:
    """Crop image to specified size
    
    Parameters
    ----------
    size:tuple[int,int]
        size defined in absolute pixels
    pivot: tuple[int,int]
        pivot point of crop rectangle defined in relative coordinates. (0,0) is top left corner and (1,1) is bottom right corner"""
    
    x1 = img.shape[1]*pivot[0]-size[0]/2
    x2 = x1 + size[0]
    y1 = img.shape[0]*pivot[1]-size[1]/2
    y2 = y1+size[1]

    x1, x2, y1, y2 = int(x1), int(x2), int(y1), int(y2)
    img = img[y1:y2, x1:x2]
    return img

def crop_to_rect(img: ImageRGBA, x1:int, x2:int, y1:int, y2:int) -> ImageRGBA:
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

    return img[y1:y2, x1:x2]

def transform(img: ImageRGBA, translate: Vec2=(0,0), scale: Vec2=(1,1), pivot: Vec2=(0.5, 0.5))->ImageRGBA:
    # 1. Calculate dimensions based on scale
    width = img.shape[1] * scale[0]
    height = img.shape[0] * scale[1]

    # 2. Calculate pivot-based offset AND add translation
    # The pivot logic finds the "anchor," and translate moves it from there.
    x = (img.shape[1] - width) * pivot[0] + translate[0]
    y = (img.shape[0] - height) * pivot[1] + translate[1]

    # 3. Precision Check
    # Using float32 epsilon is generally safer for CV2 operations
    e = np.finfo(np.float32).eps
    if (scale[0] <= e or scale[1] <= e):
        img.fill(0) # More efficient way to clear the image
        return img

    # 4. Construct the Affine Matrix
    # M = [ [sx, 0, tx], [0, sy, ty] ]
    M = np.array([
        [scale[0], 0, x],
        [0, scale[1], y]
    ], dtype=np.float32)

    # 5. Warp
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))
    
def card3D(img: ImageRGBA, translate:Vec3=(0,0,0), rotate:Vec3=(0,0,0), scale:Vec3=(1,1,1), camera=Camera(fov=math.radians(90), eye=(0,0,0), target=(0,0,1))) -> ImageRGBA:
    """
    Apply 3D perspective transform to an image.
    
    Input image should be RGBA float32. If RGB is provided, an opaque alpha channel will be added.
    Output is always RGBA float32.
    
    @fov: field of view in radians
    """
    height, width, channels = img.shape

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
    src_pts = np.array([(0,0), (width, 0), (width, height), (0, height)], dtype=np.float32)
    position = (src_pts+(-width/2, -height/2)) / max(width, height)
    position = [glm.vec4(pos[0], pos[1], 0, 1) for pos in position]

    # project vertices
    projected = [MVP*pos for pos in position] # viewspace
    projected = [proj/proj.w for proj in projected] # NDC space
    projected = [(vec.xy+(0.5, 0.5))*(width, height) for vec in projected] # screenspace
    
    dst_pts = np.array([vec.xy for vec in projected], dtype=np.float32) # keep 2d coords

    """Calculate perspective transform"""
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)

    """Warp image"""
    # make sure the image has an alpha channel and is float32
    if img.shape[2] == 3:
        warnings.warn("Input image has no alpha channel, adding opaque alpha channel.")
        alpha_channel = np.ones( (height, width, 1), dtype=img.dtype )
        img = np.dstack( (img, alpha_channel) )
    
    # ensure float32
    if img.dtype != np.float32:
        warnings.warn(f"Input image is {img.dtype}, converting to float32")
        img = img.astype(np.float32)

    # Convert to premultiplied alpha before warping to avoid color bleeding at edges
    # This prevents interpolation from introducing incorrect colors at semi-transparent edges
    img_premult = premultiply_alpha(img)
    
    # Warp with premultiplied alpha - edges will correctly interpolate to (0,0,0,0)
    result_premult = cv2.warpPerspective(img_premult, M, (width, height), borderValue=(0,0,0,0))
    
    # Convert back to straight alpha
    result = unpremultiply_alpha(result_premult)
    return result

def reformat(img: ImageRGBA, size: Tuple[int,int], interpolation=cv2.INTER_LINEAR)->ImageRGBA:
    return cv2.resize(img, size, interpolation=interpolation)
