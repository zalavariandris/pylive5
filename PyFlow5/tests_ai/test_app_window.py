import json
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication, QEvent, QPointF, QSettings
from qtpy.QtGui import QAction, QCloseEvent
from qtpy.QtWidgets import QFileDialog, QMenu, QMessageBox

import pyflow5.app_window as app_module
import pyflow5.models.pyflow5_document as document_module
from pyflow5.app_window import AppWindow
from pyflow5.models.pyflow5_document import FileChangedError, PyFlowDocument


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def make_window(
    qtbot: QtBot, settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., AppWindow]]:
    windows: list[AppWindow] = []
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=QMessageBox.StandardButton.Cancel))
    monkeypatch.setattr(QMessageBox, "warning", Mock(return_value=QMessageBox.StandardButton.No))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", Mock(return_value=("", "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", Mock(return_value=("", "")))

    def make(*, use_session: bool = False) -> AppWindow:
        window = AppWindow(use_session=use_session, settings=settings)
        windows.append(window)
        qtbot.addWidget(window)
        return window

    yield make
    for window in windows:
        window.currentDocumentWindow().dispose()
        window._closed = True
        window.close()


def write_graph(path: Path) -> None:
    path.write_text(json.dumps({
        "version": 3,
        "modules": {"local": {"type": "embedded", "source": "def operation(): return 42\n"}},
        "graph": {"nodes": {"example": {
            "operator": {"module": "local", "name": "operation"}, "position": [123, 456],
        }}},
    }), encoding="utf-8")


def menu(window: AppWindow, text: str) -> QMenu:
    result = next(item.menu() for item in window.menuBar().actions() if item.text() == text)
    assert result is not None
    return result


def action(window: AppWindow, menu_text: str, text: str) -> QAction:
    return next(item for item in menu(window, menu_text).actions() if item.text() == text)


def test_open_new_open_rebinds_views_and_closes_previous(
    make_window: Callable, tmp_path: Path, qtbot: QtBot,
) -> None:
    window = make_window()
    editor = window.currentDocumentWindow()
    first = editor.document()
    path = tmp_path / "graph.json"
    write_graph(path)
    assert window.openDocument(path)
    loaded = editor.document()
    assert first._engine._closed
    assert editor._graph_view._model is loaded.graph_model
    assert editor._modules_listview.model() is loaded.modules_model
    assert editor._node_inlet_tree_view.model() is loaded.node_inlet_tree_adapter
    assert editor._viewer.model() is loaded.node_inlet_tree_adapter
    assert editor._node_inspector.model() is loaded.node_inlet_tree_adapter
    with qtbot.waitSignal(loaded._engine.evaluated):
        loaded.requestNodeExecution("example")
    assert loaded.graph_model.nodePosition("example") == QPointF(123, 456)
    assert not loaded.isModified()
    assert window.windowTitle() == "PyFlow5 - graph.json"
    assert window.newDocument()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert loaded._engine._closed
    assert window.currentDocumentWindow() is editor
    assert editor.document().filePath() is None
    assert window.windowTitle() == "PyFlow5 - Untitled"
    assert window.openDocument(path)
    assert len(window.menuBar().actions()) == 3


