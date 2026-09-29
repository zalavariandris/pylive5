"""
Registry for managing script modules and their operators.
responsibility: ...
"""
from typing import Any

from qtpy.QtCore import (
    QObject, 
    Signal
)

# from .inline_module import InlineModuleRT
from .import_module import ImportModuleRT
from .script_module import ScriptModuleRT


class ModuleRegistry(QObject):
    modules_added = Signal(list)
    modules_removed = Signal(list)
    operators_added = Signal(list)
    operators_removed = Signal(list)
    operators_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self._modules: list[ScriptModuleRT] = []
        self._module_connections: dict[ScriptModuleRT, list[tuple[Any, Any]]] = {}

    def modules(self):
        return [module for module in self._modules]

    def add_module(self, module: ScriptModuleRT) -> None:
        if module not in self._modules:
            self._modules.append(module)
            self._make_module_connections(module)
            self.modules_added.emit([module])

    def _make_module_connections(self, module: ScriptModuleRT) -> None:
        self._module_connections[module] = [
            (module.operators_added, self.operators_added),
            (module.operators_removed, self.operators_removed),
            (module.operators_changed, self.operators_changed),
        ]

        for signal, slot in self._module_connections[module]:
            signal.connect(slot)

    # def import_module(self, path:str) -> None:
    #     module = ImportModuleRT(path)
    #     if module not in self._modules:
    #         self._modules.append(module)
    #         self.modules_added.emit([module])

    def remove_module(self, module: ScriptModuleRT) -> None:
        self._modules.remove(module)
        for signal, slot in self._module_connections.pop(module, []):
            signal.disconnect(slot)

        self.modules_removed.emit([module])
