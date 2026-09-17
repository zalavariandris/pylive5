import inspect
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Hashable, Mapping

from qtpy.QtCore import QCoreApplication, QFileSystemWatcher, QTimer, Signal, Slot

from .abstract_module_rt import AbstractModuleRT
from .operator_rt import ParameterRT
from .operator_rt_ref import OperatorRTRef


class ImportModuleRT(AbstractModuleRT):
    """An editable operator collection backed by a UTF-8 Python source file.

    All callable module-level bindings are exported, including imported callables.
    Source runs in a fresh namespace; imported dependencies use normal Python
    import caching. This is a source-file loader, not a package import loader.

    Failed reads or source execution raise without replacing the accepted state.
    Changed source invalidates all retained operators, since their behavior may
    depend on globals, helpers, or definition-time expressions.

    File watching is enabled by default and requires a running Qt event loop.
    Pass watch=False for manual loading without a QCoreApplication. Automatic
    reload failures emit reload_failed with the exception and retain live state.
    """

    script_changed = Signal()
    reload_failed = Signal(object)

    def __init__(self, name: str, path: str | Path, *, watch: bool = True):
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        super().__init__(name)

        self._path = Path(path).resolve()
        self._script = ""
        self._functions: dict[str, Callable] = {}
        self._operators: dict[str, OperatorRTRef] = {}
        self._revision = 0
        self._disk_script: str | None = None
        self._watching = False
        self._file_watcher: QFileSystemWatcher | None = None
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(100)
        self._reload_timer.timeout.connect(self._reload_changed_file)
        self.reload()
        if watch:
            self.start_watching()

    def path(self) -> Path:
        return self._path

    def get_script(self) -> str:
        return self._script

    def set_script(self, script: str) -> None:
        """Apply source in memory. Call save() to write it to the current file."""
        self._apply_script(script, self._path)

    def save(self) -> None:
        """Write the accepted source to the current file."""
        self._path.write_text(self._script, encoding="utf-8")
        self._disk_script = self._script

    def reload(self) -> None:
        """Read the current file and apply it if its source has changed."""
        self.open(self._path)

    def _reload(self) -> None:
        self.reload()

    def open(self, path: str | Path) -> None:
        """Load another file, changing the current path only after success."""
        path = Path(path).resolve()
        script = path.read_text(encoding="utf-8")
        self._apply_script(script, path, from_disk=True)

    def start_watching(self) -> None:
        """Watch the current file and pick up edits made while watching was stopped."""
        if self._watching:
            return
        if QCoreApplication.instance() is None:
            raise RuntimeError(
                "File watching requires a QCoreApplication; use watch=False otherwise."
            )
        if self._file_watcher is None:
            self._file_watcher = QFileSystemWatcher(self)
            self._file_watcher.fileChanged.connect(self._schedule_reload)
            self._file_watcher.directoryChanged.connect(self._schedule_reload)
        self._watching = True
        try:
            self._sync_watched_paths()
        except OSError:
            self.stop_watching()
            raise
        self._reload_timer.start()

    def stop_watching(self) -> None:
        """Release file watches and cancel a pending automatic reload."""
        self._watching = False
        self._reload_timer.stop()
        if self._file_watcher is not None:
            paths = self._file_watcher.files() + self._file_watcher.directories()
            if paths:
                self._file_watcher.removePaths(paths)

    def close(self) -> None:
        """Stop automatic reloads. The accepted operators remain usable."""
        self.stop_watching()

    def _sync_watched_paths(self) -> None:
        if not self._watching:
            return

        # Editors often replace the file on save. Its directory watch survives
        # replacement/deletion and lets us restore the file watch when it returns.
        desired = {self._path.parent.as_posix()}
        if self._path.exists():
            desired.add(self._path.as_posix())
        current = set(self._file_watcher.files() + self._file_watcher.directories())
        if removed := current - desired:
            self._file_watcher.removePaths(sorted(removed))
        if added := desired - current:
            failed = self._file_watcher.addPaths(sorted(added))
            if failed:
                raise OSError(f"Could not watch: {', '.join(failed)}")

    @Slot(str)
    def _schedule_reload(self, changed_path: str) -> None:
        if self._watching and Path(changed_path) in (self._path, self._path.parent):
            self._reload_timer.start()

    @Slot()
    def _reload_changed_file(self) -> None:
        if not self._watching:
            return
        try:
            self._sync_watched_paths()
            script = self._path.read_text(encoding="utf-8")
            # Directory events include unrelated files. Compare against the last
            # disk contents, so those events cannot overwrite unsaved memory edits.
            if script == self._disk_script:
                return
            # Remember failed source too, avoiding retries on duplicate events.
            self._disk_script = script
            self._apply_script(script, self._path, from_disk=True)
        except Exception as error:
            if isinstance(error, FileNotFoundError):
                self._disk_script = None
            self.reload_failed.emit(error)

    def _apply_script(self, script: str, path: Path, *, from_disk: bool = False) -> None:
        if not isinstance(script, str):
            raise TypeError("script must be a string")
        if self._revision and script == self._script and path == self._path:
            if from_disk:
                self._disk_script = script
            return

        # Prepare everything before changing live state or notifying observers.
        namespace: dict[str, Any] = {
            "__name__": self.name(),
            "__file__": str(path),
            "__package__": "",
        }
        code = compile(script, str(path), "exec")
        exec(code, namespace)
        functions = {key: value for key, value in namespace.items() if callable(value)}

        previous_names = self._functions.keys()
        next_names = functions.keys()
        removed = sorted(previous_names - next_names)
        added = sorted(next_names - previous_names)
        changed = sorted(previous_names & next_names)
        operators = {
            key: self._operators[key] if key in self._operators else OperatorRTRef(self, key)
            for key in functions
        }

        self._path = path
        self._script = script
        self._functions = functions
        self._operators = operators
        self._revision += 1
        if from_disk:
            self._disk_script = script
            self._reload_timer.stop()
            try:
                self._sync_watched_paths()
            except OSError as error:
                self.reload_failed.emit(error)

        self.script_changed.emit()
        if removed:
            self.operators_removed.emit(removed)
        if added:
            self.operators_added.emit(added)
        if changed:
            self.operators_changed.emit(changed)

    def operators(self) -> Mapping[str, OperatorRTRef]:
        return dict(self._operators)

    def get_operator(self, name: str) -> OperatorRTRef | None:
        return self._operators.get(name)

    def isValid(self, operator: OperatorRTRef) -> bool:
        return (
            isinstance(operator, OperatorRTRef)
            and operator.module is self
            and operator.key() in self._functions
        )

    def _get_function(self, operator: OperatorRTRef) -> Callable:
        if not self.isValid(operator):
            raise ValueError(f"Operator {operator!r} is not available in module {self.name()!r}.")
        return self._functions[operator.key()]

    def get_parameters(self, operator: OperatorRTRef) -> MappingProxyType[str, ParameterRT]:
        if not self.isValid(operator):
            return MappingProxyType({})

        signature = inspect.signature(self._get_function(operator))
        return MappingProxyType({
            parameter.name: ParameterRT(
                name=parameter.name,
                annotation=parameter.annotation,
                default=parameter.default,
            )
            for parameter in signature.parameters.values()
        })

    def fingerprint(self, operator: OperatorRTRef) -> Hashable:
        self._get_function(operator)
        return self, operator.key(), self._revision

    def call(self, op: OperatorRTRef, *args, **kwargs):
        return self._get_function(op)(*args, **kwargs)
