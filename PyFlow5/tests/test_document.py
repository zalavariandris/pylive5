import json
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QPointF
from qtpy.QtWidgets import QApplication

from pyflow5.pyflow5_document import PyFlowDocument
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from pygraphrt.import_module import ImportModuleRT


def make_document(tmp_path: Path) -> tuple[PyFlowDocument, NodeRef, NodeRef]:
    document = PyFlowDocument()
    first = document._G.definitions()
    first.set_script("def op(*args, **kwargs): return args, kwargs")
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 42", encoding="utf-8")
    document.importModule(str(path))
    second = document._G.imports()[0]
    source = document._G.node()(OperatorRef(second, "op"), name="source")
    target = document._G.node(
        source, "source", 42, "42", True, None, 1.5,
        nested={"type": "node", "name": "source", "values": [1, (2, 3)]},
        path=Path("images/test.png"),
    )(OperatorRef(first, "op"), name="target")
    document.graphmodel().setNodePosition("target", QPointF(12, 34))
    return document, source, target


def test_round_trip_types_modules_forward_references_and_positions(qapp: QApplication, tmp_path: Path) -> None:
    document, _, target = make_document(tmp_path)
    expected = document._G.execute(target)
    path = tmp_path / "document.json"
    document.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["graph"]["nodes"] = dict(reversed(list(data["graph"]["nodes"].items())))
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = PyFlowDocument()
    loaded.open(path)
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
    loaded.save(path)
    assert json.loads(path.read_text(encoding="utf-8")) == data


def test_load_retains_models_resets_selection_and_disconnects_old_runtime(qapp: QApplication, tmp_path: Path) -> None:
    document, _, target = make_document(tmp_path)
    old_graph = document._G
    models = (document.graphmodel(), document.operatormodel(), document.modulesmodel(), document.graphdetailsmodel())
    document.graphselectionmodel().selectNode("target")
    document.set_output_locked(True)
    events: list[str] = []
    document.graphmodel().modelAboutToBeReset.connect(lambda: events.append("before"))
    document.graphmodel().modelReset.connect(lambda: events.append("after"))
    path = tmp_path / "document.json"
    document.save(path)
    document.open(path)
    assert events == ["before", "after"]
    assert models == (document.graphmodel(), document.operatormodel(), document.modulesmodel(), document.graphdetailsmodel())
    assert document._G is not old_graph
    assert document.graphselectionmodel().selectedNodes() == ()
    assert document.graphdetailsmodel().node() is None
    assert document.get_output_node() is None
    assert not document.is_output_locked()
    assert document._watcher is None
    document.graphselectionmodel().selectNode("target")
    selected = document.get_output_node()
    old_graph.remove_node(target)
    assert document.get_output_node() == selected
    document.graphmodel().removeNodes(["target"])
    assert document.get_output_node() is None


@pytest.mark.parametrize("damage", ["json", "version", "module", "reference", "position", "value"])
def test_failed_load_leaves_document_untouched(qapp: QApplication, tmp_path: Path, damage: str) -> None:
    document, _, _ = make_document(tmp_path)
    path = tmp_path / "document.json"
    document.save(path)
    original = path.read_text(encoding="utf-8")
    graph = document._G
    document.graphselectionmodel().selectNode("target")
    document.set_output_locked(True)
    watcher = document._watcher
    data = json.loads(original)
    if damage == "version":
        del data["version"]
    elif damage == "module":
        data["graph"]["nodes"]["target"]["operator"] = {"module": "missing", "name": "op"}
    elif damage == "reference":
        data["graph"]["nodes"]["target"]["args"][0]["name"] = "missing"
    elif damage == "position":
        data["graph"]["nodes"]["target"]["position"] = ["bad", 0]
    elif damage == "value":
        data["graph"]["nodes"]["target"]["args"] = [{"type": "unknown"}]
    path.write_text("{" if damage == "json" else json.dumps(data), encoding="utf-8")
    events: list[bool] = []
    document.graphmodel().modelReset.connect(lambda: events.append(True))
    with pytest.raises(ValueError):
        document.open(path)
    assert document._G is graph
    document.save(path)
    assert path.read_text(encoding="utf-8") == original
    assert document.get_output_node() == "target"
    assert document._watcher is watcher
    assert document.is_output_locked()
    assert events == []


