"""Data objects describing content to display; no Qt objects are created here."""

from dataclasses import dataclass

import numpy as np


@dataclass
class Image:
    data: np.ndarray


@dataclass
class HTML:
    data: str


@dataclass
class Markdown:
    data: str


@dataclass
class ImageCompare:
    """Two images of equal width and height, displayed with a wipe slider."""

    a: np.ndarray
    b: np.ndarray
