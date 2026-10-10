from pathlib import Path
import pytest
from qtpy.QtCore import QPointF
from pytestqt.qtbot import QtBot

from pyflow5.models.pyflow5_document import PyFlowDocument
import pygraphrt as rt

# def make_document(tmp_path: Path) -> tuple[PyFlowDocument, rt.NodeRef, rt.NodeRef]:
#     document = PyFlowDocument()
#     first = document._graph.local()
#     first.set_script("def op(*args, **kwargs): return args, kwargs")
#     path = tmp_path / "tools.py"
#     path.write_text("def op(): return 42", encoding="utf-8")
#     document.importModule(str(path))
#     second = document._graph.imports()[0]
#     source = document._graph.node()(rt.OperatorRef(second, "op"), name="source")
#     target = document._graph.node(
#         source, "source", 42, "42", True, None, 1.5,
#         nested={"type": "node", "name": "source", "values": [1, (2, 3)]},
#         path=Path("images/test.png"),
#     )(rt.OperatorRef(first, "op"), name="target")
#     document.graph_model().setNodePosition("target", QPointF(12, 34))
#     return document, source, target

from textwrap import dedent
def test_user_flow(qtbot: QtBot) -> None:
    # create new document
    document = PyFlowDocument()

    # set local module script
    local_module_index = document.modules_model.index(0, 0)
    document.modules_model.setData(
        local_module_index, 
        dedent("""\
        def hello():
            return "boom"
        """), 
        document.modules_model.SourceRole
    )

    hello_operator_index = document.modules_model.index(0, 0, local_module_index)
    operator = hello_operator_index.data(document.modules_model.OperatorRole)
    assert isinstance(operator, rt.OperatorRef)
    assert operator.get_name() == "hello"
    assert hello_operator_index.parent() == local_module_index

    # add node with operator
    document.addNode(hello_operator_index)
    assert list(document.graph_model.nodes()) == ["hello"]
    node = document.graph_model.mapToSource("hello")
    assert node is not None
    assert document._graph_rt.execute(node) == "boom"

if __name__ == "__main__":
    pytest.main([__file__])