def test_import_paths_and_aliases_reload_source(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 1", encoding="utf-8")
    document = PyFlowDocument()
    document.importModule(str(path))
    module = document._G.imports()[-1]
    module.set_name("renamed")
    document_path = tmp_path / "document.json"
    document.save(document_path)
    assert json.loads(document_path.read_text(encoding="utf-8"))["imports"]["renamed"] == str(path)
    path.write_text("def op(): return 'updated'", encoding="utf-8")
    document.open(document_path)
    restored = document._G.imports()[-1]
    assert isinstance(restored, ImportModuleRT)
    assert Path(restored.path()) == path
    assert restored.get_name() == "renamed"
    assert OperatorRef(restored, "op").get_value()() == "updated"


def test_editor_writes_imported_source_and_reports_failed_writes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyflow5.pyflow5_window import PyFlow5Window

    path = tmp_path / "tools.py"
    path.write_text("def op(): return 1", encoding="utf-8")
    window = PyFlow5Window()
    qtbot.addWidget(window)
    document = window._document
    document.importModule(str(path))
    model = document.modulesmodel()
    window._module_list_view.setCurrentIndex(model.index(model.rowCount() - 1, 0))
    source = "def op(): return 'edited'"
    window._code_editor.setPlainText(source)
    assert path.read_text(encoding="utf-8") == source
    assert document._G.imports()[-1].get_script() == source
    document_path = tmp_path / "document.json"
    document.save(document_path)
    assert json.loads(document_path.read_text(encoding="utf-8"))["imports"]["tools"] == str(path)

    def denied(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("read-only file")

    monkeypatch.setattr(Path, "write_text", denied)
    window._code_editor.setPlainText("def op(): return 3")
    assert document._G.imports()[-1].get_script() == source
    assert path.read_text(encoding="utf-8") == source
    assert "Cannot save source" in window.statusBar().currentMessage()


def test_invalid_script_and_missing_operator_remain_editable(qapp: QApplication, tmp_path: Path) -> None:
    document, _, _ = make_document(tmp_path)
    document._G.definitions().set_script("def op(:")
    path = tmp_path / "document.json"
    document.save(path)
    document.open(path)
    ref = document.graphmodel().getNode("target").get_operator()
    assert ref.get_value() is None
    assert ref.module.get_script() == "def op(:"
    ref.module.set_script("def op(): return 7")
    target = document.graphmodel().getNode("target")
    target.set_inputs()
    assert document._G.execute(target) == 7


def test_save_rejects_opaque_values_without_overwriting_file(qapp: QApplication, tmp_path: Path) -> None:
    document, _, target = make_document(tmp_path)
    target.set_inputs(object())
    path = tmp_path / "document.json"
    path.write_text("previous save", encoding="utf-8")
    with pytest.raises(TypeError, match="Cannot save input"):
        document.save(path)
    assert path.read_text(encoding="utf-8") == "previous save"


def test_save_and_open_file_preserve_unicode(qapp: QApplication, tmp_path: Path) -> None:
    document, _, target = make_document(tmp_path)
    target.set_inputs("M\u00e1sa", greeting="\u3053\u3093\u306b\u3061\u306f")
    path = tmp_path / "document.json"
    document.save(str(path))
    original = path.read_text(encoding="utf-8")
    loaded = PyFlowDocument()
    loaded.open(str(path))
    assert loaded.graphmodel().getNode("target").get_inputs() == (
        ("M\u00e1sa",), {"greeting": "\u3053\u3093\u306b\u3061\u306f"}
    )
    loaded.save(str(path))
    assert path.read_text(encoding="utf-8") == original


def test_local_operator_is_rejected_explicitly(qapp: QApplication, tmp_path: Path) -> None:
    document = PyFlowDocument()

    @document._G.node()
    def local() -> int:
        return 1

    path = tmp_path / "document.json"
    with pytest.raises(ValueError, match="script module"):
        document.save(path)
    assert not path.exists()


def test_window_load_and_empty_document_clear_editor(qtbot: QtBot, tmp_path: Path) -> None:
    from pyflow5.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    document, _, _ = make_document(tmp_path)
    path = tmp_path / "document.json"
    document.save(path)
    window._document.open(path)
    assert window._code_editor.toPlainText().startswith("def op")
    assert len(window._document.graphmodel().nodes()) == 2
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    window._document.open(path)
    assert window._code_editor.toPlainText() == ""
    assert list(window._document.graphmodel().nodes()) == []


@pytest.fixture
def document(tmp_path: Path) -> PyFlowDocument:
    path = tmp_path / "document.json"
    path.write_text(json.dumps({
        "version": 1,
        "modules": {
            "module_2": {
                "type": "script",
                "name": "utils",
                "source": "def the_name():\n    return \"Masa\"\n    \ndef hello_world(name:str, greeting:str='Hello'):\n    return f\"{greeting} {name}!\""
            }
        },
        "nodes": {
            "hello_world": {
                "operator": {
                    "module": "module_2",
                    "name": "hello_world"
                },
                "args": [],
                "kwargs": {
                    "name": {
                        "type": "node",
                        "name": "the_name"
                    }
                },
                "position": [
                    143.0,
                    181.0
                ]
            },
            "the_name": {
                "operator": {
                    "module": "module_2",
                    "name": "the_name"
                },
                "args": [],
                "kwargs": {},
                "position": [
                    126.0,
                    115.0
                ]
            }
        }
    }), encoding="utf-8")
    doc = PyFlowDocument()
    doc.open(path)
    return doc


def test_compact_empty_document_round_trip(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "document.json"
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    document = PyFlowDocument()
    document.open(path)
    document.save(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}
    document.open(path)
    document.save(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}

def test_document_follow_current_node(qtbot, document):
    name = document.graphmodel().nodes()[0]
    document.graphselectionmodel().selectNode(name)
    assert document.graphdetailsmodel().node() == name
    assert document.graphdetailsmodel().rowCount() > 0
    document.graphselectionmodel().clearSelection()
    assert document.graphdetailsmodel().node() is None