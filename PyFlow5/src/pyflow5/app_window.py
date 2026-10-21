import json
import os
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
from qtpy.QtGui import QAction, QCloseEvent
from qtpy.QtWidgets import QApplication, QMainWindow, QMenuBar, QMenu, QWidget

from .core.file_io import write_text_atomic
from .models.pyflow5_document import FileStamp, PyFlowDocument
from .views.pyflow5_documentwindow import PyFlow5DocumentWindow

class AppWindow(QMainWindow):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        use_session: bool = True,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)

        self._closed = False
        self._use_session = use_session
        self._settings = settings if settings is not None else QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "BABLab",
            "PyFlow5",
        )
        self._recent_graphs: list[str] = self._settings.value(
            "recentGraphs", [], type=list
        )
        self._session_path = (
            Path(self._settings.fileName()).parent / "session.json"
        )

        if self._use_session and self._session_path.exists():
            try:
                jsontext = Path(self._session_path).read_text(encoding="utf-8")
                new_document = self.deserializeSession(jsontext)
            except Exception as error:
                print(f"Failed to load session: {error}")
                new_document = PyFlowDocument()
        else:
            new_document = PyFlowDocument()

        self.setContentsMargins(0, 0, 0, 0)
        self.resize(1460, 760)
        try:
            self._document_window = PyFlow5DocumentWindow(new_document, self)
        except Exception:
            new_document.close()
            raise
        self._document_window.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(self._document_window)
        self._document_window.windowTitleChanged.connect(self.setWindowTitle)
        self._document_window.fileOpened.connect(self._rememberGraph)
        self._document_window.fileSaved.connect(self._rememberGraph)
        self.setWindowTitle(self._document_window.windowTitle())
        self.setupMenubar()

    def currentDocumentWindow(self) -> PyFlow5DocumentWindow:
        return self._document_window

    def setupMenubar(self) -> None:
        # Bound callbacks and panel actions must belong to the current editor.
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        file_menu = QMenu("File", menubar)
        menubar.addMenu(file_menu)
        file_menu.addAction("New",           lambda: self.newDocument()).setShortcut("Ctrl+N")
        file_menu.addAction("Open Graph",    lambda: self.openDocument()).setShortcut("Ctrl+O")
        recents_menu = QMenu("Recent Graphs", file_menu)
        recents_menu.aboutToShow.connect(
            lambda: self._populateRecentGraphs(recents_menu)
        )
        self._populateRecentGraphs(recents_menu)
        file_menu.addMenu(recents_menu)
        file_menu.addAction("Save Graph",    lambda: self.saveCurrentDocument()).setShortcut("Ctrl+S")
        file_menu.addAction("Save Graph As", lambda: self.saveDocumentAs()).setShortcut("Ctrl+Shift+S")
        file_menu.addSeparator()

        edit_menu = QMenu("Edit", menubar)
        menubar.addMenu(edit_menu)
        edit_menu.addAction("Undo",  lambda: None)
        edit_menu.addAction("Redo",  lambda: None)
        edit_menu.addAction("Cut",   lambda: None)
        edit_menu.addAction("Copy",  lambda: None)
        edit_menu.addAction("Paste", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Select All", lambda: None)
        edit_menu.addAction("Select None", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Restart Graph", lambda: self.currentDocumentWindow()._document.restart_graph())
        edit_menu.addSeparator()

        edit_menu.addAction("New Node", self.currentDocumentWindow().openOperatorDialog).setShortcut("Ctrl+P")
        edit_menu.addAction("Delete Nodes", lambda: self.currentDocumentWindow().deleteSelectedNodes()).setShortcut("Del")
        edit_menu.addAction("Duplicate Nodes", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Add Embedded Module", lambda: self.currentDocumentWindow().addEmbeddedModule())
        edit_menu.addAction("Remove Selected Module", lambda: self.currentDocumentWindow().removeSelectedModule())

        view_menu = QMenu("View", menubar)
        view_menu.addAction(self.currentDocumentWindow()._graph_view._center_nodes_action)
        view_menu.addAction(self.currentDocumentWindow()._graph_view._layout_action)

        view_menu.addSeparator()
        self._navigate_operator_action = QAction("Go to Current Node's Operator", view_menu)
        self._navigate_operator_action.setShortcuts(["Return", "Enter"])
        self._navigate_operator_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._navigate_operator_action.triggered.connect(self.currentDocumentWindow()._navigate_to_current_node_operator)
        self.currentDocumentWindow()._graph_view.addAction(self._navigate_operator_action)
        view_menu.addAction(self._navigate_operator_action)
        panels = [
            (self.currentDocumentWindow()._modules_panel, "Modules"),
            (self.currentDocumentWindow()._graph_view, "Graph"),
            (self.currentDocumentWindow()._node_inlet_tree_view, "Tree"),
            (self.currentDocumentWindow()._viewer, "Viewer")
        ]
        for panel, name in panels:
            # add show/hide toggle to each panel
            action = QAction(f"Show/Hide {name}", view_menu)
            action.setCheckable(True)
            action.setChecked(not panel.isHidden())
            action.triggered.connect(lambda checked, p=panel: p.setVisible(checked))
            view_menu.addAction(action)

        self._navigate_to_previous_graph_panel = QAction("Go to Graph Panel", view_menu)
        self._navigate_to_previous_graph_panel.setShortcuts(["Esc"])
        self._navigate_to_previous_graph_panel.setShortcutContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._navigate_to_previous_graph_panel.triggered.connect(self._showGraphPanel)
        self.currentDocumentWindow()._modules_panel.addAction(self._navigate_to_previous_graph_panel)
        view_menu.addAction(self._navigate_to_previous_graph_panel)

        view_menu.addSeparator()
        menubar.addMenu(view_menu)

    def _showGraphPanel(self) -> None:
        document_window = self.currentDocumentWindow()
        document_window._graph_view.show()
        document_window._left_tabwidget.setCurrentWidget(document_window._graph_panel)
        document_window._graph_view.setFocus()

    def _populateRecentGraphs(self, menu: QMenu) -> None:
        menu.clear()
        for recent in self._recent_graphs:
            action = menu.addAction(recent)
            action.triggered.connect(
                lambda checked=False, path=recent: self.openDocument(path)
            )

    def serializeSession(self) -> str:
        document = self._document_window.document()
        path = document.filePath()
        stat = document.fileStat()
        stat_data = (
            {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
            if stat is not None else None
        )
        return json.dumps({
            "session_version": 1,
            "document": json.loads(document.serialize()),
            "file_path": str(path) if path is not None else None,
            "file_stat": stat_data,
            "modified": document.isModified(),
        }, indent=4)

    def deserializeSession(self, jsontext: str) -> PyFlowDocument:
        data = json.loads(jsontext)
        if not isinstance(data, dict):
            raise ValueError("Invalid session format.")
        if "session_version" not in data:
            # Migrate the previous content-only session without inventing a file baseline.
            saved_path = self._settings.value("sessionDocumentPath", "", type=str)
            resolved_path = Path(saved_path).resolve() if saved_path else None
            document = PyFlowDocument.deserialize(jsontext)
            document.restoreFileBinding(resolved_path, None)
            document.setModified(True)
            return document
        if type(data["session_version"]) is not int or data["session_version"] != 1:
            raise ValueError("Unsupported session version.")
        path = data.get("file_path")
        if path is not None and (not isinstance(path, str) or not path):
            raise ValueError("Invalid session document path.")
        modified = data.get("modified")
        if type(modified) is not bool:
            raise ValueError("Invalid session modified state.")
        stat_data = data.get("file_stat")
        stat = None
        if stat_data is not None:
            if (
                path is None or not isinstance(stat_data, dict)
                or type(stat_data.get("mtime_ns")) is not int
                or type(stat_data.get("size")) is not int or stat_data["size"] < 0
            ):
                raise ValueError("Invalid session file state.")
            stat = FileStamp(stat_data["mtime_ns"], stat_data["size"])
        # Resolve metadata before constructing a live document.
        resolved_path = Path(path).resolve() if path is not None else None
        document = PyFlowDocument.deserialize(json.dumps(data.get("document")))
        document.restoreFileBinding(resolved_path, stat)
        document.setModified(modified)
        return document

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closed:
            event.accept()
            return
                    
        if self._use_session:
            try:
                self._session_path.parent.mkdir(parents=True, exist_ok=True)
                write_text_atomic(self._session_path, self.serializeSession())
            except Exception as error:
                if not self._document_window.confirmCloseWithoutSession(error):
                    event.ignore()
                    return
        elif not self._document_window.confirmSaveChanges():
            event.ignore()
            return
        self._document_window.dispose()
        self._closed = True
        event.accept()

    def newDocument(self) -> bool:
        return self._document_window.newDocument()

    def openDocument(self, path: str | Path = "") -> bool:
        return self._document_window.open(path)

    def _rememberGraph(self, path: str | Path) -> None:
        path = os.path.abspath(path)
        path_key = os.path.normcase(path)

        previous = [
            existing
            for existing in self._recent_graphs
            if os.path.normcase(existing) != path_key
        ]
        self._recent_graphs = [path, *previous][:5]

        self._settings.setValue("recentGraphs", self._recent_graphs)
        self._settings.sync()

    def saveCurrentDocument(self) -> bool:
        return self._document_window.save()

    def saveDocumentAs(self) -> bool:
        return self._document_window.saveAs()

    def applyTheme(self, theme: str, *, persist: bool = True) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError(f"Theme changes require a QApplication instance, got {app}")

        self._system_style_key = app.style().name()

        app.setStyleSheet("")
        if theme == "system":
            # Apply the system style
            app.setStyle(self._system_style_key)

        elif theme == "fusion":
            app.setStyle("Fusion")

        elif theme == "dark":
            import qdarkstyle

            app.setStyle("Fusion")
            app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt6"))
        else:
            raise ValueError(f"Unknown theme: {theme}")

        self._theme = theme
        if persist:
            self._settings.setValue("theme", theme)
            self._settings.sync()
