import copy
import json
from pathlib import Path

import pytest
from qtpy.QtCore import QPointF

from pyflow5.pyflow5_document import PyFlowDocument
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.import_module import ImportModuleRT
from pygraphrt.script_module import ScriptModuleRT


def make_document():
    document = PyFlowDocument()
    first = ScriptModuleRT("same_name", "def op(*args, **kwargs): return args, kwargs")
    second = ScriptModuleRT("same_name", "def op(): return 42")
    document.operatormodel().setModules([document._G.local(), first, second])
    source = document._G.node()(OperatorRef(second, "op"), name="source")
    target = document._G.node(
        source, "source", 42, "42", True, None, 1.5,
        nested={"type": "node", "name": "source", "values": [1, (2, 3)]},
        path=Path("images/test.png"),
    )(OperatorRef(first, "op"), name="target")
    document.graphmodel().setNodePosition("target", QPointF(12, 34))
    return document, source, target


def test_round_trip_types_modules_forward_references_and_positions(qapp):
    document, source, target = make_document()
    expected = document._G.execute(target)
    data = json.loads(document.serialize())
    data["nodes"] = dict(reversed(list(data["nodes"].items())))
    loaded = PyFlowDocument()
    loaded.fromdict(data)
    restored = loaded.graphmodel().getNode("target")
    restored_source = loaded.graphmodel().getNode("source")
    args, kwargs = restored.get_inputs()
    assert args[0] == restored_source
    assert args[1:] == ("source", 42, "42", True, None, 1.5)
    assert [type(v) for v in args[1:]] == [str, int, str, bool, type(None), float]
    assert kwargs["nested"] == {"type": "node", "name": "source", "values": [1, (2, 3)]}
    assert kwargs["path"] == Path("images/test.png")
    assert restored.get_operator().module is not restored_source.get_operator().module
    assert loaded._G.execute(restored) == expected
    assert loaded.graphmodel().nodePosition("target") == QPointF(12, 34)
    assert loaded.todict() == data


def test_load_retains_models_resets_selection_and_disconnects_old_runtime(qapp):
    document, source, target = make_document()
    old_graph = document._G
    models = (document.graphmodel(), document.operatormodel(), document.modulesmodel(), document.inspectormodel())
    document.graphselectionmodel().selectNode("target")
    document.set_output_locked(True)
    events = []
    document.graphmodel().modelAboutToBeReset.connect(lambda: events.append("before"))
    document.graphmodel().modelReset.connect(lambda: events.append("after"))
    document.fromdict(json.loads(document.serialize()))
    assert events == ["before", "after"]
    assert models == (document.graphmodel(), document.operatormodel(), document.modulesmodel(), document.inspectormodel())
    assert document._G is not old_graph
    assert document.graphselectionmodel().selectedNodes() == ()
    assert document.inspectormodel().node() is None
    assert document.get_output_node() is None
    assert not document.is_output_locked()
    assert document._watcher is None
    document.graphselectionmodel().selectNode("target")
    selected = document.get_output_node()
    old_graph.remove_node(target)
    assert document.get_output_node() == selected
    document.graphmodel().removeNodes(["target"])
    assert document.get_output_node() is None


@pytest.mark.parametrize("damage", ["version", "module", "reference", "position", "value"])
def test_failed_load_leaves_document_untouched(qapp, damage):
    document, source, target = make_document()
    original = document.todict()
    graph = document._G
    document.graphselectionmodel().selectNode("target")
    document.set_output_locked(True)
    watcher = document._watcher
    data = copy.deepcopy(original)
    if damage == "version":
        del data["version"]
    elif damage == "module":
        data["nodes"]["target"]["operator"]["module"] = "missing"
    elif damage == "reference":
        data["nodes"]["target"]["args"][0]["name"] = "missing"
    elif damage == "position":
        data["nodes"]["target"]["position"] = ["bad", 0]
    else:
        data["nodes"]["target"]["args"] = [{"type": "unknown"}]
    events = []
    document.graphmodel().modelReset.connect(lambda: events.append(True))
    with pytest.raises(ValueError):
        document.fromdict(data)
    assert document._G is graph
    assert document.todict() == original
    assert document.get_output_node() == target
    assert document._watcher is watcher
    assert document.is_output_locked()
    assert events == []


def test_imported_source_and_name_survive_without_external_file(qapp, tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 1", encoding="utf-8")
    document = PyFlowDocument()
    document.importModule(str(path))
    module = document.modulesmodel().index(2, 0).data(document.modulesmodel().ModuleRole)
    module.set_name("renamed")
    module.set_script("def op(): return 'edited'")
    text = document.serialize()
    path.unlink()
    document.deserialize(text)
    restored = document.modulesmodel().index(2, 0).data(document.modulesmodel().ModuleRole)
    assert isinstance(restored, ImportModuleRT)
    assert restored.path() == path
    assert restored.get_name() == "renamed"
    assert OperatorRef(restored, "op").get_value()() == "edited"


def test_invalid_script_and_missing_operator_remain_editable(qapp):
    document, source, target = make_document()
    source.get_operator().module.set_script("def op(:")
    document.deserialize(document.serialize())
    ref = document.graphmodel().getNode("source").get_operator()
    assert ref.get_value() is None
    assert ref.module.get_script() == "def op(:"
    ref.module.set_script("def op(): return 7")
    assert document._G.execute(document.graphmodel().getNode("source")) == 7


def test_save_rejects_opaque_values_without_overwriting_file(qapp, tmp_path):
    document, source, target = make_document()
    target.set_inputs(object())
    path = tmp_path / "document.pgraph"
    path.write_text("previous save", encoding="utf-8")
    with pytest.raises(TypeError, match="Cannot save input"):
        document.saveGraph(str(path))
    assert path.read_text(encoding="utf-8") == "previous save"


def test_save_and_open_file_preserve_unicode(qapp, tmp_path):
    document, source, target = make_document()
    target.set_inputs("Mása", greeting="こんにちは")
    path = tmp_path / "document.pgraph"
    document.saveGraph(str(path))
    loaded = PyFlowDocument()
    loaded.openGraph(str(path))
    assert loaded.todict() == document.todict()


def test_local_operator_is_rejected_explicitly(qapp):
    document = PyFlowDocument()

    @document._G.node()
    def local():
        return 1

    with pytest.raises(ValueError, match="script module"):
        document.serialize()


def test_window_load_and_empty_document_clear_editor(qtbot):
    from pyflow5.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    document, _, _ = make_document()
    window._document.fromdict(document.todict())
    assert window._code_editor.toPlainText().startswith("def op")
    assert len(window._document.graphmodel().nodes()) == 2
    window._document.fromdict({"version": 1, "modules": {}, "nodes": {}})
    assert window._code_editor.toPlainText() == ""
    assert list(window._document.graphmodel().nodes()) == []
