from types import MappingProxyType
from typing import Iterable, Literal, Any, Callable, Hashable, Mapping
from qtpy.QtCore import Signal, QObject


from myutils.source_diff import ast_functions_diff

from .abstract_module_rt import (
    AbstractOperator,
    OperatorRef
)

from .local_module import FunctionOperator

from .abstract_module_rt import AbstractModule


def _get_all_functions_from_script(
    script: str, *, name: str
) -> dict[str, Callable]:
    """Return exported functions and the script validity state."""

    namespace: dict[str, Any] = {"__name__": name, "__package__": ""}
    code = compile(script, f"<script:{name}>", "exec")
    exec(code, namespace)
    return {key: value for key, value in namespace.items() if callable(value)}


class ScriptModuleRT(AbstractModule):
    """An editable script runtime exporting callable module-level bindings.

    Updates execute in a fresh shared namespace and commit before emitting signals.
    Operator change notifications use structural function differences; changes to
    globals and dependencies are not tracked by this analysis.
    Tracebacks identify the script by its module name as <script:name>.
    """
    state_changed = Signal()
    script_changed = Signal()
    script_failed = Signal(object)

    def __init__(self, name: str, script: str = "", parent:QObject | None = None):
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        
        super().__init__(name, parent=parent)
        self._script = script

        # collect functions from the initial script
        self._state: str|BaseException = "VALID" # consider introducing an enum for states. also a not initialized state
        try:
            new_functions = _get_all_functions_from_script(script, name=name)

            self._state: str|BaseException = "VALID" # todo: refine typehint
        except BaseException as error:
            new_functions = {}
            if self._state != error:
                self._state = error
        
        self._operators_cache = {
            key: FunctionOperator(func) 
            for key, func in new_functions.items()
        }

    def get_state(self) -> str|BaseException:
        """Validity of the stored script: valid (including empty) or syntax_error.

        Other execution errors propagate without committing an update.
        """
        return self._state

    def get_script(self) -> str:
        return self._script

    def set_script(self, script: str) -> None:
        """Store source, clearing operators and recording the exception on failure."""

        self._apply_script(script)

    def _apply_script(self, script: str) -> None:
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        
        
        if script == self._script:
            return

        # Find the added and removed functions based on the new script
        # note: we compare the new script with the currently cached operators
        #       instead of using the ast diff alone. Even though ideailly this
        #       is redundant with the AST diff, it provides a more reliable
        #       reflection of the actual operators in the module.
        #       This ensures that we accurately track which functions have been 
        #       added, removed, or changed, rather than relying solely on the 
        #       AST diff.

        # Compile first so syntax errors also carry the module's traceback name.


        try:
            new_functions = _get_all_functions_from_script(script, name=self.name())

            functions_diff = ast_functions_diff(self._script, script)
            
            # Determine the previous and next sets of operator names
            prev_names = self._operators_cache.keys()
            next_names = new_functions.keys()
            removed_names = sorted(prev_names - next_names)
            added_names =   sorted(next_names - prev_names)
            # AST names can include nested functions; exports are actual bindings.
            changed_names = sorted(prev_names & next_names & functions_diff.changed)
    
            # update the operator cache
            for name in removed_names:
                self._operators_cache.pop(name, None)
            for name in changed_names:
                self._operators_cache[name] = FunctionOperator(new_functions[name])
            for name in added_names:
                self._operators_cache[name] = FunctionOperator(new_functions[name])
    
            # # replace  the operator_cache
            # new_operators = {
            #     key: self._operators_cache[key] if key in self._operators_cache else OperatorRTRef(self, key)
            #     for key in new_functions
            # }
            # self._operators_cache = new_operators
    
            # update the cached script
            self._script = script
            if self._state != "VALID":
                self._state = "VALID"
                self.state_changed.emit()
            
            if removed_names:
                self.operators_removed.emit(removed_names)
    
            if added_names:
                self.operators_added.emit(added_names)
    
            if changed_names:
                self.operators_changed.emit(changed_names)

        except BaseException as error:
            removed = list(self._operators_cache.keys())
            self._operators_cache.clear()
            self._script = script
            if self._state != error:
                self._state = error
                self.state_changed.emit()
            if removed:
                self.operators_removed.emit(removed)

        self.script_changed.emit()

    def operators(self) -> Iterable[OperatorRef]:
        return [
            OperatorRef(self, k) 
            for k in self._operators_cache.keys()
        ] # todo: use a dictionary view (or a frozendict) instead of a copy

    def get_value(self, ref: OperatorRef) -> AbstractOperator | None:
        return self._operators_cache.get(ref.name, None)