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
    first = document._G.local()
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

from textwrap import dedent
def test_user_flow(qtbot: QtBot) -> None:
    # create new document
    document = PyFlowDocument()

    # set local module script
    local_module_index = document.modulesmodel.index(0, 0)
    document.modulesmodel.setData(
        local_module_index, 
        dedent("""\
        def hello():
            return "boom"
        """), 
        document.modulesmodel.SourceRole
    )

    hello_operator_index = document.modulesmodel.index(0, 0, local_module_index)
    operator = hello_operator_index.data(document.modulesmodel.OperatorRole)
    assert isinstance(operator, OperatorRef)
    assert operator.get_name() == "hello"
    assert hello_operator_index.parent() == local_module_index

    # add node with operator
    document.addNode(hello_operator_index)
    assert list(document.graphmodel.nodes()) == ["hello"]
    node = document.graphmodel.getNode("hello")
    assert node is not None
    assert document._G.execute(node) == "boom"

if __name__ == "__main__":
    pytest.main([__file__])
