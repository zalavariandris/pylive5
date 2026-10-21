import os
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
from qtpy.QtGui import QAction, QCloseEvent, QColor, QPainter
from qtpy.QtWidgets import (
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProxyStyle,
    QStyle,
    QStyleOption,
    QWidget,
    QFileDialog
)

from .models.pyflow5_document import PyFlowDocument
from .views.pyflow5_documentwindow import PyFlow5DocumentWindow

class HoverFusionStyle(QProxyStyle):
    def __init__(self) -> None:
        super().__init__("Fusion")

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        super().drawPrimitive(element, option, painter, widget)

        if element in {
            QStyle.PrimitiveElement.PE_PanelItemViewItem, 
            # QStyle.PrimitiveElement.CE_ItemViewItem
        }:

            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            selected = bool(option.state & QStyle.StateFlag.State_Selected)

            if hovered and not selected:
                color = QColor(option.palette.highlight().color())
                color.setAlpha(80)
                painter.fillRect(option.rect, color)


class AppWindow(QMainWindow):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        use_session: bool = True,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)

        self._document_path: Path | None = None
        self._document_window: PyFlow5DocumentWindow | None = None

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
                new_document = PyFlowDocument.fromfile(self._session_path)
            except Exception as error:
                print(f"Failed to load session: {error}")
                new_document = PyFlowDocument()
            else:
                saved_path = self._settings.value(
                    "sessionDocumentPath", "", type=str
                )
                self._document_path = Path(saved_path) if saved_path else None
        else:
            new_document = PyFlowDocument()

        self.setContentsMargins(0, 0, 0, 0)
        self.resize(1460, 760)
        self._replaceDocument(new_document, self._document_path)

    def currentDocumentWindow(self) -> PyFlow5DocumentWindow | None:
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
        document_window._left_tabwidget.setCurrentWidget(document_window._graph_container)
        document_window._graph_view.setFocus()

    def _populateRecentGraphs(self, menu: QMenu) -> None:
        menu.clear()
        for recent in self._recent_graphs:
            action = menu.addAction(recent)
            action.triggered.connect(
                lambda checked=False, path=recent: self.openDocument(path)
            )

    def _setDocumentPath(self, path: Path | None) -> None:
        self._document_path = path
        name = path.name if path is not None else "Untitled"
        self.setWindowTitle(f"PyFlow5 - {name}")

    def _replaceDocument(
        self, document: PyFlowDocument, path: Path | None = None
    ) -> None:
        try:
            replacement = PyFlow5DocumentWindow(document=document, parent=self)
        except Exception:
            document.close()
            raise

        previous = self.takeCentralWidget()
        self._document_window = replacement
        replacement.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(replacement)
        self._setDocumentPath(path)
        self.setupMenubar()
        if previous is not None:
            previous.close()
            previous.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._use_session:
            try:
                self._session_path.parent.mkdir(parents=True, exist_ok=True)
                self._document_window._document.save(self._session_path)
                self._settings.setValue(
                    "sessionDocumentPath",
                    str(self._document_path) if self._document_path is not None else "",
                )
                self._settings.sync()
            except Exception as error:
                answer = QMessageBox.warning(
                    self,
                    "Cannot save session",
                    f"The session could not be saved:\n{error}\n\n"
                    "Close the app anyway? Unsaved changes may be lost.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return

        self._document_window.close()
        event.accept()

    def newDocument(self) -> None:
        self._replaceDocument(PyFlowDocument())

    def openDocument(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open file",
                "",
                "JSON files (*.json)",
            )

        if not path:
            return
        try:
            resolved_path = Path(path).resolve()
            document = PyFlowDocument.fromfile(resolved_path)
            self._replaceDocument(document, resolved_path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot open graph", str(error))
            return
        self._rememberGraph(str(resolved_path))

    def _rememberGraph(self, path: str) -> None:
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

    def _saveDocumentTo(self, path: Path) -> bool:
        try:
            path = path.resolve()
            self._document.save(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save graph", str(error))
            return False
        self._setDocumentPath(path)
        self._rememberGraph(str(path))
        return True

    def saveCurrentDocument(self) -> bool:
        if self._document_path is None:
            return self.saveDocumentAs()
        return self._saveDocumentTo(self._document_path)

    def saveDocumentAs(self) -> bool:
        initial_path = (
            str(self._document_path)
            if self._document_path is not None
            else "untitled.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save graph as",
            initial_path,
            "JSON files (*.json)",
        )
        if not path:
            return False
        return self._saveDocumentTo(Path(path))

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

if __name__ == "__main__":
    try:
        import pytracy
        import sys
        pytracy.set_filtering_mode(True, False, False)
        pytracy.enable_tracing(True)
        print("Tracing enabled")
        print("Python profile callback:", sys.getprofile())
    except ImportError:
        print("pytracy not available")

    from qtpy.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    app.setStyle(HoverFusionStyle()) # note: without the fusion style, the currect index is not visible at all.

    document_window = AppWindow()
    document_window.show()
    sys.exit(app.exec())
