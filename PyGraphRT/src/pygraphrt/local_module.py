from .abstract_module_rt import (
    AbstractOperator,
    AbstractModule,
    OperatorRef,
    ParameterData,
    MissingOperatorError
)
from types import MappingProxyType
from typing import Callable, Mapping, Any
import inspect

from qtpy.QtCore import QObject

class FunctionOperator(AbstractOperator):
    def __init__(self, func:callable):
        super().__init__()
        self._func = func

    def get_parameters(self) -> Mapping[str, ParameterData]:
        sig = inspect.signature(self._func)
        params = {}
        for name, param in sig.parameters.items():
            param_data = ParameterData(
                name, 
                param.annotation if param.annotation is not inspect.Parameter.empty else ParameterData._empty,
                param.default if param.default is not inspect.Parameter.empty else ParameterData._empty
                )

            params[name] = param_data
        return MappingProxyType(params)

    def get_return_type(self) -> type:
        sig = inspect.signature(self._func)
        return sig.return_annotation if sig.return_annotation is not inspect.Signature.empty else Any

    def __call__(self, *args, **kwargs) -> Any:
        return self._func(*args, **kwargs)

    

class LocalModuleRT(AbstractModule):
    """An editable script runtime exporting callable module-level bindings.

    Updates execute in a fresh shared namespace and commit before emitting signals.
    Operator change notifications use structural function differences; changes to
    globals and dependencies are not tracked by this analysis.
    Tracebacks identify the script by its module name as <script:name>.
    """

    def __init__(self, parent:QObject | None = None):
        super().__init__("_local_", parent=parent)

        self._operators:dict[str, FunctionOperator] = dict()

    def op(self) -> Callable[[Callable], OperatorRef]:
        def decorator(func: Callable) -> OperatorRef:
            # assert that func is not simply a callable, but a function
            assert callable(func), "func must be a callable function"
            
            ref = OperatorRef(self, func.__name__)
            data = FunctionOperator(func)
            self._operators[ref] = data
            self.operators_added.emit([ref])
            return ref
        return decorator

    def operators(self) -> Mapping[str, AbstractOperator]:
        return {k:v for k, v in self._operators.items()} # todo: use a dictionary view (or a frozendict) instead of a copy

    def operators(self) -> list[OperatorRef]:
        return list(self._operators.keys())
    
    def remove_operator(self, op_ref: OperatorRef) -> None:
        if op_ref in self._operators:
            del self._operators[op_ref]
            # emit a signal or perform additional cleanup if necessary
            self.operators_removed.emit([op_ref])

    def update_operator(self, op_ref: OperatorRef, op_data: AbstractOperator) -> None:
        # todo: consider renaming to set_op
        if op_ref not in self._operators:
            raise MissingOperatorError(f"Operator {op_ref} does not exist in the graph.")
        self._operators[op_ref] = op_data
        self.operators_changed.emit([op_ref])

    def get_value(self, ref: OperatorRef) -> AbstractOperator | None:
        return self._operators.get(ref, None)