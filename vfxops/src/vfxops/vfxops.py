from typing import Union, Tuple
from dataclasses import dataclass
from pathlib import Path
import math
import warnings

import numpy as np
import cv2
import glm


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

# IO
from pathlib import Path
def read_image(path:Union[str, Path]) -> ImageRGBA:
    """Read image from disk as RGBA float32 (0-1)"""
    if not Path(path).exists():
        raise FileNotFoundError(f"File does not exist: {path}")

    img_bgr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img_bgr is None:
        raise Exception(f"Failed to read image from path: {path}")

    nr_of_channels = img_bgr.shape[2]

    match nr_of_channels:
        case 1:
            # grayscale to BGRA
            img = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2RGBA)
            return img.astype(np.float32) / 255.0
        
        case 3:
            # BGR to BGRA
            img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
            return img.astype(np.float32) / 255.0
        
        case 4:
            rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGBA)
            return rgba.astype(np.float32) / 255.0
        
        case _:
            raise Exception(f"Unsupported number of channels: {nr_of_channels} in image: {path}")

def to_sRGB(img: ImageRGBA) -> Image_sRGB:
    """Convert RGBA float32 (0-1) to RGB uint8 (0-255)."""
    return cv2.convertScaleAbs(img*255).astype(np.uint8)[:,:,:3]

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

#filter
def add_grain(img: ImageRGBA, variance:float):
    """Add Gaussian noise (grain) to an RGBA image.
    
    Args:
        img: Input RGBA float32 image
        variance: Noise variance. Typical range: 0.0001-0.01 (subtle to moderate grain).
    
    Returns:
        RGBA float32 image with added grain
    """
    assert img.dtype == np.float32

    row,col,ch= img.shape
    mean = 0
    sigma = variance**0.5
    gauss = np.random.normal(mean,sigma,(row,col,ch)).astype(np.float32)
    gauss = gauss.reshape(row,col,ch)
    noisy = img + gauss
    return noisy
    
def noisy(img: ImageRGBA, noise_typ):
    """
    Parameters
    ----------
    image : ndarray
        Input image data. Will be converted to float.
    mode : str
        One of the following strings, selecting the type of noise to add:

        'gauss'     Gaussian-distributed additive noise.
        'poisson'   Poisson-distributed noise generated from the data.
        's&p'       Replaces random pixels with 0 or 1.
        'speckle'   Multiplicative noise using out = image + n*image,where
                    n is uniform noise with specified mean & variance
    """

    if noise_typ == "gauss":
        row,col,ch= img.shape
        mean = 0
        var = 0.0001
        sigma = var**0.5
        gauss = np.random.normal(mean,sigma,(row,col,ch))
        gauss = gauss.reshape(row,col,ch)
        noisy = img + gauss
        return noisy

    elif noise_typ == "s&p":
        row,col,ch = img.shape
        s_vs_p = 0.5
        amount = 0.004
        out = np.copy(img)
        # Salt mode
        num_salt = np.ceil(amount * img.size * s_vs_p)
        coords = [np.random.randint(0, i - 1, int(num_salt)) for i in img.shape]
        out[coords] = 1

        # Pepper mode
        num_pepper = np.ceil(amount* img.size * (1. - s_vs_p))
        coords = [np.random.randint(0, i - 1, int(num_pepper)) for i in img.shape]
        out[coords] = 0
        return out
    
    elif noise_typ == "poisson":
        vals = len(np.unique(img))
        vals = 2 ** np.ceil(np.log2(vals))*10
        noisy = np.random.poisson(img * vals) / float(vals)
        return noisy
    
    elif noise_typ =="speckle":
        row,col,ch = img.shape
        gauss = np.random.randn(row,col,ch)
        gauss = gauss.reshape(row,col,ch)        
        noisy = img + img * gauss
        return noisy

# image
def encode_jpg(img: ImageRGBA, quality:int=75) -> bytes:
    extension = ".jpg"
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    _, buffer = cv2.imencode(extension, to_sRGB(img), params)
    return buffer.tobytes()

# merge
def merge_over(A: np.ndarray, B: np.ndarray, mix: float) -> np.ndarray:
    # 1. Determine common dimensions (the intersection)
    h_overlap = min(A.shape[0], B.shape[0])
    w_overlap = min(A.shape[1], B.shape[1])

    # 2. Create views of the intersection
    # This prevents broadcasting errors because A_part and B_part will have same H, W
    A_part = A[:h_overlap, :w_overlap]
    B_part = B[:h_overlap, :w_overlap]

    # --- Your Original Logic starts here, but uses the slices ---
    A_alpha = A_part[:, :, 3:4]
    B_alpha = B_part[:, :, 3:4]
    
    out_alpha = A_alpha + B_alpha * (1 - A_alpha)
    
    out_rgb = A_part[:, :, :3] * A_alpha + B_part[:, :, :3] * B_alpha * (1 - A_alpha)
    out_rgb = np.divide(out_rgb, out_alpha, out=np.zeros_like(out_rgb), where=out_alpha > 1e-6)
    
    composite = np.concatenate([out_rgb, out_alpha], axis=2)
    
    # Apply mix to the intersection
    blended_part = B_part * (1 - mix) + composite * mix
    # --- End of logic ---

    # 3. Construct the final output
    # We start with a copy of B so that the areas NOT covered by A remain untouched
    result = A.copy()
    result[:h_overlap, :w_overlap] = blended_part
    
    return result

