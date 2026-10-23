from types import FunctionType, ModuleType
import concurrent
import weakref

from typing import Callable, Iterable, Literal, Any
import inspect
from pathlib import Path
from qtpy.QtCore import Signal, QObject


class Registry(QObject):
    operators_added = Signal(list) # list[Callable]
    operators_removed = Signal(list) # list[Callable]
    operators_changed = Signal(list) # list[Callable]

    def operators(self) -> Iterable[Callable]:
        # This should return all operator references in the registry
        raise NotImplementedError()