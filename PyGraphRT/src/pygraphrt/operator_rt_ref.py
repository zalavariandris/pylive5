from __future__ import annotations
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Mapping

if TYPE_CHECKING:
    from .local_module_rt import LocalModuleRT
    from pygraphrt.operator_rt import ParameterRT

import weakref



class OperatorRTRef:
    def __init__(self, module: LocalModuleRT, key: str):
        self._module: weakref.ReferenceType[LocalModuleRT] = weakref.ref(module)
        self._key = key

    def key(self):
        return self._key

    def isValid(self) -> bool:
        return self._module().isValid(self)

    def fingerprint(self) -> Callable:
        return self._module().fingerprint(self)

    def __call__(self, *args, **kwargs):
        if not self.isValid():
            raise ValueError(f"Operator {self._key} is not valid.")

        func = self._module()._functions[self._key]
        return func(*args, **kwargs)

    def get_parameters(self) -> MappingProxyType[str, ParameterRT]:
        return self._module().get_parameters(self)
