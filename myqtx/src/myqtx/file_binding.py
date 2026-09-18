from pathlib import Path

from qtpy.QtCore import QCoreApplication, QFileSystemWatcher, QObject, QTimer, Signal, Slot


class FileBinding(QObject):
    """An in-memory UTF-8 text file with optional automatic reloading.

    This buffer accepts arbitrary text; it does not execute or validate Python.
    A path is optional at construction: the buffer can exist in memory only until
    save(path=...) or open(path) assigns a filename. changed is emitted after the
    text or path changes. In-memory edits require save(). External edits are
    accepted automatically when the buffer is clean. Divergent local and disk
    edits retain local text and emit conflict_detected(base, local, incoming),
    with three text snapshots.

    save() and reload() return False on conflict. Resolve explicitly with
    save(force=True) to keep local text or reload(force=True) to accept disk text.
    save(path=...) writes the buffer and sets (or changes) the document path.
    Failed reads leave the buffer and path intact. Automatic I/O failures emit
    reload_failed. Watching requires a running Qt event loop and a real file on
    disk: untitled buffers and paths that do not exist yet are not watched until
    save() creates the file (or open() loads an existing one).
    """

    changed = Signal()
    conflict_detected = Signal(str, str, str)
    reload_failed = Signal(object)

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        watch: bool = True,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._auto_watch = watch
        self._watching = False
        self._file_watcher: QFileSystemWatcher | None = None
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(100)
        self._reload_timer.timeout.connect(self._reload_changed_file)

        if path is None:
            self._path: Path | None = None
            self._text = ""
            self._base_text = ""
            self._disk_text: str | None = None
        else:
            self._path = Path(path)#.resolve()
            try:
                self._text = self._path.read_text(encoding="utf-8")
            except FileNotFoundError:
                self._text = ""
                self._base_text = ""
                self._disk_text = None
            else:
                self._base_text = self._text
                self._disk_text = self._text

        if watch:
            # Defer when there is no path, or the path is not a real file yet.
            self.start_watching()

    def path(self) -> Path | None:
        return self._path

    def get_text(self) -> str:
        return self._text

    def is_modified(self) -> bool:
        """Whether the buffer differs from the last accepted or saved contents."""
        return self._text != self._base_text

    def set_text(self, text: str) -> None:
        """Edit the buffer without writing to disk."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if text == self._text:
            return
        self._text = text
        if text == self._disk_text:
            self._base_text = text
        self.changed.emit()

    def save(
        self, path: str | Path | None = None, *, force: bool = False
    ) -> bool:
        """Save the buffer, returning False if unseen disk edits conflict.

        path, when given, sets (or changes) the document path before writing —
        this is how an untitled buffer first gets a filename. A clean buffer
        accepts newer disk text when saving to the current path. force=True
        explicitly overwrites the file with local text. I/O errors raise without
        marking edits as saved. After a successful write, watching starts if it
        was requested and the file now exists on disk.
        """
        path_changed = False
        previous_path = self._path
        previous_disk_text = self._disk_text
        if path is not None:
            new_path = Path(path)#.resolve()
            if self._path is None or new_path != self._path:
                path_changed = True
                self._path = new_path
                # Destination disk state is independent of any previous path.
                self._disk_text = None

        if self._path is None:
            raise ValueError(
                "No path set; pass a path to save(), e.g. save('script.py')"
            )

        if not force:
            try:
                incoming = self._path.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Explicit saving can recreate a deleted file, or create a new one.
                pass
            else:
                if path_changed:
                    # save-as / first bind: only conflict if local edits diverge
                    # from the destination file; otherwise overwrite it.
                    if incoming == self._text:
                        self._base_text = self._text
                        self._disk_text = self._text
                        self._after_path_change()
                        return True
                    if self.is_modified():
                        self.conflict_detected.emit(
                            self._base_text, self._text, incoming
                        )
                        # Keep the previous path; caller may force-save later.
                        self._path = previous_path
                        self._disk_text = previous_disk_text
                        return False
                else:
                    if not self._accept_disk_text(incoming):
                        return False
                    if incoming == self._text:
                        self._maybe_start_watching()
                        return True

        self._path.write_text(self._text, encoding="utf-8")
        self._base_text = self._text
        self._disk_text = self._text
        # File is now real on disk; start deferred watching if requested.
        if path_changed:
            self._after_path_change()
        else:
            self._maybe_start_watching()
        return True

    def reload(self, *, force: bool = False) -> bool:
        """Read disk changes, preserving local edits unless force=True."""
        if self._path is None:
            raise ValueError("No path set; cannot reload")
        text = self._path.read_text(encoding="utf-8")
        self._reload_timer.stop()
        try:
            self._sync_watched_paths()
        except OSError as error:
            self.reload_failed.emit(error)
        return self._accept_disk_text(text, force=force)

    def open(self, path: str | Path, *, force: bool = False) -> bool:
        """Open another document; opening the current path behaves like reload()."""
        path = Path(path)#.resolve()
        if self._path is not None and path == self._path:
            return self.reload(force=force)

        text = path.read_text(encoding="utf-8")
        self._path = path
        self._text = text
        self._base_text = text
        self._disk_text = text
        self._reload_timer.stop()
        try:
            self._sync_watched_paths()
        except OSError as error:
            self.reload_failed.emit(error)
        self._maybe_start_watching()
        self.changed.emit()
        return True

    def _accept_disk_text(self, incoming: str, *, force: bool = False) -> bool:
        self._disk_text = incoming
        if incoming == self._text:
            self._base_text = incoming
            return True
        if not force:
            if incoming == self._base_text:
                return True
            if self.is_modified():
                self.conflict_detected.emit(self._base_text, self._text, incoming)
                return False

        self._base_text = incoming
        self.set_text(incoming)
        return True

    def _maybe_start_watching(self) -> None:
        """Start watching if requested and a real file is available."""
        if self._auto_watch and not self._watching:
            try:
                self.start_watching()
            except RuntimeError:
                # No QCoreApplication yet; keep auto-watch intent.
                pass

    def _after_path_change(self) -> None:
        """Sync watches and notify after the document path was reassigned."""
        self._maybe_start_watching()
        if self._watching:
            try:
                self._sync_watched_paths()
            except OSError as error:
                self.reload_failed.emit(error)
        self.changed.emit()

    def start_watching(self) -> None:
        """Watch the file and pick up edits made while watching was stopped.

        If there is no path, or the path does not exist on disk yet, watching is
        deferred until save() creates the file or open() loads an existing one.
        """
        if self._watching:
            return
        self._auto_watch = True
        if self._path is None or not self._path.exists():
            # Untitled or not-yet-created path: wait for a real file.
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
            self._watching = False
            self._auto_watch = True  # keep intent; caller may retry after save
            paths = self._file_watcher.files() + self._file_watcher.directories()
            if paths:
                self._file_watcher.removePaths(paths)
            raise
        self._reload_timer.start()

    def stop_watching(self) -> None:
        """Release file watches and cancel a pending automatic reload."""
        self._watching = False
        self._auto_watch = False
        self._reload_timer.stop()
        if self._file_watcher is not None:
            paths = self._file_watcher.files() + self._file_watcher.directories()
            if paths:
                self._file_watcher.removePaths(paths)

    def close(self) -> None:
        """Stop automatic reloads, retaining the in-memory buffer."""
        self.stop_watching()

    def _sync_watched_paths(self) -> None:
        if not self._watching or self._path is None:
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
        if (
            self._watching
            and self._path is not None
            and Path(changed_path) in (self._path, self._path.parent)
        ):
            self._reload_timer.start()

    @Slot()
    def _reload_changed_file(self) -> None:
        if not self._watching or self._path is None:
            return
        try:
            self._sync_watched_paths()
            text = self._path.read_text(encoding="utf-8")
            # Directory events include unrelated files. Compare with the last
            # disk contents so those events cannot overwrite unsaved buffer edits.
            if text == self._disk_text:
                return
            self._accept_disk_text(text)
        except Exception as error:
            if isinstance(error, FileNotFoundError):
                self._disk_text = None
            self.reload_failed.emit(error)
