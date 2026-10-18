"""
Registry for managing script modules and their operators.
responsibility: ...
"""
from typing import Any

from qtpy.QtCore import (
    QObject, 
    Signal
)

from .script_module import ScriptModuleRT


class ModuleRegistry(QObject):
    modules_added = Signal(list)
    modules_removed = Signal(list)
    operators_added = Signal(list)
    operators_removed = Signal(list)
    operators_changed = Signal(list)

    def __init__(self, parent: QObject|None = None):
        super().__init__(parent=parent)
        self._modules: list[ScriptModuleRT] = []
        self._module_connections: dict[ScriptModuleRT, list[tuple[Any, Any]]] = {}

    def modules(self):
        return [module for module in self._modules]

    def add_module(self, module: ScriptModuleRT) -> None:
        if module not in self._modules:
            self._modules.append(module)
            self._make_module_connections(module)
            self.modules_added.emit([module])

    def find_module_by_name(self, name: str) -> ScriptModuleRT | None:
        for module in self._modules:
            if module.get_display_name() == name:
                return module
        return None

    def _make_module_connections(self, module: ScriptModuleRT) -> None:
        self._module_connections[module] = [
            (module.operators_added, self.operators_added),
            (module.operators_removed, self.operators_removed),
            (module.operators_changed, self.operators_changed),
        ]

        for signal, slot in self._module_connections[module]:
            signal.connect(slot)

    def remove_module(self, module: ScriptModuleRT) -> None:
        self._modules.remove(module)
        for signal, slot in self._module_connections.pop(module, []):
            signal.disconnect(slot)

        self.modules_removed.emit([module])
