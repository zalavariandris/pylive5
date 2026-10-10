"""Python datatype lookup for Qt editors, scoped to a registry instance."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .editors import (
    EditorFactory, 
    bool_editor, 
    enum_editor, 
    float_editor, 
    int_editor,
    path_editor, 
    string_editor,
)


@dataclass(frozen=True)
class EditorContext:
    """The operator parameter for which an editor is being selected."""

    module_name: str
    operator_name: str
    parameter_name: str
    annotation: object
    source_path: Path | None = None


EditorProvider = Callable[[EditorContext], EditorFactory | None]


class EditorRegistry:
    def __init__(self) -> None:
        self._registry: dict[type, EditorFactory] = {}
        self._providers: dict[str | Path, EditorProvider] = {}
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

    def register_provider(self, module: str | Path, provider: EditorProvider) -> None:
        """Register or replace a provider for an exact module name or source Path.

        File providers run first, then named providers, then ordinary type lookup.
        Returning None defers to the next lookup. Paths are resolved on registration.
        Registrations belong to this registry instance.
        """
        if isinstance(module, Path):
            module = module.resolve()
        elif not isinstance(module, str) or not module:
            raise ValueError("module must be a non-empty string or Path")
        if not callable(provider):
            raise TypeError("provider must be callable")
        self._providers[module] = provider

    def factory_for(
        self, datatype: object, *, context: EditorContext | None = None,
    ) -> EditorFactory | None:
        """Resolve a factory while preserving the full annotation for providers."""
        if context is not None:
            scopes: list[str | Path] = []
            if context.source_path is not None:
                scopes.append(context.source_path.resolve())

            scopes.append(context.module_name)

            for scope in scopes:
                provider = self._providers.get(scope)
                if provider is None:
                    continue
                factory = provider(context)
                if factory is not None:
                    if not callable(factory):
                        raise TypeError("Editor providers must return a factory or None")
                    return factory
                
        if not isinstance(datatype, type):
            return None
        is_enum = issubclass(datatype, Enum)
        for base in datatype.__mro__:
            if is_enum and not issubclass(base, Enum):
                continue
            if base in self._registry:
                return self._registry[base]
        return None
