from annotationlib import Format
from collections.abc import Callable
from importlib.metadata.diagnose import inspect
import sys
from types import FunctionType, MappingProxyType, ModuleType
from typing import Iterable, Literal, Any, Mapping
from qtpy.QtCore import Signal, QObject


from myutils.source_diff import ast_functions_diff

from .abstract_module_rt import (
    AbstractOperator,
    OperatorRef,
    ParameterData
)

from .inline_module import FunctionOperator

from .abstract_module_rt import AbstractModule

from .errors import ModuleError, ScriptSyntaxError
from .errors import ScriptEvaluationError


def _get_all_callables_from_script(
    script: str, *, name: str, defined_only: bool = True
) -> dict[str, FunctionType]:
    """Collect Python functions explicitly present in the script namespace.

    Args:
        script: The Python script source code.
        name: The name to assign to the script module.
        defined_only: If True, only include functions defined in the script itself.

    Returns:
        A dictionary mapping function names to function objects.

    Raises:
        ScriptEvaluationError: If the script cannot be compiled or executed.
    """

    module = ModuleType(name)
    module.__package__ = ""
    namespace: dict[str, Any] = module.__dict__
    try:
        code = compile(script, f"<script:{name}>", "exec")
        exec(code, namespace)

    except SyntaxError as error:
        raise ScriptSyntaxError(str(error)) from error
    
    except Exception as error:
        raise ScriptEvaluationError(str(error)) from error

    # if __all__ export names is present, validate it before using
    _export_names: set[str] = set()
    if "__all__" in namespace:
        names_in_all = namespace["__all__"]
        if type(names_in_all) not in (list, tuple):
            raise ScriptEvaluationError("__all__ must be a list or tuple of strings")
        
        for key in names_in_all:
            if type(key) is not str:
                raise ScriptEvaluationError("__all__ entries must be strings")

        for key in names_in_all:
            if key not in namespace:
                raise ScriptEvaluationError(f"__all__ references undefined name {key!r}")
        _export_names = set(names_in_all)

    def is_exported(item: tuple[str, Any]) -> bool:
        key, _ = item
        return key in _export_names

    def is_public(item: tuple[str, Any]) -> bool:
        key, _ = item
        return type(key) is str and not key.startswith("_")

    def is_function(item: tuple[str, Any]) -> bool:
        _, value = item
        return type(value) is FunctionType

    def is_locally_defined(item: tuple[str, Any]) -> bool:
        _, value = item
        return value.__module__ == name

    objects: Iterable[tuple[str, Any]] = namespace.items()
    if "__all__" in namespace:
        objects = filter(is_exported, objects)
    else:
        objects = filter(is_public, objects)
    objects = filter(is_function, objects)
    if defined_only:
        objects = filter(is_locally_defined, objects)

    return dict(objects)


class ScriptOperatorRef(AbstractOperator):
    """Represents an operator within a ScriptModule."""
    def __init__(self, module: ScriptModuleRT, name: str):
        super().__init__()
        self._module = module
        self._name = name

    def fingerprint(self) -> int:
        func = self._module._functions_cache[self._name]
        return hash(func) # review if this is sufficient for fingerprinting functions

    def __func_sig(self):
        func = self._module._functions_cache[self._name]
        # Live edits can leave annotation names unfinished (e.g. s instead of str).
        if sys.version_info >= (3, 14):
            return inspect.signature(func, annotation_format=Format.FORWARDREF)
        return inspect.signature(func)

    def get_parameters(self) -> Mapping[str, ParameterData]:
        sig = self.__func_sig()
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
        sig = self.__func_sig()
        return sig.return_annotation if sig.return_annotation is not inspect.Signature.empty else Any

    def __call__(self, *args, **kwargs):
        func = self._module._functions_cache[self._name]
        return func(*args, **kwargs)


