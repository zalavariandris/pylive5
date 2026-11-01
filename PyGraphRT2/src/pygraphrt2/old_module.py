"""Runtime representation of a script module.
"""


from types import FunctionType, ModuleType
import concurrent
import weakref

from typing import Callable, Iterable, Literal, Any
import inspect
from pathlib import Path
from qtpy.QtCore import Signal, QObject



class OperatorRef:
    """Represents an operator within a ScriptModule."""
    def __init__(self, module: 'Module', name: str):
        super().__init__()
        self._module = module
        self._name = name

    def name(self) -> str:
        return self._name

    def module(self) -> 'Module':
        return self._module

    def __str__(self) -> str:
        return f"Op({self._module.get_display_name()}.{self._name})"

    def resolve(self) -> Callable[..., Any]:
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
        if not isinstance(other, OperatorRef):
            return False
        return self._module == other._module and self._name == other._name


class Module(QObject):
    """
    A container for Operators
    """
    operators_added = Signal()
    operators_removed = Signal()
    operators_changed = Signal()

    def __init__(self, name: str|None=None, parent:QObject | None = None):
        super().__init__(name, parent=parent)
        if not isinstance(name, (str, type(None))):
            raise TypeError("name must be a string or None")
        
        self._functions_cache: dict[str, FunctionType] = {}
        self._line_numbers: dict[str, int] = {}
        self._evaluated_script: str = "" # used to track the last successfully evaluated script. necessary to determine dependency changes in the code itself.
        self._script = ""
        self._state: Literal["VALID"] | Exception = "VALID"

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
        name: str | None = self.get_display_name()
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
        name: str | None = self.get_display_name()
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
