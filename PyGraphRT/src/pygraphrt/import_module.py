"""Runtime representation of a script loaded from an external file."""

from os import PathLike
from pathlib import Path
import warnings
from qtpy.QtCore import QObject
from .script_module import ScriptModuleRT

from .errors import ImportModuleNotFoundError


class ImportModuleRT(ScriptModuleRT):
    """Load source and expose its path without writing to the source file."""

    def __init__(self, name:str, path: PathLike|None=None, parent: QObject | None = None):
        super().__init__(name, parent=parent)
        assert isinstance(path, PathLike) or path is None, "path must be a PathLike object or None"
        self._path = Path(path) if path is not None else None
        try:
            self.reload_file()
        except ImportModuleNotFoundError:
            # A missing source can be supplied later and loaded with reload_file().
            warnings.warn(f"Import module '{name}' not found at path {self._path}")

    def path(self) -> Path|None:
        return self._path

    def get_source_path(self) -> Path | None:
        return self._path.resolve() if self._path is not None else None

    def reload_file(self)-> None:
        """raises ImportModuleNotFoundError, if the source file does not exist."""
        if self._path is None:
            return
        try:
            text = Path(self._path).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ImportModuleNotFoundError(f"Cannot reload file: path does not exist {self._path}") from error
        else:
            # called if no exception occurred
            super().set_script(text)
        finally:
            # called when the try block is exited, regardless of whether an exception occurred
            ...
