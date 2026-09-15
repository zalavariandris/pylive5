from .operator_rt import OperatorRT
from qtpy.QtCore import (
    QObject, 
    Signal
)
from typing import Callable


class LocalModuleRT(QObject):
    operators_added = Signal(list) # list[str]
    operators_removed = Signal(list) # list[str]
    operator_function_changed = Signal(list) # list[str]

    def __init__(self, graph: "GraphRT"):
        super().__init__()
        self._graph = graph
        self._operators: set[OperatorRT] = set()
        self._connected_operator_signals: dict[str, list[tuple]] = {}

    def op(self) -> Callable:
        """Decorator to create and add an operator to the graph.

        Usage:
            @graph.op()
            def my_operator(...):
                ...
        """
        def decorator(func: Callable) -> OperatorRT:
            current_operator_names = [op.get_name() for op in self._operators]
            assert func.__name__ not in current_operator_names, f"Cannot add operator with duplicate name: {func.__name__}"
            operator = OperatorRT(self, func.__name__, func)
            self._operators.add(operator)
            
            self.operators_added.emit([operator.get_name()])

            # forward operator signals
            self._connected_operator_signals[operator.get_name()] = [
                (operator.function_changed, lambda: self.operator_function_changed.emit(operator.get_name()))
            ]
            for signal, slot in self._connected_operator_signals[operator.get_name()]:
                signal.connect(slot)
                
            return operator
        return decorator

    def remove_operator(self, operator: OperatorRT):
        assert operator in self._operators, f"Operator {operator} does not exist in the engine."      

        self._operators.remove(operator)
        self.operators_removed.emit([operator.get_name()])
        for signal, slot in self._connected_operator_signals[operator.get_name()]:
            signal.disconnect(slot)

    def operators(self) -> list[str, OperatorRT]:
        return {op.get_name(): op for op in self._operators}

    def get_operator(self, name: str) -> OperatorRT | None:
        for op in self._operators:
            if op.get_name() == name:
                return op
        return None

    def get_source(self, operator: OperatorRT) -> str:
        func = operator.get_function()
        import inspect
        return inspect.getsource(func)

