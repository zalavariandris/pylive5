from pathlib import Path

import pytest
from pytestqt.modeltest import ModelTester
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QItemSelectionModel, QModelIndex, Qt
from qtpy.QtTest import QSignalSpy

from myqtx.selection_dialog import SelectionDialog
from pyflow5.modules_operator_tree_model import ModulesOperatorsTreeModel
from pyflow5.pyflow5_document import PyFlowDocument
from pyflow5.pyflow5_window import ModuleDetailsView
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import GraphRT


@pytest.fixture
def model(qtbot: QtBot, tmp_path: Path) -> ModulesOperatorsTreeModel:
    graph = GraphRT()
    graph.local().set_script("def same() -> int: return 1")
    model = ModulesOperatorsTreeModel()
    model.setGraph(graph)
    path = tmp_path / "operators.py"
    path.write_text(
        "def same() -> int: return 2\ndef z_extra() -> int: return 3",
        encoding="utf-8",
    )
    model.importModule(str(path))
    return model


def reject_mapping(*args: object) -> None:
    raise AssertionError("Model operations must not depend on mapping helpers")


def test_model_without_mapping_helpers(
    model: ModulesOperatorsTreeModel,
    monkeypatch: pytest.MonkeyPatch,
    qtmodeltester: ModelTester,
) -> None:
    monkeypatch.setattr(model, "mapToSource", reject_mapping)
    monkeypatch.setattr(model, "mapFromSource", reject_mapping)
    qtmodeltester.check(model)

    local = model.index(0, 0)
    imported = model.index(1, 0)
    assert model.rowCount() == 2
    assert model.rowCount(local) == 1
    assert model.rowCount(imported) == 2
    assert model.index(0, 0, local) != model.index(0, 0, imported)
    for module_index, value in [(local, 1), (imported, 2)]:
        operator_index = model.index(0, 0, module_index)
        assert operator_index.parent() == module_index
        assert model.rowCount(operator_index) == 0
        assert operator_index.data() == "same"
        assert operator_index.data(model.OperatorRole)() == value
        assert operator_index.data(model.ModuleRole) is None
        assert operator_index.data(model.SourceRole) is None
        assert model.flags(operator_index) & Qt.ItemFlag.ItemIsSelectable


def test_mapping_round_trips_and_invalid_indexes(
    model: ModulesOperatorsTreeModel,
) -> None:
    for row in range(model.rowCount()):
        module_index = model.index(row, 0)
        assert model.mapFromSource(model.mapToSource(module_index)) == module_index
        for child_row in range(model.rowCount(module_index)):
            operator_index = model.index(child_row, 0, module_index)
            operator = model.mapToSource(operator_index)
            assert isinstance(operator, OperatorRef)
            assert model.mapFromSource(operator) == operator_index

    foreign = ModulesOperatorsTreeModel()
    foreign.setGraph(GraphRT())
    for index in [
        QModelIndex(),
        foreign.index(0, 0),
        model.createIndex(99, 0, 0),
        model.createIndex(0, 0, 99),
        model.createIndex(0, 1, 0),
    ]:
        assert model.data(index) is None
        assert model.flags(index) == Qt.ItemFlag.NoItemFlags
        assert model.mapToSource(index) is None
        assert not model.setData(index, "", model.SourceRole)
        assert not model.removeModule(index)


def test_mutations_without_mapping_helpers(
    model: ModulesOperatorsTreeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model, "mapToSource", reject_mapping)
    monkeypatch.setattr(model, "mapFromSource", reject_mapping)
    local = model.index(0, 0)
    imported = model.index(1, 0)
    source = "def replacement() -> int: return 42"
    for module_index in [local, imported]:
        assert model.setData(module_index, source, model.SourceRole)
        assert module_index.data(model.SourceRole) == source
        assert model.index(0, 0, module_index).data(model.OperatorRole)() == 42
    assert not model.setData(local, 42, model.SourceRole)
    assert not model.setData(local, "renamed", Qt.ItemDataRole.EditRole)
    assert not model.removeModule(local)
    assert model.removeModule(imported)
    assert model.rowCount() == 1


def test_failed_import_does_not_start_insertion(
    model: ModulesOperatorsTreeModel, tmp_path: Path
) -> None:
    about_to_insert = QSignalSpy(model.rowsAboutToBeInserted)
    with pytest.raises(OSError):
        model.importModule(str(tmp_path))
    assert len(about_to_insert) == 0
    assert model.rowCount() == 2


def test_editor_to_operator_dialog(qtbot: QtBot) -> None:
    document = PyFlowDocument()
    model = document.modulesmodel
    selection = QItemSelectionModel(model)
    editor = ModuleDetailsView()
    qtbot.addWidget(editor)
    editor.setModel(model)
    editor.setSelectionModel(selection)
    selection.setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
    )
    editor._code_editor.setPlainText('def hello() -> str: return "hello"')

    dialog = SelectionDialog(model)
    qtbot.addWidget(dialog)
    dialog.show()
    selected = dialog.selected_index()
    assert selected.data() == "hello"
    document.addNode(selected)
    node = document.graphmodel.getNode("hello")
    assert document._G.execute(node) == "hello"
