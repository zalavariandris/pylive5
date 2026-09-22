import json
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from pyflow5.pyflow5_document import PyFlowDocument
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from qtpy.QtCore import QPointF

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

