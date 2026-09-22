from pathlib import Path

from qtpy.QtCore import QObject

from .script_module import ScriptModuleRT


class ImportModuleRT(ScriptModuleRT):
    """A script module whose edits are written back to its source file."""

    def __init__(self, path: str, parent: QObject | None = None, *, source: str | None = None):
        super().__init__(Path(path).stem, source if source is not None else "", parent=parent)
        self._path = path
        if source is None:
            self.reload()

    def path(self) -> str:
        return self._path

    def set_script(self, script: str) -> None:
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        if script == self.get_script():
            return
        # Persist first: observers should only see edits that were saved.
        Path(self._path).write_text(script, encoding="utf-8")
        super().set_script(script)

    def reload(self):
        try:
            text = Path(self._path).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"File not found: {self._path}")
            return
        super().set_script(text)
