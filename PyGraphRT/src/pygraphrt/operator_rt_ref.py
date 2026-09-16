from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .local_module_rt import LocalModuleRT

import weakref

class OperatorRTRef:
    def __init__(self, module: LocalModuleRT, key: str):
        self._module: weakref.ReferenceType[LocalModuleRT] = weakref.ref(module)
        self._key = key

    def key(self):
        return self._key

    def isValid(self) -> bool:
        return self._key in self._module()._functions

    def fingerprint(self):
        if self.isValid():
            func = self._module()._functions[self._key]
            return hash(func)
        else:
            return hash(("-INVALID-", self._key))

    def __call__(self, *args, **kwargs):
        if not self.isValid():
            raise ValueError(f"Operator {self._key} is not valid.")

        func = self._module()._functions[self._key]
        return func(*args, **kwargs)
