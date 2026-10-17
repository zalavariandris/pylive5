import cv2
import numpy as np

from .core import IMAGE_DTYPE, Image, ImageRGBA, validate_image_data


def add_grain(img: ImageRGBA, variance: float) -> ImageRGBA:
    """Add Gaussian noise to all RGBA planes, matching the existing grain behavior."""
    validate_image_data(img)
    if variance < 0:
        raise ValueError("variance must be nonnegative")
    noise = np.random.default_rng().standard_normal(img.shape, dtype=IMAGE_DTYPE)
    noise *= np.float32(variance ** 0.5)
    noise += img
    return noise


def noisy(img: ImageRGBA, noise_typ: str) -> ImageRGBA:
    """Add gauss, poisson, s&p, or speckle noise to all planar RGBA channels."""
    validate_image_data(img)
    rng = np.random.default_rng()

    if noise_typ == "gauss":
        return add_grain(img, variance=0.0001)

    if noise_typ == "s&p":
        result = img.copy(order="C")
        count = int(np.ceil(0.004 * img.size * 0.5))
        for value in (1.0, 0.0):
            coordinates = tuple(rng.integers(0, length, count) for length in img.shape)
            result[coordinates] = value
        return result

    if noise_typ == "poisson":
        levels = np.float32(2 ** np.ceil(np.log2(len(np.unique(img)))) * 10)
        # Poisson samples are integers. Convert before floating-point division.
        result = rng.poisson(img * levels).astype(IMAGE_DTYPE)
        result /= levels
        return result

    if noise_typ == "speckle":
        result = rng.standard_normal(img.shape, dtype=IMAGE_DTYPE)
        result *= img
        result += img
        return result

    raise ValueError(f"Unknown noise type: {noise_typ!r}")


def gaussian_blur(img: Image, size: float) -> Image:
    """Blur planar RGB, preserving alpha when present; size is a pixel radius."""
    validate_image_data(img, channels=(3, 4))
    if size <= 0:
        return img

    ksize = max(3, int(size * 2) | 1)
    sigma = size / 3.0
    result = img.copy(order="C")
    for channel in range(3):
        cv2.GaussianBlur(
            img[channel],
            (ksize, ksize),
            sigmaX=sigma,
            dst=result[channel],
            borderType=cv2.BORDER_REFLECT,
        )
    return result


def clip(img: Image, min_val: float = 0.0, max_val: float = 1.0) -> Image:
    """Clip every plane of a float32 image to the requested range."""
    validate_image_data(img, channels=None)
    result = np.empty(img.shape, dtype=IMAGE_DTYPE)
    np.clip(img, np.float32(min_val), np.float32(max_val), out=result)
    return result
