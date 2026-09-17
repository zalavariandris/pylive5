from contextlib import contextmanager
from qtpy.QtCore import QObject

@contextmanager
def blockingSignals(obj: QObject):
    """Context manager to block signals temporarily."""
    # store current state
    was_blocked = obj.signalsBlocked()
    obj.blockSignals(True)
    try:
        yield
    finally:
        obj.blockSignals(was_blocked)
        