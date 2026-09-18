from __future__ import annotations
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Mapping

if TYPE_CHECKING:
    from .abstract_module_rt import AbstractModuleRT
    from pygraphrt.operator_rt import ParameterRT

import weakref


class OperatorRTRef:
    def __init__(self, module: AbstractModuleRT, name: str):
        self._module: weakref.ReferenceType[AbstractModuleRT] = weakref.ref(module)
        self._name = name

    def module(self) -> AbstractModuleRT | None:
        return self._module()

    def name(self):
        return self._name

    def isValid(self) -> bool:
        return self._module().isValid(self)

    def fingerprint(self) -> Callable:
        return self._module().fingerprint(self)

    def __call__(self, *args, **kwargs):
        if not self.isValid():
            raise ValueError(f"Operator {self._name} is not valid.")

        return self._module().call(self, *args, **kwargs)

    def get_parameters(self) -> MappingProxyType[str, ParameterRT]:
        return self._module().get_parameters(self)
