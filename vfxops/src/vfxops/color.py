from .core import ImageRGBA

def exposure(img: ImageRGBA, ev: float) -> ImageRGBA:
    """Adjust the exposure of an image.
    
    Parameters
    ----------
    img : ImageRGBA
        Input image data (H x W x 4) RGBA float32
    ev : float
        Exposure value. Positive values increase exposure, negative values decrease it.
    
    Returns
    -------
    ImageRGBA
        Image with adjusted exposure
    """
    factor = 2.0 ** ev
    img[:,:,:3] = img[:,:,:3] * factor
    return img