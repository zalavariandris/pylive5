from types import FunctionType, ModuleType

from myutils.source_diff import ast_functions_diff

from .registry import Registry
from typing import Any, Iterable, Callable
from qtpy.QtCore import Signal
from typing import Literal


class _ScriptOperatorRef:
    def __init__(self, module, name):
        self._module = module
        self._name = name

    def __hash__(self):
        return hash((self._module, self._name))

    def __eq__(self, other):
        if not isinstance(other, _ScriptOperatorRef):
            return False
        return self._module == other._module and self._name == other._name

    def __call__(self, *args, **kwargs):
        return self._module._functions_cache[self._name](*args, **kwargs)


class AsyncScriptModule(Registry):
    scriptChanged = Signal(str)
    stateChanged = Signal()

    def __init__(self):
        super().__init__()
        self._script = ""
        self._state:Literal["VALID", "ERROR"] | Exception = None
        self._functions_cache: dict[str, Callable] = {}
        self._line_numbers: dict[str, int] = {}
        self._evaluated_script = ""

    def set_script(self, script:str):
        self._script = script
        self.scriptChanged.emit(script)

    async def evaluate(self) -> None:
        #todo: add a force replace all functions, to replace all functions.
        #.   note: the current implementation might miss behavior changes in some situations.
        """update operators based on the current script and emit relevant signals"""
        execution_name: str = "<script>"
        new_state: Literal["VALID"] | Exception
        try:
            all_functions_from_script = _get_all_callables_from_script(self._script, name=execution_name)
            new_state = "VALID"
        except Exception as error:
            new_state = error
            all_functions_from_script = {}
            self._state = "ERROR"

        await self.__apply_functions(all_functions_from_script, new_state)

    async def __apply_functions(self, 
        all_functions_from_script: dict[str, Callable], 
        new_state: Literal["VALID"] | Exception
    ) -> None:
        prev_names = self._functions_cache.keys()
        next_names = all_functions_from_script.keys()
        removed_names = sorted(prev_names - next_names)
        added_names = sorted(next_names - prev_names)
        changed_names: list[str] = []
        if new_state == "VALID":
            functions_diff = ast_functions_diff(self._evaluated_script, self._script)
            # AST names can include nested functions; exports are actual bindings.
            changed_names = sorted(prev_names & next_names & functions_diff.changed)

        # update line numbers
        self._line_numbers = {
            name: func.__code__.co_firstlineno
            for name, func
            in all_functions_from_script.items()
            if hasattr(func, "__code__")
        }

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
            self.stateChanged.emit()
        if removed_names:
            self.operators_removed.emit([_ScriptOperatorRef(self, name) for name in removed_names])
        if added_names:
            self.operators_added.emit([_ScriptOperatorRef(self, name) for name in added_names])
        if changed_names:
            self.operators_changed.emit([_ScriptOperatorRef(self, name) for name in changed_names])
        self._evaluated_script = self._script

    def operators(self)->Iterable[Callable]:
        return [
            _ScriptOperatorRef(self, name) 
            for name in self._functions_cache.keys()
        ]

    def get_operator_by_name(self, name: str) -> _ScriptOperatorRef:
        if name not in self._functions_cache:
            raise KeyError(f"Operator {name!r} not found")
        return _ScriptOperatorRef(self, name)

def _get_all_callables_from_script(
    script: str, *, name: str
) -> dict[str, Callable]:
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

    code = compile(script, f"<script:{name}>", "exec")
    exec(code, namespace)


    # if __all__ export names is present, validate it before using
    _export_names: set[str] = set()
    if "__all__" in namespace:
        names_in_all = namespace["__all__"]
        if type(names_in_all) not in (list, tuple):
            raise ValueError("__all__ must be a list or tuple of strings")
        
        for key in names_in_all:
            if type(key) is not str:
                raise ValueError("__all__ entries must be strings")

        for key in names_in_all:
            if key not in namespace:
                raise ValueError(f"__all__ references undefined name {key!r}")
        _export_names = set(names_in_all)

    def is_exported(item: tuple[str, Any]) -> bool:
        """Check if the item is exported according to __all__."""
        key, _ = item
        return key in _export_names

    def is_public(item: tuple[str, Any]) -> bool:
        """Check if the item is a public name (does not start with an underscore)."""
        key, _ = item
        return type(key) is str and not key.startswith("_")

    def is_function(item: tuple[str, Any]) -> bool:
        """Check if the item is a function."""
        _, value = item
        return type(value) is FunctionType

    def is_callable(item: tuple[str, Any]) -> bool:
        """Check if the item is callable."""
        _, value = item
        return callable(value)

    def is_locally_defined(item: tuple[str, Any]) -> bool:
        """Check if the function is defined within the script module itself."""
        _, value = item
        return value.__module__ == name

    objects: Iterable[tuple[str, Any]] = namespace.items()
    objects = filter(is_callable, objects)
    if "__all__" in namespace:
        objects = filter(is_exported, objects)
    else:
        objects = filter(is_public, objects)
        objects = filter(is_locally_defined, objects)
    

    # if defined_only:
    #     objects = filter(is_locally_defined, objects)

    return dict(objects)