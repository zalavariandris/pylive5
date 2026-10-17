import numpy as np

from .core import IMAGE_DTYPE, Image, ImageRGBA, validate_image_data


def merge_over(A: ImageRGBA, B: ImageRGBA, mix: float) -> ImageRGBA:
    """Composite straight RGBA over the overlap, retaining A's extent outside it."""
    validate_image_data(A)
    validate_image_data(B)
    height = min(A.shape[1], B.shape[1])
    width = min(A.shape[2], B.shape[2])
    foreground = A[:, :height, :width]
    background = B[:, :height, :width]
    alpha_a = foreground[3:4]
    alpha_b = background[3:4]

    composite = np.empty((4, height, width), dtype=IMAGE_DTYPE)
    alpha = composite[3:4]
    alpha[:] = alpha_a + alpha_b * (1.0 - alpha_a)
    rgb = foreground[:3] * alpha_a + background[:3] * alpha_b * (1.0 - alpha_a)
    composite[:3] = 0.0
    np.divide(rgb, alpha, out=composite[:3], where=alpha > 1e-6)

    weight = np.float32(mix)
    result = A.copy(order="C")
    result[:, :height, :width] = background * (np.float32(1.0) - weight) + composite * weight
    return result


def merge_multiply(A: ImageRGBA, B: ImageRGBA) -> ImageRGBA:
    """Multiply RGB and combine alpha with over, using planar straight RGBA."""
    validate_image_data(A)
    validate_image_data(B)
    if A.shape != B.shape:
        raise ValueError("Images must have the same shape")
    result = np.empty(A.shape, dtype=IMAGE_DTYPE)
    np.multiply(A[:3], B[:3], out=result[:3])
    result[3] = A[3] + B[3] * (1.0 - A[3])
    return result


def paste(img: Image, other: Image, origin: tuple[int, int]) -> Image:
    """Paste other into img in place, at the (x, y) origin."""
    validate_image_data(img, channels=None)
    validate_image_data(other, channels=img.shape[0])
    x, y = origin
    img[:, y:y + other.shape[1], x:x + other.shape[2]] = other
    return img


def premultiply(img: ImageRGBA) -> ImageRGBA:
    """Multiply planar RGB by alpha, preserving the input and alpha plane."""
    validate_image_data(img)
    result = img.copy(order="C")
    result[:3] *= result[3:4]
    return result


def unpremultiply(img: ImageRGBA) -> ImageRGBA:
    """Recover straight RGB, setting RGB to zero where alpha is near zero."""
    validate_image_data(img)
    result = np.zeros(img.shape, dtype=IMAGE_DTYPE)
    result[3] = img[3]
    np.divide(img[:3], img[3:4], out=result[:3], where=img[3:4] > 1e-6)
    return result
