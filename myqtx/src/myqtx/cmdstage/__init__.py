"""A visual stage for command-line programs."""

from .data import HTML, Image, ImageCompare, Markdown
from .stage import Stage

_stage = Stage()


def show(data: object = None) -> None:
    """Display data in the shared stage, starting its viewer if needed."""
    _stage.show(data)


def clear() -> None:
    """Clear the shared stage if its viewer is running."""
    _stage.clear()


def close() -> None:
    """Stop the shared stage's viewer."""
    _stage.close()


__all__ = [
    "Stage", "Image", "ImageCompare", "HTML", "Markdown",
    "show", "clear", "close",
]
