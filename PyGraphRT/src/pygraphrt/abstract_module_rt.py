from typing import Iterable
from abc import ABCMeta, abstractmethod

from qtpy.QtCore import (
    QObject, 
    Signal,
)


from .abstract_operator import AbstractOperator, ParameterData


class _AbstractQObjectMeta(type(QObject), ABCMeta):
    pass


class AbstractModule(QObject, metaclass=_AbstractQObjectMeta):
    operators_added = Signal(list) # list[OperatorRef]
    operators_removed = Signal(list) # list[OperatorRef]
    operators_changed = Signal(list) # list[OperatorRef]

    def __init__(self, name: str|None=None, parent: QObject | None = None):
        super().__init__(parent=parent)
        self._display_name = name

    def get_display_name(self) -> str|None:
        return self._display_name

    def set_display_name(self, name: str|None)->bool:
        self._display_name = name
        return True
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self._display_name!r})"
    
    @abstractmethod
    def operators(self) -> Iterable[AbstractOperator]:
        pass
