"""Runtime representation of a script module.
"""

from types import MappingProxyType
from typing import Callable, Any, Mapping
import inspect
from pathlib import Path



from .abstract_module_rt import (
    AbstractOperator,
    ParameterData
)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .script_module import ScriptModuleRT


class ScriptOperatorRef(AbstractOperator):
    """Represents an operator within a ScriptModule."""
    def __init__(self, module: 'ScriptModuleRT', name: str):
        super().__init__()
        self._module = module
        self._name = name

    def get_name(self) -> str:
        return self._name

    def get_module(self) -> 'ScriptModuleRT':
        return self._module

    def get_module_name(self) -> str:
        func = self._module._functions_cache.get(self._name)
        return (func.__module__ or "") if func is not None else ""

    def get_source_path(self) -> Path | None:
        return self._module.get_source_path()

    def __str__(self) -> str:
        return f"Op({self._module.get_display_name()}.{self._name})"

    def get_callable(self) -> Callable[..., Any]:
        #todo: consider making all operators selfcontained objects. 
        return self._module._functions_cache[self._name]

    def fingerprint(self) -> int:
        # todo: review if this is sufficient for fingerprinting functions
        if func:=self._module._functions_cache.get(self._name, None):
            return hash((self._name, func)) 
        else:
            return hash((self._name, None))

    def __func_sig(self)->inspect.Signature|None:
        func = self._module._functions_cache.get(self._name, None)
        if func is None:
            return None

        return inspect.signature(func)

    def get_parameters(self) -> Mapping[str, ParameterData]:
        sig = self.__func_sig()
        if sig is None:
            return MappingProxyType({})
        params = {}
        for name, param in sig.parameters.items():
            param_data = ParameterData(
                name, 
                param.annotation if param.annotation is not inspect.Parameter.empty else ParameterData._empty,
                param.default if param.default is not inspect.Parameter.empty else ParameterData._empty
                )

            params[name] = param_data
        return MappingProxyType(params)

    def get_line_number(self) -> int | None:
        return self._module._line_numbers.get(self._name, None)

    def get_return_type(self) -> type|Any:
        sig = self.__func_sig()
        if sig:
            if sig.return_annotation is not inspect.Signature.empty:
                return sig.return_annotation
            else:
                return Any #todo: this should be 'EMPTY', not 'Any' i think
        else:
            return Any

    def __call__(self, *args, **kwargs):
        func = self._module._functions_cache[self._name]
        return func(*args, **kwargs)

    def __hash__(self) -> int:
        return hash((self._module, self._name))
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, ScriptOperatorRef):
            return False
        return self._module == other._module and self._name == other._name
