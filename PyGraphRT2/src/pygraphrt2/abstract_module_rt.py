from types import MappingProxyType
from typing import Mapping
from abc import ABCMeta, abstractmethod


from qtpy.QtCore import (
    QObject, 
    Signal,
)

from .graph_rt2 import AbstractOperator


class _AbstractQObjectMeta(type(QObject), ABCMeta):
    pass


class AbstractModule(QObject, metaclass=_AbstractQObjectMeta):
    operators_added = Signal(list) # list[str]
    operators_removed = Signal(list) # list[str]
    operators_changed = Signal(list) # list[str]

    def __init__(self, name: str, parent: QObject | None = None):
        super().__init__(parent=parent)
        self._name = name

    def name(self) -> str:
        return self._name
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self._name!r})"
    
    @abstractmethod
    def operators(self) -> Mapping[str, AbstractOperator]:
        pass

    @abstractmethod
    def get_operator(self, key: str) -> AbstractOperator | None:
        pass
