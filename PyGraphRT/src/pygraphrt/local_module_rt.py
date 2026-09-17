from __future__ import annotations
import inspect
from types import MappingProxyType
from typing import TYPE_CHECKING, Hashable, Mapping

if TYPE_CHECKING:
    from .graph_rt import GraphRT

from pygraphrt.operator_rt import ParameterRT
from qtpy.QtCore import (
    QObject, 
    Signal
)
from typing import Callable


from .operator_rt_ref import OperatorRTRef

from qtpy.QtCore import (
    QObject, 
    Signal,
)

from .abstract_module_rt import AbstractModuleRT
import inspect

class LocalModuleRT(AbstractModuleRT):
    def __init__(self, graph: GraphRT):
        super().__init__(graph)
        self._functions: dict[str, Callable] = {}
        self._operators: dict[str, OperatorRTRef] = {}

    def operators(self) -> Mapping[str, OperatorRTRef]:
        return {key: self._operators[key] for key in self._operators}
    
    def get_operator(self, name: str) -> OperatorRTRef | None:
        if name in self._functions:
            return self._operators[name]
        return None

    def get_parameters(self, operator: OperatorRTRef) -> MappingProxyType[str, ParameterRT]:
        if operator._key not in self._operators:
            return MappingProxyType({})
        """Returns the function parameters."""
        func = self._functions.get(operator._key)
        if func is None:
            return MappingProxyType({})
        
        sig = inspect.signature(func)

        return MappingProxyType({
            param.name: ParameterRT(
                name=param.name, 
                annotation=param.annotation,
                default=param.default,
            )
            for param in sig.parameters.values()
        })

    def isValid(self, operator: OperatorRTRef) -> bool:
        return operator._key in self._functions

    def fingerprint(self, operator: OperatorRTRef) -> Hashable:
        if not self.isValid(operator):
            raise ValueError(f"Operator {operator} is not valid.")
        return self._functions[operator._key]

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

    def call(self, op: OperatorRTRef, *args, **kwargs):
        if not self.isValid(op):
            raise ValueError(f"Operator {op._key} is not valid.")

        func = self._functions[op._key]
        return func(*args, **kwargs)
    
    def remove_operator(self, operator: OperatorRTRef):
        assert operator._key in self._functions, f"Operator {operator._key} does not exist in the engine."      

        del self._functions[operator._key]
        del self._operators[operator._key]
        self.operators_removed.emit([operator._key])

    def update_operator(self, operator: OperatorRTRef, func: Callable):
        assert operator._key in self._functions, f"Operator {operator._key} does not exist in the engine."
        prev_func = self._functions[operator._key]
        # if prev_func.__name__ != func.__name__:
        #     raise ValueError(f"Cannot update operator with a function that has a different name: {func.__name__}")
        self._functions[operator._key] = func
        self.operators_changed.emit([operator._key])
        op = self._operators[operator._key]
