from __future__ import annotations
from typing import TYPE_CHECKING, Any
from qtpy.QtCore import QObject, Signal

if TYPE_CHECKING:
    from .graph_rt import GraphRT
from .operator_rt import OperatorRT


def _assert_hashable_inputs(*args, **kwargs) -> None:
    # TODO: support unhashable literal inputs (e.g. dicts, lists)
    for i, v in enumerate(args):
        if not isinstance(v, NodeRT):
            try:
                hash(v)
            except TypeError:
                raise TypeError(f"Literal input at position {i} is not hashable ({type(v).__name__!r}). Unhashable inputs are not yet supported.") from None
    for k, v in kwargs.items():
        if not isinstance(v, NodeRT):
            try:
                hash(v)
            except TypeError:
                raise TypeError(f"Literal input {k!r} is not hashable ({type(v).__name__!r}). Unhashable inputs are not yet supported.") from None

import weakref

class NodeRT(QObject):
    inputs_changed = Signal()
    operator_changed = Signal()

    def __init__(self, graph:'GraphRT', operator: OperatorRT, name: str):
        super().__init__()
        assert isinstance(operator, OperatorRT), "operator must be an instance of OperatorRT"
        self._name = name
        self._operator: weakref.ReferenceType[OperatorRT] | None = weakref.ref(operator) if operator is not None else None
        self._args: tuple = ()
        self._kwargs: dict[str, Any] = {}
        self._graph: GraphRT = graph

    def get_name(self) -> str:
        return self._name

    def set_operator(self, operator: OperatorRT | None):
        """Sets the operator of the node."""
        if not isinstance(operator, (OperatorRT, type(None))):
            raise TypeError("operator must be an instance of OperatorRT")
        
        if operator is not None and operator not in self._graph._operators:
            raise ValueError("operator must be part of the graph")
        
        if self._operator is not None:
            self._graph._operators_to_nodes[self._operator].discard(self)

        if operator is not None:
            self._graph._operators_to_nodes.setdefault(operator, set()).add(self)

        self._operator = operator

        self.operator_changed.emit()

    def get_operator(self) -> OperatorRT|None:
        if self._operator:
            return self._operator()
        else:
            return None

    def get_inputs(self) -> tuple[tuple, dict[str, Any]]:
        return tuple(self._args), {k: v for k, v in self._kwargs.items()}

    def set_inputs(self, *args, **kwargs):
        for arg in args:
            if isinstance(arg, NodeRT) and arg not in self._graph._nodes:
                raise ValueError(f"Node {arg.get_name()} is not part of the runtime. Please add it before using it as an input.")

        for kwarg in kwargs.values():
            if isinstance(kwarg, NodeRT) and kwarg not in self._graph._nodes:
                raise ValueError(f"Node {kwarg.get_name()} is not part of the runtime. Please add it before using it as an input.")

        _assert_hashable_inputs(*args, **kwargs)

        prev_successors = set(arg for arg in self._args if isinstance(arg, NodeRT)) | set(kwarg for kwarg in self._kwargs.values() if isinstance(kwarg, NodeRT))
        next_successors = set(arg for arg in args if isinstance(arg, NodeRT)) | set(kwarg for kwarg in kwargs.values() if isinstance(kwarg, NodeRT))

        for arg in prev_successors - next_successors:
            self._graph._successors[arg].discard(self)

        for arg in next_successors - prev_successors:
            self._graph._successors[arg].add(self)

        self._args = args
        self._kwargs = kwargs
        self.inputs_changed.emit()

    def __call__(self, *args, **kwargs):
        operator_ref = self._operator
        if operator_ref is None:
            raise ValueError(f"Node {self._name} has no operator.")
        elif operator_ref() is None:
            raise ValueError(f"Node {self._name} has an invalid operator.")
        else:
            return operator_ref()(*args, **kwargs)
