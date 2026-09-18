from pathlib import Path
from types import MappingProxyType
from typing import Hashable, Mapping

from qtpy.QtCore import Signal, Slot

from .abstract_module_rt import AbstractModuleRT
from .operator_rt import ParameterRT
from .operator_rt_ref import OperatorRTRef
import myqtx 
from .script_module_rt import ScriptModuleRT


class ImportModuleRT(AbstractModuleRT):
    """A module wrapping a ScriptModuleRT and a public file buffer.

    script_module owns script execution; file_binding owns open/save/reload,
    watching, and conflicts. Operator references exposed here belong to this
    module. Invalid file edits retain the last working runtime and emit
    script_failed. Accepted runtime edits update the buffer; saving is explicit.

    path is optional at construction: an untitled module can be created with no
    filename, then bound later via file_binding.save(path) (or open(path)).
    """

    script_changed = Signal()
    script_failed = Signal(object)

    def __init__(
        self, name: str, path: str | Path | None = None, *, watch: bool = True
    ):
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        super().__init__(name)

        self.file_binding = myqtx.FileBinding(path, watch=False, parent=self)
        # Construction raises immediately if the initial source cannot execute.
        self.script_module = ScriptModuleRT(
            name,
            self.file_binding.get_text(),
            filename=self._script_filename(),
        )
        self.script_module.setParent(self)
        self._operators: dict[str, OperatorRTRef] = {}
        self._sync_operators()

        self.file_binding.changed.connect(self._on_file_changed)
        self.script_module.script_changed.connect(self._on_script_changed)
        self.script_module.script_failed.connect(self.script_failed)
        self.script_module.operators_added.connect(self.operators_added)
        self.script_module.operators_removed.connect(self.operators_removed)
        self.script_module.operators_changed.connect(self.operators_changed)
        if watch:
            self.file_binding.start_watching()

    def _script_filename(self) -> str:
        path = self.file_binding.path()
        return str(path) if path is not None else ""

    def get_script(self) -> str:
        return self.script_module.get_script()

    def set_script(self, script: str) -> None:
        self.script_module.set_script(script, filename=self._script_filename())

    def save(self, path: str | Path | None = None, *, force: bool = False) -> bool:
        """Save the script buffer; pass path to assign a filename if untitled."""
        return self.file_binding.save(path, force=force)

    def operators(self) -> Mapping[str, OperatorRTRef]:
        return dict(self._operators)

    def get_operator(self, name: str) -> OperatorRTRef | None:
        return self._operators.get(name)

    def isValid(self, operator: OperatorRTRef) -> bool:
        return (
            isinstance(operator, OperatorRTRef)
            and operator.module() is self
            and operator.name() in self._operators
        )

    def get_parameters(self, operator: OperatorRTRef) -> MappingProxyType[str, ParameterRT]:
        if not self.isValid(operator):
            return MappingProxyType({})
        return self.script_module.get_parameters(self._wrapped_operator(operator))

    def fingerprint(self, operator: OperatorRTRef) -> Hashable:
        return self.script_module.fingerprint(self._wrapped_operator(operator))

    def call(self, op: OperatorRTRef, *args, **kwargs):
        return self.script_module.call(self._wrapped_operator(op), *args, **kwargs)

    def _wrapped_operator(self, operator: OperatorRTRef) -> OperatorRTRef:
        if not self.isValid(operator):
            raise ValueError(f"Operator {operator!r} is not available in module {self.name()!r}.")
        return self.script_module.get_operator(operator.name())

    def _sync_operators(self) -> None:
        self._operators = {
            key: self._operators[key] if key in self._operators else OperatorRTRef(self, key)
            for key in self.script_module.operators()
        }

    @Slot()
    def _on_file_changed(self) -> None:
        self.set_script(self.file_binding.get_text())

    @Slot()
    def _on_script_changed(self) -> None:
        # Publish a complete set of wrapper references before forwarding signals.
        self._sync_operators()
        self.file_binding.set_text(self.get_script())
        self.script_changed.emit()