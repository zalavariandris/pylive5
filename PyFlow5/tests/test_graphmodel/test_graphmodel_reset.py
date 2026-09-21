from qtpy.QtCore import QPointF

from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.graph_rt import GraphRT
from qdageditor5.models.graph_selection_model import GraphSelectionModel


def test_reset_recovers_unfinished_edit_and_preserves_runtime(qapp):
    graph = GraphRT()

    @graph.node()
    def source():
        return 42

    @graph.node(value=source)
    def output(value):
        return value

    model = PyFlowRTModel(graph)
    selection = GraphSelectionModel(model)
    selection.selectNode("output")
    model.setNodePosition("output", QPointF(12, 34))
    model.setNodePosition("removed", QPointF(90, 90))
    cache = graph.cache
    links = list(model.links())
    events = []
    model.modelAboutToBeReset.connect(lambda: events.append("before"))
    model.modelReset.connect(lambda: events.append("after"))
    model._beginAddNodes(["unfinished"])

    model.reset()

    assert events == ["before", "after"]
    assert model._message_queue == []
    assert model._rt is graph
    assert graph.cache is cache
    assert graph.nodes() == [source, output]
    assert list(model.links()) == links
    assert model.nodePosition("output") == QPointF(12, 34)
    assert "removed" not in model._positions
    assert selection.selectedNodes() == ()
    assert selection.currentNode() is None
    assert graph.execute(output) == 42
    model.removeNodes(["output"])
    assert list(model.nodes()) == ["source"]


