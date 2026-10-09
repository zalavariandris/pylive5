"""A visual stage for command-line programs."""

from .data import HTML, Image, ImageCompare, Markdown
from .stage import Stage
import logging
logger = logging.getLogger(__name__)

_stage = Stage()


def show(data: object = None) -> bool:
    """Display data in the shared stage, starting its viewer if needed."""
    try:
        _stage.show(data)
    except Exception as exc:
        logger.warning("Could not display preview: %s", exc)
        return False
    return True


def clear() -> bool:
    """Clear the shared stage if its viewer is running."""
    try:
        _stage.clear()
    except Exception as exc:
        logger.warning("Could not clear the stage: %s", exc)
        return False
    return True


def close() -> bool:
    """Stop the shared stage's viewer."""
    try:
        _stage.close() 
    except Exception as exc:
        logger.warning("Could not close the stage: %s", exc)
        return False
    return True


__all__ = [
    "Stage", "Image", "ImageCompare", "HTML", "Markdown",
    "show", "clear", "close",
]
