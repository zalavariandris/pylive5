from pygraphrt.source_diff import ast_diff, FunctionsDiff
from qtpy.QtCore import QObject, Signal
import copy
from typing import Mapping

class ScriptModuleRT(QObject):
    script_changed = Signal()
    functions_removed = Signal(list) # list[str]
    functions_added = Signal(list) # list[str]
    functions_changed = Signal(list) # list[str]

    def __init__(self, script=""):
        super().__init__()
        assert isinstance(script, str)
        self._script = script

    def get_script(self) -> str:
        return copy.copy(self._script)

    def set_script(self, script: str):
        if script == self._script:
            return
        try:
            functions_diff:FunctionsDiff = ast_diff(self._script, script)
            self._script = script
            self.script_changed.emit()
            if functions_diff.removed:
                self.functions_removed.emit(list(functions_diff.removed))
            if functions_diff.added:
                self.functions_added.emit(list(functions_diff.added))
            if functions_diff.changed:
                self.functions_changed.emit(list(functions_diff.changed))

        except SyntaxError as e:
            print(f"Failed to set script due to syntax error: {e}")

        except Exception as e:
            print(f"Failed to set script due to error: {e}")

    def functions(self) -> Mapping[str, callable]:
        assert isinstance(self._script, str)
        if not self._script:
            return {}
        local_vars = {}
        exec(self._script, {}, local_vars)
        return {k: v for k, v in local_vars.items() if callable(v)}

    def get_function(self, name: str) -> callable | None:
        return self.functions().get(name)