def test_file_menu_delegates_to_editor(make_window: Callable, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window()
    editor = window.currentDocumentWindow()
    for label, method, arguments in (
        ("New", "newDocument", ()), ("Open Graph", "open", ("",)),
        ("Save Graph", "save", ()), ("Save Graph As", "saveAs", ()),
    ):
        callback = Mock()
        monkeypatch.setattr(editor, method, callback)
        action(window, "File", label).trigger()
        callback.assert_called_once_with(*arguments)
    editor._left_tabwidget.setCurrentWidget(editor._modules_panel)
    action(window, "View", "Go to Graph Panel").trigger()
    assert editor._left_tabwidget.currentWidget() is editor._graph_panel


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_open_keeps_document(make_window: Callable, tmp_path: Path, cancel: bool) -> None:
    window = make_window()
    document = window.currentDocumentWindow().document()
    path = tmp_path / "broken.json"
    path.write_text("invalid json", encoding="utf-8")
    assert not window.openDocument("" if cancel else path)
    assert window.currentDocumentWindow().document() is document
    assert not document._engine._closed
    assert window._recent_graphs == []


def test_failed_binding_closes_candidate_and_restores_previous(
    make_window: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = make_window()
    editor = window.currentDocumentWindow()
    previous = editor.document()
    candidate = PyFlowDocument()
    monkeypatch.setattr(PyFlowDocument, "open", lambda path: candidate)
    original_set_model = editor._graph_view.setModel

    def set_model(model: object) -> None:
        if model is candidate.graph_model:
            raise RuntimeError("cannot bind")
        original_set_model(model)

    monkeypatch.setattr(editor._graph_view, "setModel", set_model)
    assert not window.openDocument(tmp_path / "graph.json")
    assert candidate._engine._closed
    assert editor.document() is previous
    assert not previous._engine._closed
    assert editor._graph_view._model is previous.graph_model


def test_save_and_save_as_update_binding_recents_and_title(
    make_window: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = make_window()
    document = window.currentDocumentWindow().document()
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    dialog = Mock(return_value=(str(first), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", dialog)
    document.modules_model.addEmbeddedModule()
    assert window.windowTitle() == "PyFlow5 - Untitled*"
    assert window.saveCurrentDocument()
    assert document.filePath() == first
    assert window.windowTitle() == "PyFlow5 - first.json"
    document.modules_model.addEmbeddedModule()
    assert window.saveCurrentDocument()
    dialog.assert_called_once()
    first_contents = first.read_text(encoding="utf-8")
    dialog.return_value = (str(second), "")
    assert window.saveDocumentAs()
    assert document.filePath() == second
    assert window.windowTitle() == "PyFlow5 - second.json"
    assert first.read_text(encoding="utf-8") == first_contents
    assert window._recent_graphs == [str(second), str(first)]


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_save_as_preserves_binding(
    make_window: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool,
) -> None:
    window = make_window()
    original = tmp_path / "original.json"
    write_graph(original)
    assert window.openDocument(original)
    document = window.currentDocumentWindow().document()
    document.setModified(True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("" if cancel else str(tmp_path / "new.json"), ""))
    monkeypatch.setattr(document_module, "write_text_atomic", Mock(side_effect=OSError("disk full")))
    assert not window.saveDocumentAs()
    assert document.filePath() == original
    assert document.isModified()
    assert window._recent_graphs == [str(original)]


@pytest.mark.parametrize("accept", [False, True])
def test_external_change_prompt(
    make_window: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accept: bool,
) -> None:
    window = make_window()
    path = tmp_path / "graph.json"
    write_graph(path)
    assert window.openDocument(path)
    path.write_text("external change", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No))
    assert window.saveCurrentDocument() == accept
    if accept:
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3
    else:
        assert path.read_text(encoding="utf-8") == "external change"


@pytest.mark.parametrize("operation", ["new", "open", "close"])
@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Save])
def test_unsaved_prompt(
    make_window: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    operation: str, answer: QMessageBox.StandardButton,
) -> None:
    window = make_window()
    document = window.currentDocumentWindow().document()
    document.modules_model.addEmbeddedModule()
    saved_path, opened_path = tmp_path / "saved.json", tmp_path / "opened.json"
    write_graph(opened_path)
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=answer))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(saved_path), ""))
    if operation == "new":
        accepted = window.newDocument()
    elif operation == "open":
        accepted = window.openDocument(opened_path)
    else:
        accepted = window.close()
    assert accepted == (answer != QMessageBox.StandardButton.Cancel)
    assert document._engine._closed == accepted
    assert saved_path.exists() == (answer == QMessageBox.StandardButton.Save)
    if not accepted:
        assert window.currentDocumentWindow().document() is document


def test_cancelled_save_blocks_new(make_window: Callable, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window()
    document = window.currentDocumentWindow().document()
    document.setModified(True)
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=QMessageBox.StandardButton.Save))
    assert not window.newDocument()
    assert window.currentDocumentWindow().document() is document


