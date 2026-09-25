from pathlib import Path
from qtpy.QtCore import QObject
from .script_module import ScriptModuleRT

from .errors import ModuleError, ImportModuleNotFoundError


class ImportModuleRT(ScriptModuleRT):
    """A script module whose edits are written back to its source file."""

    def __init__(self, path: str|None=None, parent: QObject | None = None):
        super().__init__(path, parent=parent)
        self._path = path
        try:
            self.reload_file()
        except FileNotFoundError:
            pass

    def path(self) -> str:
        return self._path

    def save_file(self) -> None:
        """Save the current script to the source file."""
        try:
            Path(self._path).write_text(self.get_script(), encoding="utf-8")
        except FileNotFoundError as error:
            raise ImportModuleNotFoundError("Cannot save file: path is None") from error

    def reload_file(self)-> None:
        """raises FileNotFoundError, if the source file does not exist."""
        if self._path is None:
            return
        try:
            text = Path(self._path).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ImportModuleNotFoundError("Cannot reload file: path does not exist") from error
        else:
            # called if no exception occurred
            super().set_script(text)
        finally:
            # called when the try block is exited, regardless of whether an exception occurred
            ...