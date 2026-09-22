from types import ModuleType
from typing import Iterable, Literal, Any, Callable, Hashable, Mapping
from qtpy.QtCore import Signal, QObject


from myutils.source_diff import ast_functions_diff

from .abstract_module_rt import (
    AbstractOperator,
    OperatorRef
)

from .script_module import ScriptModuleRT


from pathlib import Path


class ImportModuleRT(ScriptModuleRT):
    """An editable script runtime exporting callable module-level bindings.

    Updates execute in a fresh shared namespace and commit before emitting signals.
    All operator signals carry lists of OperatorRef, including removed exports.
    Operator change notifications use structural function differences; changes to
    globals and dependencies are not tracked by this analysis.
    Tracebacks identify the script by its module name as <script:name>.
    """
    state_changed = Signal()
    script_changed = Signal()

    def __init__(self, path: str, parent:QObject | None = None):
        super().__init__(Path(path).stem, parent=parent)
        self._path = Path(path)

        self.reload()

    def reload(self):
        text = self._path.read_text()
        self.set_script(text)
        return text