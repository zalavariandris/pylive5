"""
Runtime representation of an importable script module.
responsibility: ...
"""

from pathlib import Path
import warnings
from qtpy.QtCore import QObject
from .script_module import ScriptModuleRT

from .errors import ModuleError, ImportModuleNotFoundError


class ImportModuleRT(ScriptModuleRT):
    """A script module whose edits are written back to its source file."""

    def __init__(self, name:str, path: Path|None=None, parent: QObject | None = None):
        super().__init__(name, parent=parent)
        assert isinstance(path, Path) or path is None, "path must be a Path object or None"
        self._path = path
        try:
            self.reload_file()
        except ImportModuleNotFoundError as error:
            # todo: we need to handle the case, when an importmodule is created from scratch without an actual file. basically its not saved yet.
            warnings.warn(f"Import module '{name}' not found at path {self._path}")

    def path(self) -> Path|None:
        return self._path

    def save_file(self) -> None:
        """Save the current script to the source file."""
        try:
            Path(self._path).write_text(self.get_source(), encoding="utf-8")
        except FileNotFoundError as error:
            raise ImportModuleNotFoundError(f"Cannot save file: path is None {self._path}") from error

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