from qtpy.QtCore import (
    QObject, 
    Signal
)

from .inline_module import InlineModuleRT
from .import_module import ImportModuleRT
from .script_module import ScriptModuleRT


class ScriptModuleRegistry(QObject):
    modules_added = Signal(list)
    modules_removed = Signal(list)
    modules_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self._modules: list[ScriptModuleRT] = []

    def modules(self):
        return [module for module in self._modules]

    def add_module(self, module: ScriptModuleRT) -> None:
        if module not in self._modules:
            self._modules.append(module)
            self.modules_added.emit([module])

    # def import_module(self, path:str) -> None:
    #     module = ImportModuleRT(path)
    #     if module not in self._modules:
    #         self._modules.append(module)
    #         self.modules_added.emit([module])

    def remove_module(self, module: ScriptModuleRT) -> None:
        self._modules.remove(module)
        self.modules_removed.emit([module])
