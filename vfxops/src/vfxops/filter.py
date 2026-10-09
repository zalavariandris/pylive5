from dataclasses import dataclass
import numpy as np

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

def premultiply(img: ImageRGBA) -> ImageRGBA:
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

def unpremultiply(img: ImageRGBA) -> ImageRGBA:
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