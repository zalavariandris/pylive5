from __future__ import annotations
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from pygraphrt.graph_rt import GraphRT

from qtpy.QtCore import (
    QObject, 
    Signal
)
from typing import Callable


from .operator_rt_ref import OperatorRTRef


class LocalModuleRT(QObject):
    operators_added = Signal(list) # list[str]
    operators_removed = Signal(list) # list[str]
    operator_changed = Signal(list) # list[str]

    def __init__(self, graph: GraphRT):
        super().__init__()
        self._functions: dict[str, Callable] = {}
        self._operators: dict[str, OperatorRTRef] = {}
        self._graph = graph

    def operators(self) -> Mapping[str, OperatorRTRef]:
        return {key: self._operators[key] for key in self._functions}
    
    def get_operator(self, name: str) -> OperatorRTRef | None:
        if name in self._functions:
            return self._operators[name]
        return None

    def op(self) -> Callable[[Callable], OperatorRTRef]:
        """Decorator to create and add an operator to the graph.

        Usage:
            @graph.op()
            def my_operator(...):
                ...
        """
        def decorator(func: Callable) -> OperatorRTRef:
            current_operator_names = list(self._functions.keys())
            assert func.__name__ not in current_operator_names, f"Cannot add operator with duplicate name: {func.__name__}"
            key = func.__name__
            self._functions[key] = func
            self._operators[key] = OperatorRTRef(self, key)
            
            self.operators_added.emit([key])

            # forward operator signals
            op = self._operators[key]
            return op
        return decorator

    def remove_operator(self, operator: OperatorRTRef):
        assert operator._key in self._functions, f"Operator {operator._key} does not exist in the engine."      

        del self._functions[operator._key]
        del self._operators[operator._key]
        self.operators_removed.emit([operator._key])

    def update_operator(self, operator: OperatorRTRef, func: Callable):
        assert operator._key in self._functions, f"Operator {operator._key} does not exist in the engine."
        prev_func = self._functions[operator._key]
        if prev_func.__name__ != func.__name__:
            raise ValueError(f"Cannot update operator with a function that has a different name: {func.__name__}")
        self._functions[operator._key] = func
        self.operator_changed.emit([operator._key])
        op = self._operators[operator._key]
