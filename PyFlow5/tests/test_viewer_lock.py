import pytest

from pyflow5.pyflow5_document import PyFlowDocument
from pyflow5.pyflow5_window import PyFlow5Window
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.script_module import ScriptModuleRT
from qdageditor5.models.graph_selection_model import GraphSelectionModel


FLAGS = GraphSelectionModel.SelectionFlag


def add_value_nodes(document):
    module = ScriptModuleRT("values", "def value(number=1): return number")
    model = document.graphmodel()
    model.addNode(OperatorRef(module, "value"))
    model.addNode(OperatorRef(module, "value"))
    return [model.getNode(name) for name in model.nodes()]


def select(document, node):
    document.graphselectionmodel().selectNode(
        node.get_name(), FLAGS.ClearAndSelect | FLAGS.Current,
    )


@pytest.fixture
def document(qapp):
    document = PyFlowDocument()
    yield document
    document.set_output_node(None)


def test_lock_preserves_output_while_selection_and_inspector_change(document):
    first, second = add_value_nodes(document)
    select(document, first)
    document.set_output_locked(True)

    select(document, second)
    assert document.get_output_node() == first
    assert document.inspectormodel().node() == second.get_name()

    document.graphselectionmodel().clearSelection()
    assert document.get_output_node() == first
    assert document.inspectormodel().node() is None


def test_unlock_immediately_follows_current_selection(document):
    first, second = add_value_nodes(document)
    select(document, first)
    document.set_output_locked(True)
    select(document, second)
    document.set_output_locked(False)
    assert document.get_output_node() == second

    document.set_output_locked(True)
    document.graphselectionmodel().clearSelection()
    document.set_output_locked(False)
    assert document.get_output_node() is None


def test_current_node_change_within_same_selection_updates_unlocked_output(document):
    first, second = add_value_nodes(document)
    selection = document.graphselectionmodel()
    selection.selectNodes([first.get_name(), second.get_name()])
    selection.setCurrentNode(first.get_name())
    assert document.get_output_node() == first
    selection.setCurrentNode(second.get_name())
    assert document.get_output_node() == second


def test_locked_output_stays_live_after_unrelated_node_deletion(document):
    first, second = add_value_nodes(document)
    select(document, first)
    document.set_output_locked(True)
    select(document, second)
    document.graphmodel().removeNodes([second.get_name()])
    results = []
    document.output_value_got_dirty.connect(lambda: results.append(document.execute()))

    first.set_inputs(number=42)
    assert results == [42]
    assert document.get_output_node() == first
    assert document.is_output_locked()


def test_deleting_pinned_node_releases_lock_and_follows_selection(document):
    first, second = add_value_nodes(document)
    select(document, first)
    document.set_output_locked(True)
    select(document, second)
    document.graphmodel().removeNodes([first.get_name()])
    assert not document.is_output_locked()
    assert document.get_output_node() == second


def test_reset_clears_output_and_lock(document):
    first, second = add_value_nodes(document)
    select(document, first)
    document.set_output_locked(True)
    document.reset_graph()
    assert document.get_output_node() is None
    assert not document.is_output_locked()


def test_viewer_switch_and_document_state_stay_synchronized(qtbot):
    window = PyFlow5Window()
    qtbot.addWidget(window)
    document = window._document
    first, second = add_value_nodes(document)
    select(document, first)

    window._viewer_lock_switch.click()
    assert document.is_output_locked()
    select(document, second)
    assert document.get_output_node() == first

    window._viewer_lock_switch.click()
    assert not document.is_output_locked()
    assert document.get_output_node() == second

    document.set_output_locked(True)
    assert window._viewer_lock_switch.isChecked()
    document.graphmodel().removeNodes([second.get_name()])
    assert not window._viewer_lock_switch.isChecked()
    assert document.get_output_node() is None
