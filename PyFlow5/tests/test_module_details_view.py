from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QItemSelectionModel, QModelIndex, QSettings, Qt
from qtpy.QtGui import QCloseEvent, QStandardItem, QStandardItemModel

from pyflow5.views.module_details_view import ModuleDetailsView
from pyflow5.models.operators_model import OperatorsModel
from pyflow5.models.pyflow5_document import PyFlowDocument
from pyflow5.views import pyflow5_documentwindow
from pygraphrt import ModuleRegistry, ScriptModuleRT


@pytest.fixture
def view(qtbot: QtBot) -> ModuleDetailsView:
    registry = ModuleRegistry()
    for name in ("first", "second"):
        module = ScriptModuleRT(name)
        module.set_script(f"value = {name!r}")
        module.evaluate()
        registry.add_module(module)
    model = OperatorsModel()
    model.setSourceRegistry(registry)
    view = ModuleDetailsView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setSelectionModel(QItemSelectionModel(model, view))
    return view


def select(view: ModuleDetailsView, row: int) -> QModelIndex:
    index = view.model().index(row, 0)
    view.selection().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    return index


def test_select_edit_and_undo(view: ModuleDetailsView) -> None:
    index = select(view, 0)
    editor = view._code_editor
    assert editor.isEnabled()
    assert editor.toPlainText() == "value = 'first'"
    assert view._title_label.text() == "first"

    editor.insertPlainText("# comment\n")
    assert index.data(OperatorsModel.SourceRole) == "# comment\nvalue = 'first'"
    assert editor.textCursor().position() == len("# comment\n")
    assert editor.document().isUndoAvailable()
    editor.undo()
    assert index.data(OperatorsModel.SourceRole) == "value = 'first'"


def test_model_changes_refresh_without_selection_model(view: ModuleDetailsView) -> None:
    view.setSelectionModel(None)
    index = view.model().index(0, 0)
    view.setCurrentIndex(index)
    view.model().setData(index, "value = 42", OperatorsModel.SourceRole)
    assert view._code_editor.toPlainText() == "value = 42"


def test_imported_source_is_read_only_and_embedded_source_stays_editable(
    view: ModuleDetailsView, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = tmp_path / "external.py"
    source = "value = 123"
    path.write_text(source, encoding="utf-8")
    model = view.model()
    imported_index = model.importModule(path)
    select(view, 0)

    # Displaying source must not feed a textChanged signal back into the model.
    with qtbot.assertNotEmitted(model.dataChanged):
        select(view, imported_index.row())
    editor = view._code_editor
    assert editor.isEnabled()
    assert editor.isReadOnly()
    assert editor.toPlainText() == source
    editor.selectAll()
    assert editor.textCursor().selectedText() == source

    qtbot.keyClicks(editor, "replacement")
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    qtbot.keyClick(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == source
    assert imported_index.data(model.SourceRole) == source
    assert path.read_text(encoding="utf-8") == source

    with qtbot.assertNotEmitted(model.dataChanged):
        embedded_index = select(view, 0)
    assert embedded_index.data(model.ReadOnlyRole) is False
    assert not editor.isReadOnly()
    editor.selectAll()
    qtbot.keyClicks(editor, "value = 456")
    assert embedded_index.data(model.SourceRole) == "value = 456"


def test_deselection_and_reset_clear_editor(view: ModuleDetailsView) -> None:
    select(view, 0)
    view.selection().clearSelection()
    assert not view.currentIndex().isValid()
    assert not view._code_editor.isEnabled()
    assert view._code_editor.toPlainText() == ""

    select(view, 1)
    view.model().setSourceRegistry(ModuleRegistry())
    assert not view.currentIndex().isValid()
    assert not view._code_editor.isEnabled()
    assert view._title_label.text() == "<No Selection>"
    assert view._code_editor.toPlainText() == ""


def test_current_changes_within_existing_selection(view: ModuleDetailsView) -> None:
    first = select(view, 0)
    second = view.model().index(1, 0)
    selection = view.selection()
    selection.select(second, QItemSelectionModel.SelectionFlag.Select)
    selection.setCurrentIndex(second, QItemSelectionModel.SelectionFlag.NoUpdate)
    assert view.currentIndex() == second
    selection.setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)
    assert view.currentIndex() == first
    selection.select(first, QItemSelectionModel.SelectionFlag.Deselect)
    assert view.currentIndex() == second


def test_switch_models_disconnects_previous_model(view: ModuleDetailsView) -> None:
    old_index = select(view, 0)
    old_model = view.model()
    old_selection = view.selection()
    new_model = QStandardItemModel(view)
    item = QStandardItem("new")
    item.setData("value = 3", OperatorsModel.SourceRole)
    new_model.appendRow(item)
    selection = QItemSelectionModel(new_model, view)
    selection.setCurrentIndex(new_model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    view.setModel(new_model)
    view.setSelectionModel(selection)
    assert view._code_editor.toPlainText() == "value = 3"

    old_model.setData(old_index, "value = 99", OperatorsModel.SourceRole)
    old_selection.clear()
    old_model.setSourceRegistry(None)
    assert view._code_editor.toPlainText() == "value = 3"
    view.setModel(None)
    assert not view.currentIndex().isValid()
    assert not view._code_editor.isEnabled()


def test_removal_tracks_current_item_and_clears_removed_item(view: ModuleDetailsView) -> None:
    model = QStandardItemModel(view)
    for name in ("first", "second"):
        item = QStandardItem(name)
        item.setData(name, OperatorsModel.SourceRole)
        model.appendRow(item)
    view.setModel(model)
    view.setCurrentIndex(model.index(1, 0))
    model.removeRow(0)
    assert view.currentIndex() == model.index(0, 0)
    assert view._code_editor.toPlainText() == "second"
    model.removeRow(0)
    assert not view.currentIndex().isValid()
    assert not view._code_editor.isEnabled()
    assert view._code_editor.toPlainText() == ""


def test_operator_without_source_disables_editor(view: ModuleDetailsView) -> None:
    module = select(view, 0)
    view.model().setData(module, "def hello(): return 42", OperatorsModel.SourceRole)
    view.setCurrentIndex(view.model().index(0, 0, module))
    assert view._title_label.text() == "hello"
    assert not view._code_editor.isEnabled()
    assert view._code_editor.toPlainText() == ""


def test_window_connects_module_details(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TestSettings(QSettings):
        def __init__(self, *_args: object) -> None:
            super().__init__(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    class TestWindow(pyflow5_documentwindow.PyFlow5DocumentWindow):
        def closeEvent(self, event: QCloseEvent) -> None:
            event.accept()

    monkeypatch.setattr(pyflow5_documentwindow, "QSettings", TestSettings)
    window = TestWindow()
    qtbot.addWidget(window)
    window.addEmbeddedModule()
    view = window._registry_panel
    assert view.model() is window._document.registry_model
    assert view.currentIndex().isValid()
    assert view._code_editor.isEnabled()
    view._code_editor.setPlainText("def hello(): return 42")
    assert window._document._module_registry.modules()[0].get_source() == "def hello(): return 42"

    window.setDocument(PyFlowDocument())
    assert not view.currentIndex().isValid()
    assert view._code_editor.toPlainText() == ""
    window._document.createEmbeddedModule()
    assert view.currentIndex() == window._document.registry_model.index(0, 0)
    assert view._code_editor.isEnabled()
