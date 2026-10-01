import pytest
from pytestqt.modeltest import ModelTester
from qtpy.QtCore import QModelIndex, Qt

from pyflow5.modules_operator_tree_model import ModulesOperatorsTreeModel
from pygraphrt import ImportModuleRT, ModuleRegistry, ScriptModuleRT
from pygraphrt.script_module import ScriptOperatorRef


@pytest.fixture
def model() -> ModulesOperatorsTreeModel:
    registry = ModuleRegistry()
    for module in [ScriptModuleRT("local"), ImportModuleRT("imported")]:
        module.set_script("def same() -> int: return 1\ndef extra() -> int: return 2")
        registry.add_module(module)
    model = ModulesOperatorsTreeModel()
    model.setSourceRegistry(registry)
    return model


def test_mapping_round_trips(model: ModulesOperatorsTreeModel) -> None:
    for module_row in range(model.rowCount()):
        module_index = model.index(module_row, 0)
        module = model.mapToSource(module_index)
        assert isinstance(module, ScriptModuleRT)
        assert model.mapFromSource(module) == module_index
        for operator_row, operator in enumerate(module.operators()):
            index = model.index(operator_row, 0, module_index)
            assert model.mapToSource(index) == operator
            assert model.mapFromSource(operator) == index
            assert model.mapFromSource(ScriptOperatorRef(module, operator.get_name())) == index
            assert index.parent() == module_index
            assert index.data() == operator.get_name()
            assert model.flags(index) == (
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
        assert model.flags(module_index) & Qt.ItemFlag.ItemIsSelectable


def test_invalid_indexes(model: ModulesOperatorsTreeModel) -> None:
    foreign = ModulesOperatorsTreeModel()
    for index in [
        QModelIndex(),
        foreign.createIndex(0, 0, 0),
        model.createIndex(99, 0, 0),
        model.createIndex(0, 0, 99),
        model.createIndex(99, 0, 1),
        model.createIndex(0, 1, 0),
    ]:
        assert model.mapToSource(index) is None
        assert model.data(index) is None
        assert model.flags(index) == Qt.ItemFlag.NoItemFlags


def test_unknown_and_removed_sources(model: ModulesOperatorsTreeModel) -> None:
    foreign_module = ScriptModuleRT("local")
    foreign_module.set_script("def same() -> int: return 1")
    assert not model.mapFromSource(foreign_module).isValid()
    assert not model.mapFromSource(ScriptOperatorRef(foreign_module, "same")).isValid()
    assert not model.mapFromSource(None).isValid()

    module = model.mapToSource(model.index(0, 0))
    assert isinstance(module, ScriptModuleRT)
    removed_operator = ScriptOperatorRef(module, "same")
    module.set_script("def extra() -> int: return 2")
    assert not model.mapFromSource(removed_operator).isValid()
    assert not model.mapFromSource(ScriptOperatorRef(module, "missing")).isValid()


def test_mapping_without_registry(model: ModulesOperatorsTreeModel) -> None:
    index = model.index(0, 0)
    module = model.mapToSource(index)
    model.setSourceRegistry(None)
    assert model.mapToSource(index) is None
    assert not model.mapFromSource(module).isValid()


def test_qt_model_contract(
    model: ModulesOperatorsTreeModel, qtmodeltester: ModelTester
) -> None:
    qtmodeltester.check(model)