class ScriptModuleRT(AbstractModule):
    """An editable script runtime exporting callable module-level bindings.

    Updates execute in a fresh shared namespace and commit before emitting signals.
    All operator signals carry lists of OperatorRef, including removed exports.
    Operator change notifications use structural function differences; changes to
    globals and dependencies are not tracked by this analysis.
    Tracebacks identify the script by its module name as <script:name>.
    """
    state_changed = Signal()
    script_changed = Signal()

    def __init__(self, name: str|None=None, parent:QObject | None = None):
        if not isinstance(name, (str, type(None))):
            raise TypeError("name must be a string or None")
        
        super().__init__(name, parent=parent)
        
        self._functions_cache: dict[str, FunctionType] = {}
        self._evaluated_script: str = "" # used to track the last successfully evaluated script. necessary to determine dependency changes in the code itself.
        self._script = ""
        self._state: Literal["VALID"] | Exception = "VALID"

    def get_script(self) -> str:
        return self._script

    def set_script(self, script: str) -> None:
        """Store source and report script errors through state and change signals.

        Invalid arguments and runtime implementation errors propagate. Script
        errors commit the source and clear operators so the source stays editable.
        """
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        
        if script == self._script:
            return
        
        self._script = script
        self.script_changed.emit()
        self._evaluate()
        
    def _evaluate(self) -> None:
        """update operators based on the current script and emit relevant signals"""
        name: str | None = self.get_display_name()
        execution_name: str = name if name is not None else "<script>"
        new_state: Literal["VALID"] | Exception
        try:
            all_functions_from_script = _get_all_callables_from_script(self._script, name=execution_name)
        except ScriptEvaluationError as error:
            new_state = error
            all_functions_from_script = {}
        except ModuleError as error:
            new_state = error
            all_functions_from_script = {}
        else:
            new_state = "VALID"

        prev_names = self._functions_cache.keys()
        next_names = all_functions_from_script.keys()
        removed_names = sorted(prev_names - next_names)
        added_names = sorted(next_names - prev_names)
        changed_names: list[str] = []
        if new_state == "VALID":
            functions_diff = ast_functions_diff(self._evaluated_script, self._script)
            # AST names can include nested functions; exports are actual bindings.
            changed_names = sorted(prev_names & next_names & functions_diff.changed)

        # Prepare the entire update before committing; runtime bugs propagate.
        current_functions = self._functions_cache.copy()
        for name in removed_names:
            del current_functions[name]
        for name in changed_names + added_names:
            current_functions[name] = all_functions_from_script[name]

        state_changed = self._state != new_state
        self._functions_cache = current_functions
        self._state = new_state

        if state_changed:
            self.state_changed.emit()
        if removed_names:
            self.operators_removed.emit([OperatorRef(self, name) for name in removed_names])
        if added_names:
            self.operators_added.emit([OperatorRef(self, name) for name in added_names])
        if changed_names:
            self.operators_changed.emit([OperatorRef(self, name) for name in changed_names])
        self._evaluated_script = self._script
        print("script evaluated")
        
    def get_state(self) -> Literal["VALID"] | Exception:
        """Return 'VALID' or the stored compilation, execution, or export error."""
        return self._state

    def operators(self) -> Iterable[OperatorRef]:
        return [
            OperatorRef(self, k) 
            for k in self._functions_cache.keys()
        ] # todo: use a dictionary view (or a frozendict) instead of a copy

    # #todo: deprecate. the operator reference is resposible to call 
    # # the actual function, that is owned by the module
    # def get_operator(self, ref: OperatorRef, default=None) -> AbstractOperator | None:
    #     try:
    #         func = self._functions_cache[ref.name]
    #         return FunctionOperator(func)
    #     except KeyError:
    #         return None

    def get_operator_by_name(self, name: str, default=None) -> OperatorRef | None:
        if name in self._functions_cache:
            return OperatorRef(self, name)
        return default

    def __getitem__(self, key: OperatorRef) -> AbstractOperator:
        try:
            func = self._functions_cache[key.name]
            return FunctionOperator(func)
        except KeyError as err:
            raise ModuleError(f"Operator {key.name!r} not found", self) from err
        
