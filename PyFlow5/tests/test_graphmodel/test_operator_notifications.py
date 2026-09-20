from qtpy.QtCore import Qt
from qtpy.QtGui import QColor

from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import GraphRT
from pygraphrt.script_module_rt import ScriptModuleRT
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


def observe(model):
    data, inlets, resets = [], [], []
    model.nodeDataChanged.connect(data.append)
    model.inletsChanged.connect(inlets.append)
    model.modelReset.connect(lambda: resets.append(True))
    return data, inlets, resets


def test_operator_changes_notify_only_matching_nodes(qapp):
    module = ScriptModuleRT("tools", "def value(a): return a")
    other_module = ScriptModuleRT("other", "def value(a): return a")
    graph = GraphRT()
    first = graph.node()(OperatorRef(module, "value"))
    second = graph.node()(OperatorRef(module, "value"))
    graph.node()(OperatorRef(other_module, "value"))
    model = PyFlowRTModel(graph)
    selection = GraphSelectionModel(model)
    selection.selectNode(first.get_name())
    data, inlets, resets = observe(model)
    names = [first.get_name(), second.get_name()]
    for script, expected, color in [
        ("def value(a, b): return a + b", ["a", "b"], Qt.GlobalColor.green),
        ("def value(:", [], Qt.GlobalColor.red),
        ("def value(c): return c", ["c"], Qt.GlobalColor.green),
    ]:
        data.clear()
        inlets.clear()
        module.set_script(script)
        assert data == [tuple(names)]
        assert inlets == names
        assert list(model.inlets(names[0])) == expected
        assert model.nodeData(names[0], Qt.ItemDataRole.BackgroundRole) == QColor(color)
        assert selection.selectedNodes() == (names[0],)
        assert resets == []
    data.clear()
    module.set_script("def value(c): return c\ndef unused(): return 0")
    assert data == []


def test_subscriptions_follow_node_add_remove_and_runtime_replacement(qapp):
    module = ScriptModuleRT("tools", "def value(): return 1")
    graph = GraphRT()
    model = PyFlowRTModel(graph)
    data, inlets, resets = observe(model)
    node = graph.node()(OperatorRef(module, "value"))
    module.set_script("def value(): return 2")
    assert data == [(node.get_name(),)]
    graph.remove_node(node)
    assert module not in model._observed_modules
    data.clear()
    module.set_script("def value(): return 3")
    assert data == []
    node = graph.node()(OperatorRef(module, "value"))
    model.reset()
    model.reset()
    data.clear()
    module.set_script("def value(): return 4")
    assert data == [(node.get_name(),)]
    replacement = GraphRT()
    model.setRT(replacement)
    data.clear()
    module.set_script("def value(): return 5")
    graph.node()(OperatorRef(module, "value"))
    assert data == []
    assert model._observed_modules == set()
    replacement.node()(OperatorRef(module, "value"))
    module.set_script("def value(): return 6")
    assert len(data) == 1


def test_view_repaints_for_operator_changes_and_disconnects_old_model(qtbot):
    class TrackingView(DirectionalGraphView5):
        def __init__(self):
            self.repaint_requests = 0
            super().__init__()

        def update(self, *args):
            self.repaint_requests += 1
            return super().update(*args)

    module = ScriptModuleRT("tools", "def value(a): return a")
    graph = GraphRT()
    graph.node()(OperatorRef(module, "value"))
    model = PyFlowRTModel(graph)
    view = TrackingView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.repaint_requests = 0
    module.set_script("def value(a, b): return a + b")
    assert view.repaint_requests > 0
    view.setModel(PyFlowRTModel(GraphRT()))
    view.repaint_requests = 0
    module.set_script("def value(a): return a")
    assert view.repaint_requests == 0
