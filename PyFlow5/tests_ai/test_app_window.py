import json
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication, QEvent, QSettings
from qtpy.QtGui import QAction, QCloseEvent
from qtpy.QtWidgets import QFileDialog, QMenu, QMessageBox

import pyflow5.__main__ as app_module
from pyflow5.__main__ import AppWindow
from pyflow5.models.pyflow5_document import PyFlowDocument
from pyflow5.views.pyflow5_documentwindow import PyFlow5DocumentWindow


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def make_window(
    qtbot: QtBot, settings: QSettings
) -> Iterator[Callable[..., AppWindow]]:
    windows: list[AppWindow] = []

    def make(*, use_session: bool = False) -> AppWindow:
        window = AppWindow(use_session=use_session, settings=settings)
        windows.append(window)
        qtbot.addWidget(window)
        return window

    yield make
    for window in windows:
        window._use_session = False
        window.close()


def write_graph(path: Path, name: str = "example") -> None:
    data = {
        "version": 3,
        "modules": {
            "local": {"type": "embedded", "source": "def operation(): return 42\n"}
        },
        "graph": {
            "nodes": {name: {"operator": {"module": "local", "name": "operation"}}}
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def menu(window: AppWindow, text: str) -> QMenu:
    result = next(
        action.menu() for action in window.menuBar().actions() if action.text() == text
    )
    assert result is not None
    return result


def action(window: AppWindow, menu_text: str, text: str) -> QAction:
    return next(item for item in menu(window, menu_text).actions() if item.text() == text)


def test_open_new_open_binds_views_and_closes_previous_documents(
    make_window: Callable[..., AppWindow], tmp_path: Path
) -> None:
    window = make_window()
    first = window._document
    path = tmp_path / "graph.json"
    write_graph(path)

    window.openDocument(str(path))
    loaded = window._document
    editor = window._document_window
    assert first._engine._closed
    assert list(loaded.graph_model.nodes()) == ["example"]
    assert editor._graph_view._model is loaded.graph_model
    assert editor._modules_listview.model() is loaded.modules_model
    assert editor._node_tree_view.model() is loaded.node_inlet_tree_adapter
    assert editor._viewer.model() is loaded.node_inlet_tree_adapter
    assert editor._node_inspector.model() is loaded.node_inlet_tree_adapter
    assert window._document_path == path
    assert path.name in window.windowTitle()

    window.newDocument()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert loaded._engine._closed
    assert window._document_path is None
    assert list(window._document.graph_model.nodes()) == []
    assert "Untitled" in window.windowTitle()

    window.openDocument(str(path))
    assert list(window._document.graph_model.nodes()) == ["example"]
    assert len(window.menuBar().actions()) == 3


def test_menus_use_current_editor_and_dispose_previous_widgets(
    make_window: Callable[..., AppWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[PyFlow5DocumentWindow] = []

    def open_dialog(editor: PyFlow5DocumentWindow) -> None:
        calls.append(editor)

    monkeypatch.setattr(PyFlow5DocumentWindow, "openOperatorDialog", open_dialog)
    window = make_window()
    destroyed: list[str] = []
    window._document_window.destroyed.connect(lambda: destroyed.append("editor"))
    window.menuBar().destroyed.connect(lambda: destroyed.append("menubar"))
    window.newDocument()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert set(destroyed) == {"editor", "menubar"}

    action(window, "Edit", "New Node").trigger()
    assert calls == [window._document_window]
    for label, method in (
        ("Restart Graph", "restart_graph"),
        ("Delete Nodes", "deleteSelectedNodes"),
    ):
        callback = Mock()
        monkeypatch.setattr(window._document, method, callback)
        action(window, "Edit", label).trigger()
        callback.assert_called_once_with()

    editor = window._document_window
    for label, method in (("Fit Nodes", "fitNodes"), ("Layout Nodes", "layout_nodes")):
        callback = Mock()
        monkeypatch.setattr(editor._graph_view, method, callback)
        action(window, "View", label).trigger()
        callback.assert_called_once_with()

    graph_toggle = action(window, "View", "Show/Hide Graph")
    assert graph_toggle.isChecked()
    graph_toggle.trigger()
    assert editor._graph_view.isHidden()
    graph_toggle.trigger()
    assert not editor._graph_view.isHidden()
    editor._left_tabwidget.setCurrentWidget(editor._modules_panel)
    action(window, "View", "Go to Graph Panel").trigger()
    assert editor._left_tabwidget.currentWidget() is editor._graph_container


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_open_keeps_current_document(
    make_window: Callable[..., AppWindow],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    window = make_window()
    document = window._document
    editor = window._document_window
    warnings = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warnings)
    if cancel:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
        window.openDocument()
    else:
        path = tmp_path / "broken.json"
        path.write_text("invalid json", encoding="utf-8")
        window.openDocument(str(path))

    assert window._document is document
    assert window._document_window is editor
    assert not document._engine._closed
    assert window._document_path is None
    assert window._recent_graphs == []
    assert warnings.call_count == (0 if cancel else 1)


def test_failed_editor_construction_closes_candidate_only(
    make_window: Callable[..., AppWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    window = make_window()
    previous = window._document
    candidate = PyFlowDocument()
    monkeypatch.setattr(PyFlowDocument, "fromfile", lambda path: candidate)
    monkeypatch.setattr(
        app_module, "PyFlow5DocumentWindow", Mock(side_effect=RuntimeError("cannot bind"))
    )
    monkeypatch.setattr(QMessageBox, "warning", Mock())
    window.openDocument("example.json")
    assert candidate._engine._closed
    assert window._document is previous
    assert not previous._engine._closed


def test_save_reuses_path_and_save_as_switches_it(
    make_window: Callable[..., AppWindow],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = make_window()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    dialog = Mock(return_value=(str(first_path), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", dialog)
    assert window.saveCurrentDocument()
    assert first_path.exists()
    assert window._document_path == first_path
    dialog.assert_called_once()

    window._document.addEmbeddedModule()
    assert window.saveCurrentDocument()
    assert "modules" in json.loads(first_path.read_text(encoding="utf-8"))
    dialog.assert_called_once()
    first_contents = first_path.read_text(encoding="utf-8")

    dialog.return_value = (str(second_path), "")
    window._document.addEmbeddedModule()
    assert window.saveDocumentAs()
    assert window._document_path == second_path
    assert second_path.name in window.windowTitle()
    assert first_path.read_text(encoding="utf-8") == first_contents
    assert second_path.read_text(encoding="utf-8") != first_contents
    assert window._recent_graphs == [str(second_path), str(first_path)]


@pytest.mark.parametrize("cancel", [False, True])
def test_cancelled_or_failed_save_as_preserves_existing_path(
    make_window: Callable[..., AppWindow],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    window = make_window()
    original_path = tmp_path / "original.json"
    write_graph(original_path)
    window.openDocument(str(original_path))
    new_path = tmp_path / "new.json"
    dialog_path = "" if cancel else str(new_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (dialog_path, ""))
    monkeypatch.setattr(window._document, "save", Mock(side_effect=OSError("disk full")))
    monkeypatch.setattr(QMessageBox, "warning", Mock())
    assert not window.saveDocumentAs()
    assert window._document_path == original_path
    assert window._recent_graphs == [str(original_path)]
    assert not new_path.exists()


def test_recent_menu_refreshes_and_opens_selected_path(
    make_window: Callable[..., AppWindow],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = make_window()
    paths = [str(tmp_path / f"{index}.json") for index in range(6)]
    for path in paths:
        window._rememberGraph(path)
    window._rememberGraph(paths[3])
    recent_menu = action(window, "File", "Recent Graphs").menu()
    assert recent_menu is not None
    recent_menu.aboutToShow.emit()
    expected = [paths[3], paths[5], paths[4], paths[2], paths[1]]
    assert [item.text() for item in recent_menu.actions()] == expected
    open_document = Mock()
    monkeypatch.setattr(window, "openDocument", open_document)
    recent_menu.actions()[1].triggered.emit(True)
    open_document.assert_called_once_with(paths[5])


def test_session_restores_unsaved_work_and_original_save_destination(
    make_window: Callable[..., AppWindow], tmp_path: Path
) -> None:
    original_path = tmp_path / "original.json"
    write_graph(original_path)
    original_contents = original_path.read_text(encoding="utf-8")
    window = make_window(use_session=True)
    window.openDocument(str(original_path))
    window._document.addEmbeddedModule()
    module_count = window._document.modules_model.rowCount()
    assert window.close()
    assert window._document._engine._closed
    assert original_path.read_text(encoding="utf-8") == original_contents

    restored = make_window(use_session=True)
    assert restored._document_path == original_path
    assert list(restored._document.graph_model.nodes()) == ["example"]
    assert restored._document.modules_model.rowCount() == module_count
    assert str(restored._session_path) not in restored._recent_graphs


@pytest.mark.parametrize("close_anyway", [False, True])
def test_session_save_failure_can_cancel_close(
    make_window: Callable[..., AppWindow],
    monkeypatch: pytest.MonkeyPatch,
    close_anyway: bool,
) -> None:
    window = make_window(use_session=True)
    monkeypatch.setattr(window._document, "save", Mock(side_effect=OSError("disk full")))
    answer = QMessageBox.StandardButton.Yes if close_anyway else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "warning", Mock(return_value=answer))
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() == close_anyway
    assert window._document._engine._closed == close_anyway


def test_disabled_session_still_closes_document(
    make_window: Callable[..., AppWindow]
) -> None:
    window = make_window(use_session=False)
    assert window.close()
    assert window._document._engine._closed
    assert not window._session_path.exists()


def test_broken_session_does_not_reuse_original_save_path(
    make_window: Callable[..., AppWindow], tmp_path: Path, settings: QSettings
) -> None:
    (tmp_path / "session.json").write_text("broken", encoding="utf-8")
    settings.setValue("sessionDocumentPath", str(tmp_path / "previous.json"))
    window = make_window(use_session=True)
    assert window._document_path is None
    assert list(window._document.graph_model.nodes()) == []
