"""Python datatype lookup for Qt editors, scoped to a registry instance."""

from enum import Enum
from pathlib import Path

from .editors import (
    EditorFactory, bool_editor, enum_editor, float_editor, int_editor,
    path_editor, string_editor,
)


class EditorRegistry:
    def __init__(self) -> None:
        self._registry: dict[type, EditorFactory] = {}
        self.register_editor(str, string_editor)
        self.register_editor(int, int_editor)
        self.register_editor(float, float_editor)
        self.register_editor(bool, bool_editor)
        self.register_editor(Path, path_editor)
        self.register_editor(Enum, enum_editor)

    def register_editor(self, datatype: type, factory: EditorFactory) -> None:
        """Register or replace a factory, used when an editor is created/refreshed.

        Factories receive the actual datatype and parent widget and return an
        Editor. Lookup follows Python's MRO: exact type, then nearest base class.
        Enums use their enum bases instead of mixed-in primitives such as int.
        Unregistered types have no editable fallback.
        """
        if not isinstance(datatype, type):
            raise TypeError("datatype must be a Python type")
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._registry[datatype] = factory

    def factory_for(self, datatype: type) -> EditorFactory | None:
        is_enum = issubclass(datatype, Enum)
        for base in datatype.__mro__:
            if is_enum and not issubclass(base, Enum):
                continue
            if base in self._registry:
                return self._registry[base]
        return None
