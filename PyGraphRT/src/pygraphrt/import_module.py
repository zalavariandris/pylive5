from pathlib import Path

from qtpy.QtCore import QObject

from .script_module import ScriptModuleRT


class ImportModuleRT(ScriptModuleRT):
    """A script module whose edits are written back to its source file."""

    def __init__(self, path: str, parent: QObject | None = None):
        super().__init__(Path(path).stem, parent=parent)
        self._path = path
        try:
            self.reload_file()
        except FileNotFoundError:
            pass

    def path(self) -> str:
        return self._path

    def set_script(self, script: str) -> None:
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        if script == self.get_script():
            return
        # Persist first: observers should only see edits that were saved.
        super().set_script(script)

    def save_file(self) -> None:
        """Save the current script to the source file."""
        Path(self._path).write_text(self.get_script(), encoding="utf-8")

    def reload_file(self)->"None":
        """raises FileNotFoundError, if the source file does not exist."""
        text = Path(self._path).read_text(encoding="utf-8")
        super().set_script(text)
