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


def test_window_reset_action_clears_output_and_interactions(qtbot):
    from pyflow5.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    graph = window._G
    model = window._model
    script = window._code_editor.toPlainText()

    @graph.node()
    def answer():
        return 42

    window._selection.selectNode("answer")
    watcher = window._watcher
    assert watcher is not None
    assert window._display_widget.label.text() == "42"
    window._graph_view._tool = object()
    window._graph_view._hovered_item = object()
    window._graph_view._press_pos = QPointF(1, 2)
    window._graph_view._pressed = True
    model._beginAddNodes(["unfinished"])

    assert window._restart_kernel_action.text() == "Reset Graph View"
    window._restart_kernel_action.trigger()

    assert window._G is graph
    assert window._model is model
    assert graph.nodes() == [answer]
    assert window._code_editor.toPlainText() == script
    assert window._selection.selectedNodes() == ()
    assert window.get_output_node() is None
    assert window._watcher is None
    assert not watcher._running
    assert window._display_widget.label.text() == ""
    assert window._graph_view._tool is None
    assert window._graph_view._hovered_item is None
    assert window._graph_view._press_pos is None
    assert not window._graph_view._pressed
    answer.set_inputs()
    assert window._display_widget.label.text() == ""
    window.reset_graph()
    assert model._message_queue == []
