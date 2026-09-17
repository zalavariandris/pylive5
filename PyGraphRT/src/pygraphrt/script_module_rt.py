import inspect
from types import MappingProxyType

from pygraphrt.operator_rt import ParameterRT
from pygraphrt.operator_rt_ref import OperatorRTRef
from pygraphrt.source_diff import ast_functions_diff, FunctionsDiff
from qtpy.QtCore import QObject, Signal
import copy
from typing import TYPE_CHECKING, Any, Callable, Hashable, Mapping


from .abstract_module_rt import AbstractModuleRT

if TYPE_CHECKING:
    from .graph_rt import GraphRT


def _get_all_functions_from_script(script: str) -> Mapping[str, Callable]:
    assert isinstance(script, str)
    if not script:
        return {}
    local_vars:dict[str, Any] = {}
    exec(script, {}, local_vars)
    return {k: v for k, v in local_vars.items() if callable(v)}

class ScriptModuleRT(AbstractModuleRT):
    script_changed = Signal()

    def __init__(self, graph: GraphRT, script=""):
        super().__init__(graph)
        assert isinstance(script, str)
        self._script = script
        self._functions: dict[str, Callable] = _get_all_functions_from_script(script)
        self._operators_cache: dict[str, OperatorRTRef] = {key: OperatorRTRef(self, key) for key in self._functions}

    def get_script(self) -> str:
        return copy.copy(self._script)

    def set_script(self, script: str):
        if script == self._script:
            return
        try:
            self._functions = _get_all_functions_from_script(script)
            functions_diff:FunctionsDiff = ast_functions_diff(self._script, script)
            self._script = script
            self.script_changed.emit()
            if functions_diff.removed:
                removed_keys:list[str] = list(functions_diff.removed)
                for key in removed_keys:
                    if key in self._operators_cache:
                        del self._operators_cache[key]
                self.operators_removed.emit(removed_keys)

            if functions_diff.added:
                added_keys:list[str] = list(functions_diff.added)
                for key in added_keys:
                    if key in self._operators_cache:
                        self._operators_cache[key] = OperatorRTRef(self, key)
                self.operators_added.emit(added_keys)

            if functions_diff.changed:
                changed_keys:list[str] = list(functions_diff.changed)
                self.operators_changed.emit(changed_keys)

        except SyntaxError as e:
            print(f"Failed to set script due to syntax error: {e}")

        except Exception as e:
            print(f"Failed to set script due to error: {e}")

    def operators(self) -> Mapping[str, OperatorRTRef]:
        return {
            k: v 
            for k, v in self._operators_cache.items()
        }

    def get_operator(self, name: str) -> OperatorRTRef | None:
        return self._operators_cache.get(name)

    def isValid(self, operator: OperatorRTRef) -> bool:
        return operator._key in self._operators_cache

    def get_parameters(self, operator: OperatorRTRef) -> MappingProxyType[str, ParameterRT]:
        if operator._key not in self._operators_cache:
            return MappingProxyType({})
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

    def fingerprint(self, operator: OperatorRTRef) -> Hashable:
        key = operator._key
        return hash((key, self._functions[key]))

    def call(self, op: OperatorRTRef, *args, **kwargs):
        func = self._functions.get(op._key)
        if func is None:
            raise ValueError(f"Operator {op._key} not found in script.")
        return func(*args, **kwargs)