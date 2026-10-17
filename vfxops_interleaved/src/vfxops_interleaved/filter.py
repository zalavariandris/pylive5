import numba
import numpy as np
import cv2

from .core import (
    ImageRGBA
)


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

def gaussian_blur(img: np.ndarray, size: float) -> np.ndarray:
    """
    Gaussian blur with After Effects-style control.
    
    Parameters
    ----------
    img : float32 RGBA or RGB image in range [0, 1]
    size : blur radius in pixels
    """

    if size <= 0:
        return img

    ksize = max(3, int(size * 2) | 1)
    sigma = size / 3.0

    result = img.copy()

    rgb = np.ascontiguousarray(img[..., :3])

    cv2.GaussianBlur(
        rgb,
        (ksize, ksize),
        sigmaX=sigma,
        dst=rgb,
        borderType=cv2.BORDER_REFLECT
    )

    result[..., :3] = rgb

    return result

def clip(img: np.ndarray, min_val: float = 0.0, max_val: float = 1.0) -> np.ndarray:
    """
    Clip image values to the specified range [min_val, max_val].

    Parameters
    ----------
    img : float32 RGBA or RGB image
    min_val : float, optional
        Minimum value to clip to, by default 0.0
    max_val : float, optional
        Maximum value to clip to, by default 1.0

    Returns
    -------
    np.ndarray
        Clipped image
    """
    return np.clip(img, min_val, max_val)
