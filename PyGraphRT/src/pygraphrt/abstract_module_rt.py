from __future__ import annotations
from types import MappingProxyType
from typing import TYPE_CHECKING, Hashable, Mapping

if TYPE_CHECKING:
    from pygraphrt.graph_rt import GraphRT

from pygraphrt.operator_rt import ParameterRT
from qtpy.QtCore import (
    QObject, 
    Signal
)

from .operator_rt_ref import OperatorRTRef

from qtpy.QtCore import (
    QObject, 
    Signal,
)

from abc import ABCMeta, abstractmethod
class _AbstractQObjectMeta(type(QObject), ABCMeta):
    pass


class AbstractModuleRT(QObject, metaclass=_AbstractQObjectMeta):
    operators_added = Signal(list) # list[str]
    operators_removed = Signal(list) # list[str]
    operators_changed = Signal(list) # list[str]

    def __init__(self, graph: GraphRT):
        super().__init__()
        self._graph = graph

    @abstractmethod
    def operators(self) -> Mapping[str, OperatorRTRef]:
        pass

    @abstractmethod
    def get_operator(self, name: str) -> OperatorRTRef | None:
        pass

    @abstractmethod
    def isValid(self, operator: OperatorRTRef) -> bool:
        pass

    @abstractmethod
    def get_parameters(self, operator: OperatorRTRef) -> MappingProxyType[str, ParameterRT]:
        pass

    @abstractmethod
    def fingerprint(self, operator: OperatorRTRef) -> Hashable:
        pass

    @abstractmethod
    def call(self, op: OperatorRTRef, *args, **kwargs):
        pass

    
    