def test_recent_menu(make_window: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window()
    paths = [str(tmp_path / f"{index}.json") for index in range(6)]
    for path in paths:
        window._rememberGraph(path)
    window._rememberGraph(paths[3])
    recent_menu = action(window, "File", "Recent Graphs").menu()
    recent_menu.aboutToShow.emit()
    assert [item.text() for item in recent_menu.actions()] == [paths[3], paths[5], paths[4], paths[2], paths[1]]
    callback = Mock()
    monkeypatch.setattr(window.currentDocumentWindow(), "open", callback)
    recent_menu.actions()[1].triggered.emit(True)
    callback.assert_called_once_with(paths[5])


@pytest.mark.parametrize("bound", [False, True])
def test_session_restores_unsaved_content_and_binding(make_window: Callable, tmp_path: Path, bound: bool) -> None:
    window = make_window(use_session=True)
    path = tmp_path / "original.json"
    write_graph(path)
    original_contents = path.read_text(encoding="utf-8")
    if bound:
        assert window.openDocument(path)
    document = window.currentDocumentWindow().document()
    stamp = document.fileStat()
    document.modules_model.addEmbeddedModule()
    module_count = document.modules_model.rowCount()
    assert window.close()
    assert document._engine._closed
    assert path.read_text(encoding="utf-8") == original_contents
    restored_window = make_window(use_session=True)
    restored = restored_window.currentDocumentWindow().document()
    assert restored.filePath() == (path if bound else None)
    assert restored.fileStat() == stamp
    assert restored.isModified()
    assert restored.modules_model.rowCount() == module_count
    assert restored_window.windowTitle().endswith("*")
    assert str(window._session_path) not in restored_window._recent_graphs


def test_session_preserves_external_change_baseline(make_window: Callable, tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    write_graph(path)
    window = make_window(use_session=True)
    assert window.openDocument(path)
    assert window.close()
    path.write_text("external modification while closed", encoding="utf-8")
    restored = make_window(use_session=True).currentDocumentWindow().document()
    assert not restored.isModified()
    with pytest.raises(FileChangedError):
        restored.save()


@pytest.mark.parametrize("close_anyway", [False, True])
def test_session_failure_preserves_previous_snapshot(
    make_window: Callable, monkeypatch: pytest.MonkeyPatch, close_anyway: bool,
) -> None:
    window = make_window(use_session=True)
    document = window.currentDocumentWindow().document()
    window._session_path.write_text("previous snapshot", encoding="utf-8")
    monkeypatch.setattr(app_module, "write_text_atomic", Mock(side_effect=OSError("disk full")))
    monkeypatch.setattr(QMessageBox, "warning", Mock(return_value=QMessageBox.StandardButton.Yes if close_anyway else QMessageBox.StandardButton.No))
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() == close_anyway
    assert document._engine._closed == close_anyway
    assert window._session_path.read_text(encoding="utf-8") == "previous snapshot"


def test_broken_session_ignores_previous_path(make_window: Callable, tmp_path: Path, settings: QSettings) -> None:
    (tmp_path / "session.json").write_text("broken", encoding="utf-8")
    settings.setValue("sessionDocumentPath", str(tmp_path / "previous.json"))
    document = make_window(use_session=True).currentDocumentWindow().document()
    assert document.filePath() is None
    assert not document.isModified()


def test_legacy_session_migration(make_window: Callable, tmp_path: Path, settings: QSettings) -> None:
    path = tmp_path / "graph.json"
    write_graph(path)
    (tmp_path / "session.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    settings.setValue("sessionDocumentPath", str(path))
    window = make_window(use_session=True)
    document = window.currentDocumentWindow().document()
    assert document.filePath() == path
    assert document.isModified()
    with pytest.raises(FileChangedError):
        document.save()
    assert window.close()
    assert json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))["session_version"] == 1


def test_replacing_selected_document_disconnects_old_views_and_signals(
    make_window: Callable, tmp_path: Path, qtbot: QtBot,
) -> None:
    path = tmp_path / "graph.json"
    write_graph(path)
    window = make_window()
    assert window.openDocument(path)
    editor = window.currentDocumentWindow()
    previous = editor.document()
    with qtbot.waitSignal(previous._engine.evaluated):
        editor.graphselection_model.selectNode("example")
    editor._navigate_to_current_node_operator()
    assert editor._module_details_view.currentIndex().isValid()
    assert window.newDocument()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert editor.graphselection_model.currentNode() is None
    assert not editor._module_details_view.currentIndex().isValid()
    previous.setModified(True)
    previous.filePathChanged.emit(path)
    assert window.windowTitle() == "PyFlow5 - Untitled"


def test_restored_session_can_save_to_original_file(make_window: Callable, tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    write_graph(path)
    window = make_window(use_session=True)
    assert window.openDocument(path)
    window.currentDocumentWindow().document().graph_model.setNodePosition("example", QPointF(789, 321))
    assert window.close()
    restored_window = make_window(use_session=True)
    assert restored_window.saveCurrentDocument()
    restored = restored_window.currentDocumentWindow().document()
    assert not restored.isModified()
    assert json.loads(path.read_text(encoding="utf-8"))["graph"]["nodes"]["example"]["position"] == [789, 321]


def test_disabled_session_does_not_restore_or_overwrite_snapshot(
    make_window: Callable, tmp_path: Path,
) -> None:
    snapshot = tmp_path / "session.json"
    snapshot.write_text("existing snapshot", encoding="utf-8")
    window = make_window()
    document = window.currentDocumentWindow().document()
    assert document.filePath() is None
    assert window.close()
    assert document._engine._closed
    assert snapshot.read_text(encoding="utf-8") == "existing snapshot"
