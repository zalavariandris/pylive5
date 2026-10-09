from typing import Mapping, Any
from types import MappingProxyType
import sys
import inspect
from annotationlib import Format
from pathlib import Path

from .abstract_operator import AbstractOperator, ParameterData


class FunctionOperator(AbstractOperator):
    def __init__(self, func:callable):
        super().__init__()
        assert callable(func), f"func must be a callable function got{func}"
        assert hasattr(func, "__code__"), f"function with a __code__ attribute, got {func}"
        self._func = func

    def get_name(self) -> str:
        return self._func.__name__

    def get_module_name(self) -> str:
        return self._func.__module__ or ""

    def get_source_path(self) -> Path | None:
        filename = self._func.__code__.co_filename
        return None if filename.startswith("<") else Path(filename).resolve()

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

    def fingerprint(self) -> str:
        return f"{self._func.__module__}.{self._func.__qualname__}"

    def __hash__(self):
        return hash(self._func)

    def __eq__(self, other):
        if not isinstance(other, FunctionOperator):
            return False
        return self._func == other._func

    def __call__(self, *args, **kwargs) -> Any:
        return self._func(*args, **kwargs)
