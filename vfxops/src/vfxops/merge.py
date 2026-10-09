from .core import (
    ImageRGBA
)

import numpy as np
from typing import Tuple

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
    

