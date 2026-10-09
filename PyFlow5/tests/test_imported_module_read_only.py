import json
from pathlib import Path

from pytestqt.qtbot import QtBot

from pyflow5.modules_operator_tree_model import ModulesOperatorsTreeModel
from pyflow5.pyflow5_document import PyFlowDocument
from pygraphrt import ImportModuleRT


def test_import_stays_read_only_after_document_save_and_load(
    tmp_path: Path, qtbot: QtBot,
) -> None:
    module_path = tmp_path / "external.py"
    source = "def value() -> int: return 1\n"
    module_path.write_text(source, encoding="utf-8")
    document = PyFlowDocument()
    document.importModule(module_path)
    model = document.modules_model
    index = model.index(0, 0)
    module = model.mapToSource(index)
    assert isinstance(module, ImportModuleRT)
    assert index.data(ModulesOperatorsTreeModel.ReadOnlyRole) is True
    assert index.data(ModulesOperatorsTreeModel.SourceRole) == source

    with qtbot.assertNotEmitted(model.dataChanged):
        assert not model.setData(index, "value = 2", model.SourceRole)
    assert module.get_source() == source
    assert module.get_operator_by_name("value")() == 1

    # Runtime edits are in memory; saving the document stores only the import path.
    module.set_script("def value() -> int: return 2\n")
    document_path = tmp_path / "graph.json"
    document.save(document_path)
    assert module_path.read_text(encoding="utf-8") == source
    data = json.loads(document_path.read_text(encoding="utf-8"))
    assert data["modules"][module_path.name] == {
        "type": "import", "path": str(module_path),
    }

    restored = PyFlowDocument.fromfile(document_path)
    restored_index = restored.modules_model.index(0, 0)
    assert restored_index.data(ModulesOperatorsTreeModel.ReadOnlyRole) is True
    assert restored_index.data(ModulesOperatorsTreeModel.SourceRole) == source
    assert not restored.modules_model.setData(
        restored_index, "value = 3", model.SourceRole,
    )
    assert module_path.read_text(encoding="utf-8") == source
