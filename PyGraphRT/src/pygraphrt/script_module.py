from types import FunctionType, ModuleType
from typing import Iterable, Literal, Any
from qtpy.QtCore import Signal, QObject


from myutils.source_diff import ast_functions_diff

from .abstract_module_rt import (
    AbstractOperator,
    OperatorRef
)

from .inline_module import FunctionOperator

from .abstract_module_rt import AbstractModule

class RTModuleError(Exception):
    """Custom exception for runtime module errors."""


class ScriptEvaluationError(RTModuleError):
    """The script could not be compiled, executed, or inspected."""

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error: Exception = error


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
    except Exception as error:
        raise ScriptEvaluationError(error) from error

    # if __all__ export names is present, validate it before using
    _export_names: set[str] = set()
    if "__all__" in namespace:
        names_in_all = namespace["__all__"]
        if type(names_in_all) not in (list, tuple):
            raise ScriptEvaluationError(TypeError("__all__ must be a list or tuple of strings"))
        
        for key in names_in_all:
            if type(key) is not str:
                raise ScriptEvaluationError(TypeError("__all__ entries must be strings"))

        for key in names_in_all:
            if key not in namespace:
                raise ScriptEvaluationError(AttributeError(f"__all__ references undefined name {key!r}"))
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
        
        self._operators_cache: dict[str, FunctionOperator] = {}
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

        name: str | None = self.get_display_name()
        execution_name: str = name if name is not None else "<script>"
        new_state: Literal["VALID"] | Exception
        try:
            new_functions = _get_all_callables_from_script(script, name=execution_name)
        except ScriptEvaluationError as error:
            new_state = error.error
            new_functions = {}
        else:
            new_state = "VALID"

        prev_names = self._operators_cache.keys()
        next_names = new_functions.keys()
        removed_names = sorted(prev_names - next_names)
        added_names = sorted(next_names - prev_names)
        changed_names: list[str] = []
        if new_state == "VALID":
            functions_diff = ast_functions_diff(self._script, script)
            # AST names can include nested functions; exports are actual bindings.
            changed_names = sorted(prev_names & next_names & functions_diff.changed)

        # Prepare the entire update before committing; runtime bugs propagate.
        new_operators = self._operators_cache.copy()
        for name in removed_names:
            del new_operators[name]
        for name in changed_names + added_names:
            new_operators[name] = FunctionOperator(new_functions[name])

        state_changed = self._state != new_state
        self._operators_cache = new_operators
        self._script = script
        self._state = new_state

        if state_changed:
            self.state_changed.emit()
        if removed_names:
            self.operators_removed.emit([OperatorRef(self, name) for name in removed_names])
        if added_names:
            self.operators_added.emit([OperatorRef(self, name) for name in added_names])
        if changed_names:
            self.operators_changed.emit([OperatorRef(self, name) for name in changed_names])
        self.script_changed.emit()

    def get_state(self) -> Literal["VALID"] | Exception:
        """Return 'VALID' or the stored compilation, execution, or export error."""
        return self._state

    def operators(self) -> Iterable[OperatorRef]:
        return [
            OperatorRef(self, k) 
            for k in self._operators_cache.keys()
        ] # todo: use a dictionary view (or a frozendict) instead of a copy

    def get_operator(self, ref: OperatorRef) -> AbstractOperator | None:
        return self._operators_cache.get(ref.name, None)
