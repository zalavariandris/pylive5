from pathlib import Path
from types import MappingProxyType
from typing import Hashable, Mapping

from pygraphrt2.graph_rt2 import AbstractOperator
from qtpy.QtCore import Signal, Slot, QObject

import myqtx 

from .abstract_module_rt import AbstractModule
from .script_module_rt import ScriptModuleRT


class ImportModuleRT(AbstractModule):
    """A module wrapping a ScriptModuleRT and a public file buffer.

    script_module owns script execution; file_binding owns open/save/reload,
    watching, and conflicts. Operator references exposed here belong to this
    module. Invalid file edits retain the last working runtime and emit
    script_failed. Accepted runtime edits update the buffer; saving is explicit.

    path is optional at construction: an untitled module can be created with no
    filename, then bound later via file_binding.save(path) (or open(path)).
    """

    script_changed = Signal()
    state_changed = Signal(object)

    def __init__(
        self, 
        name: str, 
        filepath: str|Path|None = None, 
        parent: QObject|None=None,
        *, 
        watch: bool = True
    ):
        super().__init__(name, parent=parent)

        self.file_binding = myqtx.FileBinding(filepath, watch=False, parent=self)

        self._script_module = ScriptModuleRT(
            name,
            script=self.file_binding.get_text(),
            parent=self
        )

        self._filename = self._script_filename()
        self._operators: dict[str, AbstractOperator] = {}
        self._sync_operators()

        self.file_binding.changed.connect(self._on_file_changed)
        self._script_module.script_changed.connect(self._on_script_changed)
        self._script_module.state_changed.connect(self.state_changed)
        self._script_module.operators_added.connect(self.operators_added)
        self._script_module.operators_removed.connect(self.operators_removed)
        self._script_module.operators_changed.connect(self.operators_changed)

        if watch:
            self.file_binding.start_watching()

    def _script_filename(self) -> str:
        path = self.file_binding.path()
        return str(path) if path is not None else ""

    def get_script(self) -> str:
        return self._script_module.get_script()

    def set_script(self, script: str) -> None:
        self._script_module.set_script(script)

    def save(self, path: str | Path | None = None, *, force: bool = False) -> bool:
        """Save the script buffer; pass path to assign a filename if untitled."""
        return self.file_binding.save(path, force=force)

    def operators(self) -> Mapping[str, AbstractOperator]:
        return dict(self._operators)

    def get_operator(self, name: str) -> AbstractOperator | None:
        return self._operators.get(name)

    @Slot()
    def _on_file_changed(self) -> None:
        self.set_script(self.file_binding.get_text())

    @Slot()
    def _on_script_changed(self) -> None:
        # Publish a complete set of wrapper references before forwarding signals.
        self.file_binding.set_text(self.get_script())
        self.script_changed.emit()