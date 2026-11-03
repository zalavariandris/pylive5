from collections.abc import Callable
from typing import Any


_CONTEXTUAL_ATTRIBUTE = "__pygraphrt_contextual__"


def contextual[F: Callable[..., Any]](compute: F) -> F:
    """Mark a callable for managed contextual evaluation."""
    setattr(compute, _CONTEXTUAL_ATTRIBUTE, True)
    return compute


def is_contextual(value: object) -> bool:
    """Whether a returned value declares contextual evaluation."""
    return getattr(value, _CONTEXTUAL_ATTRIBUTE, False) is True
