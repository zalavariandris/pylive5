from .abstract_module_rt import (
    AbstractOperator,
    AbstractModule,
    OperatorRef,
    ParameterData,
)
from types import MappingProxyType
from typing import Callable, Mapping, Any
import inspect
import sys

if sys.version_info >= (3, 14):
    from annotationlib import Format

from qtpy.QtCore import QObject

class OperatorExistsError(Exception):
    """Raised when attempting to create an operator that already exists."""
    pass

class MissingOperatorError(Exception):
    pass

class FunctionOperator(AbstractOperator):
    def __init__(self, func:callable):
        super().__init__()
        assert callable(func) and hasattr(func, "__code__"), "func must be a callable function with a __code__ attribute"
        self._func = func

    def _signature(self):
        # Live edits can leave annotation names unfinished (e.g. s instead of str).
        if sys.version_info >= (3, 14):
            return inspect.signature(self._func, annotation_format=Format.FORWARDREF)
        return inspect.signature(self._func)

    def get_parameters(self) -> Mapping[str, ParameterData]:
        sig = self._signature()
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
        sig = self._signature()
        return sig.return_annotation if sig.return_annotation is not inspect.Signature.empty else Any

    def __call__(self, *args, **kwargs) -> Any:
        return self._func(*args, **kwargs)

    

class InlineModuleRT(AbstractModule):
    """An editable script runtime exporting callable module-level bindings.

    Updates execute in a fresh shared namespace and commit before emitting signals.
    Operator change notifications use structural function differences; changes to
    globals and dependencies are not tracked by this analysis.
    Tracebacks identify the script by its module name as <script:name>.
    """

    def __init__(self, parent:QObject | None = None):
        super().__init__("_inline_", parent=parent)

        self._operators:dict[OperatorRef, FunctionOperator] = dict()

    def operators(self) -> list[OperatorRef]:
        return list(self._operators.keys())

    def op(self) -> Callable[[Callable], OperatorRef]:
        def decorator(func: Callable) -> OperatorRef:
            # assert that func is not simply a callable, but a function
            assert callable(func) and hasattr(func, "__code__"), "func must be a callable function with a __code__ attribute"
            
            ref = OperatorRef(self, func.__name__)

            if ref in self._operators:
                self._update_operator(ref, FunctionOperator(func))
            else:
                ref = self._create_operator(func)

            return ref
        return decorator

    def _create_operator(self, func: Callable) -> OperatorRef:
        assert callable(func) and hasattr(func, "__code__"), "func must be a callable function with a __code__ attribute"
        ref = OperatorRef(self, func.__name__)

        if ref in self._operators:
            raise OperatorExistsError(f"Operator {ref} already exists.")
        
        data = FunctionOperator(func)
        self._operators[ref] = data
        self.operators_added.emit([ref])
        return ref

    def _update_operator(self, op_ref: OperatorRef, func: callable) -> None:
        assert callable(func) and hasattr(func, "__code__"), "func must be a callable function with a __code__ attribute"
        # todo: consider renaming to set_op
        if op_ref not in self._operators:
            raise MissingOperatorError(f"Operator {op_ref} does not exist in the graph.")
        self._operators[op_ref] = FunctionOperator(func)
        self.operators_changed.emit([op_ref])
    
    def delete_operator(self, op_ref: OperatorRef) -> None:
        if op_ref in self._operators:
            del self._operators[op_ref]
            # emit a signal or perform additional cleanup if necessary
            self.operators_removed.emit([op_ref])

    def get_operator(self, ref: OperatorRef) -> AbstractOperator | None:
        return self._operators.get(ref, None)
