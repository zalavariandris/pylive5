from types import MappingProxyType
from abc import ABCMeta, abstractmethod
from typing import Callable, Any, ClassVar, Iterable, Mapping
import inspect
from qtpy.QtCore import (
    QObject, 
    Signal,
)

from dataclasses import dataclass

class MissingOperatorError(Exception):
    pass

import abc
class AbstractOperator(abc.ABC):
    def __init__(self):
        super().__init__()

    @abc.abstractmethod
    def get_parameters(self) -> Mapping[str, ParameterData]:
        pass

    @abc.abstractmethod
    def get_return_type(self) -> type:
        pass

    @abc.abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        pass


@dataclass(frozen=True)
class ParameterData:
    _empty:ClassVar = object()
    name:str
    annotation:type = _empty
    default: Any = _empty

    def __repr__(self):
        return f"ParameterData(name='{self.name}', annotation={self.annotation}, default={self.default})"


@dataclass
class OperatorRef:
    module: 'AbstractModule'
    name: str

    def _post_init__(self):
        assert isinstance(self.module, AbstractModule), "module must be an instance of AbstractModule"

    def __eq__(self, other):
        if not isinstance(other, OperatorRef):
            return False
        return self.module == other.module and self.name == other.name

    def __hash__(self):
        return hash((self.module, self.name))

    def get_name(self) -> str:
        return self.name

    def get_value(self) -> AbstractOperator | None:
        return self.module.get_operator(self)
    
    def get_parameters(self) -> Mapping[str, ParameterData]:
        if operator_data := self.get_value():
            return operator_data.get_parameters()
        return dict()


class _AbstractQObjectMeta(type(QObject), ABCMeta):
    pass


class AbstractModule(QObject, metaclass=_AbstractQObjectMeta):
    operators_added = Signal(list) # list[OperatorRef]
    operators_removed = Signal(list) # list[OperatorRef]
    operators_changed = Signal(list) # list[OperatorRef]

    def __init__(self, name: str, parent: QObject | None = None):
        super().__init__(parent=parent)
        self._name = name

    def get_name(self) -> str:
        return self._name

    def set_name(self, name: str)->bool:
        self._name = name
        return True
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self._name!r})"
    
    @abstractmethod
    def operators(self) -> Iterable[OperatorRef]:
        pass

    @abstractmethod
    def get_operator(self, ref: OperatorRef) -> AbstractOperator | None:
        pass