def merge_multiply(A: ImageRGBA, B: ImageRGBA) -> ImageRGBA:
    """Merge two RGBA float32 images using the 'multiply' blending mode.
    
    Parameters:
    -----------
    A : ImageRGBA
        First image (H x W x 4) RGBA float32 (straight alpha)
    B : ImageRGBA
        Second image (H x W x 4) RGBA float32 (straight alpha)
    
    Returns:
    --------
    ImageRGBA
        Blended RGBA float32 image (A multiplied by B)
    """
    # Multiply RGB channels
    out_rgb = A[:,:,:3] * B[:,:,:3]
    
    # Combine alpha channels using 'over' operation
    A_alpha = A[:,:,3:4]
    B_alpha = B[:,:,3:4]
    out_alpha = A_alpha + B_alpha * (1 - A_alpha)
    
    return np.dstack([out_rgb, out_alpha])

def paste(img: ImageRGBA, other: ImageRGBA, origin:Tuple[int,int]):
    x,y = origin
    img[y:y+other.shape[0], x:x+other.shape[1]] = other
    return img
    
def premultiply_alpha(img: ImageRGBA) -> ImageRGBA:
    """Convert from straight (unassociated) alpha to premultiplied (associated) alpha.
    
    In premultiplied alpha, RGB channels are multiplied by the alpha channel.
    This is the correct format for interpolation operations to avoid color bleeding.
    
    Parameters:
    -----------
    img : ImageRGBA
        Image with straight alpha (H x W x 4) RGBA float32
    
    Returns:
    --------
    ImageRGBA
        Image with premultiplied alpha
    """
    alpha = img[:,:,3:4]
    rgb_premult = img[:,:,:3] * alpha
    return np.dstack([rgb_premult, alpha])

def unpremultiply_alpha(img: ImageRGBA) -> ImageRGBA:
    """Convert from premultiplied (associated) alpha to straight (unassociated) alpha.
    
    Divides RGB channels by alpha to recover original colors.
    Where alpha is near zero, RGB is set to black.
    
    Parameters:
    -----------
    img : ImageRGBA
        Image with premultiplied alpha (H x W x 4) RGBA float32
    
    Returns:
    --------
    ImageRGBA
        Image with straight alpha
    """
    alpha = img[:,:,3:4]
    rgb = np.divide(img[:,:,:3], alpha, 
                   out=np.zeros_like(img[:,:,:3]), 
                   where=alpha > 1e-6)
    return np.dstack([rgb, alpha])

# utils
def get_sequence_frame_range(image_sequence_pattern: str) -> Tuple[int, int]:
    """Returns the first and last frame numbers in the image sequence."""
    # match all files in the sequence, to get all frame numbers
    import re
    import glob
    import os
    """filepath: path pattern with printf style format, e.g. 'image_%04d.png'"""
    
    # Extract directory and filename pattern
    path_obj = Path(image_sequence_pattern)
    parent_dir = path_obj.parent
    filename_pattern = path_obj.name
    
    if not parent_dir.exists():
        raise Exception(f"No such directory: '{parent_dir.absolute()}'")
    
    # Convert printf pattern (e.g., %04d) to regex pattern
    # Match patterns like %04d, %05d, %d, etc.
    regex_pattern = re.sub(r'%0?(\d*)d', r'(\\d+)', filename_pattern)
    regex_pattern = f"^{regex_pattern}$"
    
    # Find all matching files and extract frame numbers
    frames = {}
    for file_path in parent_dir.glob("*" + path_obj.suffix):
        match = re.match(regex_pattern, file_path.name)
        if match:
            frame_num = int(match.group(1))
            frames[frame_num] = file_path

    first_frame = min(frames.keys()) if frames else None
    last_frame = max(frames.keys()) if frames else None
    
    
    if not frames:
        raise ValueError(f"No image files found matching pattern: '{image_sequence_pattern}'")
    
    frame_numbers = sorted(frames.keys())
    first_frame = frame_numbers[0]
    last_frame = frame_numbers[-1]

    # warn for missing frames
    expected_frames = set(range(first_frame, last_frame+1))
    missing_frames = expected_frames - set(frame_numbers)
    if missing_frames:
        warnings.warn(f"Warning: Missing frames in sequence: {sorted(missing_frames)}")

    return first_frame, last_frame
