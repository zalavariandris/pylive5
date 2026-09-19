import inspect
from types import MappingProxyType
from typing import Any, Callable, Hashable, Mapping

from qtpy.QtCore import Signal

from .abstract_module_rt import AbstractModuleRT
from .operator_rt import ParameterRT
from .operator_rt_ref import OperatorRTRef
from ....myutils.src.myutils.source_diff import ast_functions_diff


def _get_all_functions_from_script(
    script: str, *, name: str, filename: str
) -> dict[str, Callable]:
    namespace: dict[str, Any] = {"__name__": name, "__package__": ""}
    if filename != "<string>":
        namespace["__file__"] = filename
    exec(compile(script, filename, "exec"), namespace)
    return {key: value for key, value in namespace.items() if callable(value)}


class ScriptModuleRT(AbstractModuleRT):
    """An editable script runtime exporting callable module-level bindings.

    Updates execute in a fresh shared namespace and commit before emitting signals.
    Operator change notifications use structural function differences; changes to
    globals and dependencies are not tracked by this analysis.
    """

    script_changed = Signal()
    script_failed = Signal(object)

    def __init__(self, name: str, script: str = "", *, filename: str = "<string>"):
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        if not isinstance(filename, str):
            raise TypeError("filename must be a string")
        super().__init__(name)
        self._script = script
        self._filename = filename
        self._functions = _get_all_functions_from_script(
            script, name=name, filename=self._filename
        )
        self._operators_cache = {
            key: OperatorRTRef(self, key) for key in self._functions
        }

    def get_script(self) -> str:
        return self._script

    def set_script(self, script: str, *, filename: str | None = None) -> None:
        """Apply source and optional filename, retaining accepted state on failure."""
        try:
            self._apply_script(script, filename=filename)
        except Exception as error:
            self.script_failed.emit(error)
            print(f"Failed to set script due to error: {error}")

    def _apply_script(self, script: str, *, filename: str | None = None) -> None:
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        if filename is None:
            filename = self._filename
        if not isinstance(filename, str):
            raise TypeError("filename must be a string")
        if script == self._script and filename == self._filename:
            return

        # Prepare the complete next state before notifying observers.
        functions = _get_all_functions_from_script(
            script, name=self.name(), filename=filename
        )
        functions_diff = ast_functions_diff(self._script, script)
        previous_names = self._functions.keys()
        next_names = functions.keys()
        removed = sorted(previous_names - next_names)
        added = sorted(next_names - previous_names)
        # AST names can include nested functions; exports are actual bindings.
        changed = sorted(previous_names & next_names & functions_diff.changed)
        operators = {
            key: self._operators_cache[key]
            if key in self._operators_cache else OperatorRTRef(self, key)
            for key in functions
        }

        self._script = script
        self._filename = filename
        self._functions = functions
        self._operators_cache = operators

        self.script_changed.emit()
        if removed:
            self.operators_removed.emit(removed)
        if added:
            self.operators_added.emit(added)
        if changed:
            self.operators_changed.emit(changed)

    def operators(self) -> Mapping[str, OperatorRTRef]:
        return dict(self._operators_cache)

    def get_operator(self, name: str) -> OperatorRTRef | None:
        return self._operators_cache.get(name)

    def isValid(self, operator: OperatorRTRef) -> bool:
        return (
            isinstance(operator, OperatorRTRef)
            and operator.module() is self
            and operator.name() in self._functions
        )

    def _get_function(self, operator: OperatorRTRef) -> Callable:
        if not self.isValid(operator):
            raise ValueError(f"Operator {operator!r} is not available in module {self.name()!r}.")
        return self._functions[operator.name()]

    def get_parameters(self, operator: OperatorRTRef) -> MappingProxyType[str, ParameterRT]:
        if not self.isValid(operator):
            return MappingProxyType({})

        signature = inspect.signature(self._get_function(operator))
        return MappingProxyType({
            parameter.name: ParameterRT(
                name=parameter.name,
                annotation=parameter.annotation,
                default=parameter.default,
            )
            for parameter in signature.parameters.values()
        })

    def fingerprint(self, operator: OperatorRTRef) -> Hashable:
        return hash((operator.name(), self._get_function(operator)))

    def call(self, op: OperatorRTRef, *args, **kwargs):
        return self._get_function(op)(*args, **kwargs)
