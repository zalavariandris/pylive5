from typing import Callable, Any
from types import MappingProxyType
from dataclasses import dataclass
import inspect
from qtpy.QtCore import (
    QObject, 
    Signal
)

def _getsource(func: "Callable") -> str:
    """Like inspect.getsource but strips decorators."""
    import ast, textwrap
    src = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(src)
    # FunctionDef.lineno is always the 'def' line, regardless of decorators
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return "".join(src.splitlines(keepends=True)[node.lineno - 1:])
    return src


@dataclass(frozen=True, slots=True)
class ParameterRT:
    name: str
    annotation: type


class OperatorRT(QObject):
    function_changed = Signal()
    
    def __init__(self, graph, name: str, func: Callable | str):
        super().__init__()
        self._graph = graph
        if isinstance(func, str):
            func = self.compile(func)
        self._func = func
        self._name = name

    def get_name(self) -> str:
        return self._name

    def get_function(self) -> Callable | None:
        return self._func

    def get_source(self) -> str | None:
        if self._func is None:
            return None
        return _getsource(self._func)

    def set_function(self, func: Callable | None):
        """Sets the function of the node and updates its parameters accordingly."""
        assert func is None or callable(func), "func must be a callable function or None"
        if func is not self._func:
            self._func = func
            self.function_changed.emit()

    def get_parameters(self) -> MappingProxyType[str, ParameterRT]:
        """Returns the function parameters."""
        if self._func is None:
            return MappingProxyType({})
        
        sig = inspect.signature(self._func)

        return MappingProxyType({
            param.name: ParameterRT(name=param.name, annotation=param.annotation)
            for param in sig.parameters.values()
        })

    @staticmethod
    def compile(source: str) -> Callable:
        """Compiles the given source code into a callable function."""
        #todo: consider using a more secure execution environment!
        local_dict: dict = {}
        exec(source, local_dict)

        function_objects = list(
            filter(lambda item: callable(item), local_dict.values())
        )
        if not function_objects:
            raise ValueError("No function found in the source.")

        return function_objects[-1]

    def __eq__(self, other):
        if not isinstance(other, OperatorRT):
            return NotImplemented
        return self.get_name() == other.get_name()

    def __hash__(self):
        return hash(("Node", self.get_name()))

    def __call__(self, *args, **kwargs):
        """Calls the function, with the given arguments."""
        if self._func is None:
            raise ValueError("Operator function is not set.")
        return self._func(*args, **kwargs)
