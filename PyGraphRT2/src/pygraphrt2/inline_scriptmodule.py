from types import FunctionType, ModuleType

from .registry import Registry
from typing import Any, ClassVar, Iterable, Callable
from qtpy.QtCore import Signal
from typing import Literal

import inspect
from types import MappingProxyType
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ParameterData:
    EMPTY: ClassVar[Any] = inspect.Parameter.empty
    name:str
    annotation: Any = EMPTY
    default: Any = EMPTY

    def __repr__(self):
        return f"ParameterData(name='{self.name}', annotation={self.annotation}, default={self.default})"



class OperatorUnavailableError(RuntimeError):
    """The referenced operator is absent from the evaluated script namespace."""

    def __init__(self, operator: "ScriptOperatorRef") -> None:
        self.operator = operator
        super().__init__(f"Operator {operator.name()!r} is unavailable")


@dataclass(frozen=True)
class ScriptOperatorRef:
    """A binding whose identity survives function removal and script errors.

    Availability follows the module's last evaluation. Nodes keep this reference
    while it is unavailable; assigning None to a node explicitly unbinds it.
    """

    _module: 'InlineScriptModule'
    _name: str

    def module(self) -> 'InlineScriptModule':
        return self._module

    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        """Whether the last evaluated namespace contains this operator."""
        return self._name in self._module._functions_cache

    def resolve(self) -> Callable[..., Any]:
        if not self.is_available():
            state = self._module.get_state()
            cause = state if isinstance(state, Exception) else None
            raise OperatorUnavailableError(self) from cause
        return self._module._functions_cache[self._name]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.resolve()(*args, **kwargs)

    # equality and hashing
    def __hash__(self) -> int:
        return hash((self._module, self._name))
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, ScriptOperatorRef):
            return False
        return self._module == other._module and self._name == other._name

    # signature
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
                param.annotation if param.annotation is not inspect.Parameter.empty else ParameterData.EMPTY,
                param.default if param.default is not inspect.Parameter.empty else ParameterData.EMPTY
                )

            params[name] = param_data
        return MappingProxyType(params)

    def get_line_number(self) -> int | None:
        return self._module._line_numbers.get(self._name, None)

    def get_return_type(self) -> type:
        sig = self.__func_sig()
        if sig:
            if sig.return_annotation is not inspect.Signature.empty:
                return sig.return_annotation
            else:
                return ParameterData.EMPTY #todo: this should be 'EMPTY', not 'Any' i think
        else:
            return ParameterData.EMPTY

class InlineScriptModule(Registry):
    scriptChanged = Signal(str)
    stateChanged = Signal()
    registry_invalidated = Signal()

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name)
        self._script = ""
        self._state: Literal["VALID"] | Exception | None = None
        self._functions_cache: dict[str, Callable] = {}
        self._line_numbers: dict[str, int] = {}
        self._evaluated_script = ""

    def set_script(self, script:str):
        self._script = script
        self.scriptChanged.emit(script)
        self.registry_invalidated.emit()

    def get_script(self) -> str:
        return self._script

    def get_state(self) -> Literal["VALID"] | Exception | None:
        return self._state

    def evaluate(self) -> None:
        """Commit a complete namespace, or expose the error with no stale operators."""
        try:
            functions = _get_all_callables_from_script(self._script, name="<script>")
        except Exception as error:
            self.__apply_functions({}, error)
            raise
        self.__apply_functions(functions, "VALID")

    def __apply_functions(self, 
        all_functions_from_script: dict[str, Callable], 
        new_state: Literal["VALID"] | Exception
    ) -> None:
        prev_names = self._functions_cache.keys()
        next_names = all_functions_from_script.keys()
        removed_names = sorted(prev_names - next_names)
        added_names = sorted(next_names - prev_names)
        # Function bodies can depend on changed globals, imports, or helpers.
        # Refresh every surviving binding from the same newly evaluated namespace.
        changed_names = sorted(prev_names & next_names)

        # update line numbers
        self._line_numbers = {
            name: func.__code__.co_firstlineno
            for name, func
            in all_functions_from_script.items()
            if hasattr(func, "__code__")
        }

        state_changed = self._state != new_state
        self._functions_cache = all_functions_from_script.copy()
        
        self._state = new_state

        if state_changed:
            self.stateChanged.emit()
        if removed_names:
            self.operators_removed.emit([ScriptOperatorRef(self, name) for name in removed_names])
        if added_names:
            self.operators_added.emit([ScriptOperatorRef(self, name) for name in added_names])
        if changed_names:
            self.operators_changed.emit([ScriptOperatorRef(self, name) for name in changed_names])
        self._evaluated_script = self._script

    def operators(self)->Iterable[Callable]:
        return [
            ScriptOperatorRef(self, name) 
            for name in self._functions_cache.keys()
        ]

    def get_operator_by_name(self, name: str) -> ScriptOperatorRef:
        if name not in self._functions_cache:
            raise KeyError(f"Operator {name!r} not found")
        return ScriptOperatorRef(self, name)

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
