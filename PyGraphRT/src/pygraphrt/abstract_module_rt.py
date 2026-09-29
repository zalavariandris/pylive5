from types import MappingProxyType
from abc import ABCMeta, abstractmethod
from typing import Callable, Any, ClassVar, Iterable, Mapping, override
import inspect
from qtpy.QtCore import (
    QObject, 
    Signal,
)

from dataclasses import dataclass





@dataclass(frozen=True)
class ParameterData:
    _empty:ClassVar = object()
    name:str
    annotation:type = _empty
    default: Any = _empty

    def __repr__(self):
        return f"ParameterData(name='{self.name}', annotation={self.annotation}, default={self.default})"


import abc
class AbstractOperator(abc.ABC):
    def __init__(self):
        super().__init__()

    @abc.abstractmethod
    def fingerprint(self) -> int:
        pass

    @abc.abstractmethod
    def get_parameters(self) -> Mapping[str, ParameterData]:
        pass

    @abc.abstractmethod
    def get_return_type(self) -> type:
        pass

    @abc.abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        pass


class OperatorRef(AbstractOperator):
    """An operator owned by a module."""

    def __init__(self, module: 'AbstractModule', name: str):
        assert isinstance(module, AbstractModule), "module must be an instance of AbstractModule"
        self.module = module
        self.name = name

    def fingerprint(self) -> int:
        the_function = self.module.get_operator(self)
        return hash(the_function)

    def get_name(self) -> str:
        return self.name

    def __eq__(self, other):
        if not isinstance(other, OperatorRef):
            return False
        return self.module == other.module and self.name == other.name

    def __hash__(self):
        return hash((self.module, self.name))

    @override
    def __call__(self, *args, **kwargs):
        value = self.module.get_operator(self)
        return value(*args, **kwargs)

    @override
    def get_parameters(self) -> Mapping[str, ParameterData]:
        if operator_data := self.module.get_operator(self):
            return operator_data.get_parameters()
        return dict()

    @override
    def get_return_type(self) -> type:
        if operator_data := self.module.get_operator(self):
            return operator_data.get_return_type()
        return type(None)


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

    # @abstractmethod
    # def get_operator(self, ref: OperatorRef) -> AbstractOperator | None:
    #     pass


