"""Runtime representation of a script module.
"""


from collections.abc import Mapping
from types import FunctionType, MappingProxyType, ModuleType
from dataclasses import dataclass
import concurrent
import weakref
from qtpy.QtCore import QRunnable, QThreadPool
from typing import Callable, ClassVar, Iterable, Literal, Any, override
import inspect
from pathlib import Path
from qtpy.QtCore import Signal, QObject
from myutils.source_diff import ast_functions_diff
from .errors import ModuleError, ScriptSyntaxError
from .errors import ScriptEvaluationError

from .registry import Registry

def _get_all_callables_from_script(
    script: str, *, name: str
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

from concurrent.futures import Future

class _ScriptEvaluationRunnable(QRunnable):
    def __init__(self, script: str, name: str, future: Future[dict[str, FunctionType]]) -> None:
        super().__init__()

        self._script = script
        self._name = name
        self._future = future

    def run(self) -> None:
        if not self._future.set_running_or_notify_cancel():
            return

        try:
            print(f"Evaluating script {self._name}...")
            results = _get_all_callables_from_script(self._script, name=self._name)
            print(f"Script {self._name} evaluated successfully.")
        except Exception as error:
            self._future.set_exception(error)
        else:
            self._future.set_result(results)


class FunctionRunnable(QRunnable):
    def __init__(self, func: FunctionType) -> None:
        super().__init__()
        self._func = func

    def run(self) -> None:
        if not self._future.set_running_or_notify_cancel():
            return
        try:
            result = self._func()
        except BaseException as error:
            self._future.set_exception(error)
        else:
            self._future.set_result(result)


@dataclass(frozen=True)
class ParameterData:
    EMPTY: ClassVar[Any] = inspect.Parameter.empty
    name:str
    annotation: Any = EMPTY
    default: Any = EMPTY

    def __repr__(self):
        return f"ParameterData(name='{self.name}', annotation={self.annotation}, default={self.default})"

    

@dataclass(frozen=True)
class ScriptOperatorRef:
    """A stable reference that can outlive a missing or broken script function."""

    _module: 'ScriptModule'
    _name: str

    def module(self) -> 'ScriptModule':
        return self._module

    def name(self) -> str:
        return self._name

    def resolve(self) -> FunctionType:
        return self._module._functions_cache[self._name]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        func = self._module._functions_cache[self._name]
        return func(*args, **kwargs)

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


class ScriptModule(Registry):
    """An editable script provides Operators
    """
    state_changed = Signal()
    script_changed = Signal()

    def __init__(self, name: str|None=None, parent:QObject | None = None):
        super().__init__(name, parent=parent)
        if not isinstance(name, (str, type(None))):
            raise TypeError("name must be a string or None")
        
        self._functions_cache: dict[str, FunctionType] = {}
        self._line_numbers: dict[str, int] = {}
        self._evaluated_script: str = "" # used to track the last successfully evaluated script. necessary to determine dependency changes in the code itself.
        self._script = ""
        self._state: Literal["VALID"] | Exception = "VALID"

    def get_source(self) -> str:
        return self._script

    def get_source_path(self) -> Path | None:
        return None

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

    def __apply_functions(self, all_functions_from_script: dict[str, FunctionType], new_state: Literal["VALID"] | Exception) -> None:
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
            self.state_changed.emit()
        if removed_names:
            self.operators_removed.emit([ScriptOperatorRef(self, name) for name in removed_names])
        if added_names:
            self.operators_added.emit([ScriptOperatorRef(self, name) for name in added_names])
        if changed_names:
            self.operators_changed.emit([ScriptOperatorRef(self, name) for name in changed_names])
        self._evaluated_script = self._script

    def evaluate(self) -> None:
        #todo: add a force replace all functions, to replace all functions.
        #.   note: the current implementation might miss behavior changes in some situations.
        """update operators based on the current script and emit relevant signals"""
        name: str | None = self.name()
        execution_name: str = name if name is not None else "<script>"
        new_state: Literal["VALID"] | Exception
        try:
            all_functions_from_script = _get_all_callables_from_script(self._script, name=execution_name)

        except ScriptEvaluationError as error:
            new_state = error
            all_functions_from_script = {}
            # indicate error by setting the state to the caught exception
            self._state = new_state

        except ModuleError as error:
            new_state = error
            all_functions_from_script = {}
            # indicate error by setting the state to the caught exception
            self._state = new_state

        else:
            new_state = "VALID"

        self.__apply_functions(all_functions_from_script, new_state)

    def request_evaluate(self) -> concurrent.futures.Future:
        """Request the module to evaluate its current script.
        returns """
        self._pool:QThreadPool = QThreadPool.globalInstance()
        future: concurrent.futures.Future = concurrent.futures.Future()
        name: str | None = self.name()
        execution_name: str = name if name is not None else "<script>"
        runnable = _ScriptEvaluationRunnable(self._script, execution_name, future)
        self._pool.start(runnable)

        weak_self = weakref.ref(self)
        def on_done(fut: concurrent.futures.Future) -> None:
            # this is running on the worker thread
            try:
                all_the_new_functions = fut.result()
                self_ref = weak_self()
                if self_ref is not None:
                    self_ref.__apply_functions(all_the_new_functions, "VALID")
                print(all_the_new_functions)
            except Exception as e:
                # fut.result will rerais the exception if occured during script evaluation
                import traceback
                traceback.print_exc()
                self_ref = weak_self()
                if self_ref is not None:
                    self_ref._state = e
                    self_ref.__apply_functions(dict(), "VALID")
        future.add_done_callback(on_done)
        return future
        
    def get_status(self) -> Literal["VALID"] | Exception:
        """Return 'VALID' or the stored compilation, execution, or export error."""
        return self._state

    @override
    def operators(self) -> Iterable[ScriptOperatorRef]:
        return [
            ScriptOperatorRef(self, k) 
            for k in self._functions_cache.keys()
        ] # todo: use a dictionary view (or a frozendict) instead of a copy
    
    def get_operator_by_name(self, name: str, default=None) -> ScriptOperatorRef | None:
        if name in self._functions_cache:
            return ScriptOperatorRef(self, name)
        return default

    def create_placeholder_operator(self, name: str) -> ScriptOperatorRef:
        return ScriptOperatorRef(self, name)
