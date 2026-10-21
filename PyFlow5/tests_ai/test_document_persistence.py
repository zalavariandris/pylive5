import json
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QPointF

import pyflow5.models.pyflow5_document as document_module
from pyflow5.core.file_io import write_text_atomic
from pyflow5.models.pyflow5_document import FileChangedError, PyFlowDocument


def graph_text() -> str:
    return json.dumps({
        "version": 3,
        "modules": {"local": {"type": "embedded", "source": "def operation(value=42): return value\n"}},
        "graph": {"nodes": {"example": {
            "operator": {"module": "local", "name": "operation"},
            "args": [{"type": "literal", "value": 12}], "position": [123, -456],
        }}},
    })


@pytest.fixture
def make_document(qapp: object) -> Iterator[Callable[[], PyFlowDocument]]:
    documents: list[PyFlowDocument] = []

    def make() -> PyFlowDocument:
        document = PyFlowDocument.deserialize(graph_text())
        documents.append(document)
        return document

    yield make
    for document in documents:
        document.close()


def test_roundtrip_and_evaluation_are_clean(make_document: Callable, qtbot: QtBot) -> None:
    document = make_document()
    assert document.graph_model.nodePosition("example") == QPointF(123, -456)
    assert json.loads(document.serialize()) == json.loads(graph_text())
    assert document.filePath() is None
    assert document.fileStat() is None
    with qtbot.waitSignal(document._engine.evaluated):
        document.requestNodeExecution("example")
    assert not document.isModified()


def test_content_changes_mark_modified(make_document: Callable) -> None:
    document = make_document()
    document.graph_model.setNodePosition("example", QPointF(1, 2))
    assert document.isModified()
    document.setModified(False)
    document.graph_model.mapToSource("example").set_inputs(99)
    assert document.isModified()
    document.setModified(False)
    document._engine._registry.modules()[0].set_script("# comment\ndef operation(value=42): return value\n")
    document._engine._registry.modules()[0]._evaluate()
    assert document.isModified()
    document.setModified(False)
    document.modules_model.addEmbeddedModule()
    assert document.isModified()


def test_save_as_then_save_reuses_binding(make_document: Callable, tmp_path: Path) -> None:
    document = make_document()
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    document.saveAs(first)
    assert document.filePath() == first
    assert not document.isModified()
    document.graph_model.setNodePosition("example", QPointF(7, 8))
    document.save()
    first_contents = first.read_text(encoding="utf-8")
    document.graph_model.setNodePosition("example", QPointF(9, 10))
    document.saveAs(second)
    assert document.filePath() == second
    assert first.read_text(encoding="utf-8") == first_contents
    restored = PyFlowDocument.open(second)
    try:
        assert restored.filePath() == second
        assert restored.fileStat() == document.fileStat()
        assert restored.graph_model.nodePosition("example") == QPointF(9, 10)
        assert not restored.isModified()
    finally:
        restored.close()


@pytest.mark.parametrize("remove", [False, True])
def test_external_changes_require_override(make_document: Callable, tmp_path: Path, remove: bool) -> None:
    document = make_document()
    path = tmp_path / "graph.json"
    document.saveAs(path)
    if remove:
        path.unlink()
    else:
        path.write_text("external changes", encoding="utf-8")
    with pytest.raises(FileChangedError):
        document.save()
    document.save(override=True)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3


@pytest.mark.parametrize("failure", ["serialize", "write"])
def test_failed_save_as_preserves_binding_and_contents(
    make_document: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    document = make_document()
    original, destination = tmp_path / "original.json", tmp_path / "destination.json"
    document.saveAs(original)
    previous_stat = document.fileStat()
    destination.write_text("existing destination", encoding="utf-8")
    document.setModified(True)
    if failure == "serialize":
        monkeypatch.setattr(document, "serialize", Mock(side_effect=ValueError("cannot encode")))
    else:
        monkeypatch.setattr(document_module, "write_text_atomic", Mock(side_effect=OSError("disk full")))
    with pytest.raises((ValueError, OSError)):
        document.saveAs(destination)
    assert document.filePath() == original
    assert document.fileStat() == previous_stat
    assert document.isModified()
    assert destination.read_text(encoding="utf-8") == "existing destination"


def test_failed_atomic_replace_keeps_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "graph.json"
    path.write_text("original", encoding="utf-8")
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("cannot replace")))
    with pytest.raises(OSError):
        write_text_atomic(path, "replacement")
    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_serialize_preserves_binding_and_modified_state(make_document: Callable, tmp_path: Path) -> None:
    document = make_document()
    path = tmp_path / "graph.json"
    document.saveAs(path)
    stat = document.fileStat()
    document.setModified(True)
    document.serialize()
    assert document.filePath() == path
    assert document.fileStat() == stat
    assert document.isModified()


@pytest.mark.parametrize("payload", [
    [], {}, {"version": 999, "graph": {}}, {"version": True, "graph": {}},
    {"version": 3, "graph": []}, {"version": 3, "graph": {"nodes": []}},
])
def test_invalid_document_is_rejected(qapp: object, payload: object) -> None:
    with pytest.raises(ValueError):
        PyFlowDocument.deserialize(json.dumps(payload))


@pytest.mark.parametrize("position", [[1], [1, 2, 3], [True, 0], [float("nan"), 0], ["1", 2], None])
def test_invalid_positions_are_rejected(qapp: object, position: object) -> None:
    data = json.loads(graph_text())
    data["graph"]["nodes"]["example"]["position"] = position
    with pytest.raises(ValueError, match="position"):
        PyFlowDocument.deserialize(json.dumps(data))


def test_unbound_save_requires_destination(make_document: Callable) -> None:
    with pytest.raises(ValueError, match="file path"):
        make_document().save()
