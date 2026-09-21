from dataclasses import dataclass

import pytest
from qtpy.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from qtpy.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from myqtx import InspectorEditor, InspectorRole, InspectorView, UNSET
from pyflow5.node_inspector_model import NodeInspectorModel
from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import GraphRT
from pygraphrt.script_module_rt import ScriptModuleRT


def field(model, name, role):
    for row in range(model.rowCount()):
        index = model.index(row)
        if index.data() == name:
            return index.data(role)
    raise AssertionError(f"Missing field: {name}")


def test_binding_states_and_defaults_are_distinct_without_execution(qapp):
    graph = GraphRT()

    @graph.node()
    def source():
        raise AssertionError("Inspection must not execute a node")

    @graph.node(explicit=None, connected=source)
    def target(required, width: int = 512, explicit="default", connected=None):
        raise AssertionError("Inspection must not execute a node")

    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    assert inspector.rowCount() == 4
    assert inspector.rowCount(inspector.index(0)) == 0
    assert field(inspector, "required", InspectorRole.BindingRole) == "missing"
    assert field(inspector, "required", Qt.EditRole) is UNSET
    assert field(inspector, "width", InspectorRole.BindingRole) == "default"
    assert field(inspector, "width", Qt.EditRole) == 512
    assert field(inspector, "width", InspectorRole.TypeRole) is int
    assert field(inspector, "explicit", InspectorRole.BindingRole) == "literal"
    assert field(inspector, "explicit", Qt.EditRole) is None
    assert field(inspector, "explicit", InspectorRole.DefaultRole) == "default"
    assert field(inspector, "connected", InspectorRole.ConnectionRole) == ("source", "out")
    assert field(inspector, "connected", Qt.EditRole) is UNSET
    assert not inspector.flags(inspector.index(0)) & Qt.ItemFlag.ItemIsEditable
    assert not inspector.setData(inspector.index(0), 123)


def test_complex_value_occupies_one_row(qapp):
    graph = GraphRT()

    @graph.node()
    def target(vector: tuple = (1, 2, 3)):
        return vector

    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    assert inspector.rowCount() == 1
    assert inspector.index(0).data(Qt.EditRole) == (1, 2, 3)


def test_value_changes_preserve_editor_widgets(qtbot):
    graph = GraphRT()

    @graph.node(value=2)
    def target(value: int):
        return value

    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    view = InspectorView()
    qtbot.addWidget(view)
    view.setModel(inspector)
    editor = view.findChild(QLineEdit)
    resets = []
    inspector.modelReset.connect(lambda: resets.append(True))

    target.set_inputs(value=7)
    assert view.findChild(QLineEdit) is editor
    assert editor.text() == "7"
    assert not editor.isReadOnly()
    assert resets == []


def test_signature_changes_and_unavailable_operators_retain_bindings(qapp):
    module = ScriptModuleRT("tools", "def op(a: int = 1): return a")
    graph = GraphRT()
    node = graph.node(a=3)(OperatorRef(module, "op"), name="target")
    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")

    module.set_script("def op(b: str = 'hello'): return b")
    assert inspector.rowCount() == 2
    assert field(inspector, "b", Qt.EditRole) == "hello"
    assert field(inspector, "a", Qt.EditRole) == 3
    assert field(inspector, "a", InspectorRole.ErrorRole) == "No matching parameter."

    module.set_script("def op(:")
    assert inspector.rowCount() == 1
    assert field(inspector, "a", Qt.EditRole) == 3
    assert "unavailable" in inspector.headerData(0, Qt.Horizontal, Qt.ToolTipRole)

    module.set_script("def op(a: int = 1): return a")
    assert inspector.rowCount() == 1
    assert field(inspector, "a", InspectorRole.ErrorRole) == ""


def test_extra_and_duplicate_bindings_remain_visible(qapp):
    graph = GraphRT()

    @graph.node(1, 2, 3, a=4, orphan=None)
    def target(a, b=5):
        return a

    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    assert inspector.rowCount() == 5
    assert field(inspector, "a", Qt.EditRole) == 1
    assert field(inspector, "a (keyword)", Qt.EditRole) == 4
    assert field(inspector, "Argument 3", Qt.EditRole) == 3
    assert field(inspector, "orphan", Qt.EditRole) is None
    assert len({inspector.index(row).data(InspectorRole.KeyRole)
                for row in range(inspector.rowCount())}) == 5


def test_deletion_and_reset_clear_target(qapp):
    graph = GraphRT()

    @graph.node()
    def target(value=1):
        return value

    model = PyFlowRTModel(graph)
    inspector = NodeInspectorModel(model)
    inspector.setNode("target")
    model.reset()
    assert inspector.node() is None
    assert inspector.rowCount() == 0
    inspector.setNode("target")
    model.removeNodes(["target"])
    assert inspector.node() is None
    assert inspector.rowCount() == 0
    inspector.setNode("nonexistent")
    assert inspector.node() is None


class EditableModel(QAbstractListModel):
    def __init__(self, value, annotation):
        super().__init__()
        self.value = value
        self.annotation = annotation
        self.commits = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 1

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return "Value"
        if role == Qt.EditRole:
            return self.value
        if role == InspectorRole.TypeRole:
            return self.annotation
        if role == InspectorRole.BindingRole:
            return "literal"
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        self.commits.append(value)
        self.value = value
        self.dataChanged.emit(index, index, [role])
        return True


@dataclass
class Vector:
    x: int
    y: int


class VectorEditor(QWidget):
    committed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.x, self.y = QLineEdit(self), QLineEdit(self)
        layout.addWidget(self.x)
        layout.addWidget(self.y)
        # These intentionally fire while write() updates child widgets.
        self.x.textChanged.connect(self.committed.emit)
        self.y.textChanged.connect(self.committed.emit)

    def read(self):
        return Vector(int(self.x.text()), int(self.y.text()))

    def write(self, value):
        self.x.setText(str(value.x))
        self.y.setText(str(value.y))


def test_custom_complex_editor_commits_one_value_without_feedback(qtbot):
    model = EditableModel(Vector(1, 2), Vector)
    view = InspectorView()
    qtbot.addWidget(view)

    def factory(index, parent):
        widget = VectorEditor(parent)
        return InspectorEditor(widget, widget.read, widget.write, widget.committed)

    view.registerEditor(Vector, factory)
    view.setModel(model)
    editor = view.findChild(VectorEditor)
    assert editor is not None
    assert model.commits == []
    editor.x.setText("9")
    assert model.value == Vector(9, 2)
    assert model.commits == [Vector(9, 2)]


def test_invalid_numeric_input_does_not_commit(qtbot):
    model = EditableModel(1, int)
    view = InspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    editor = view.findChild(QLineEdit)
    editor.setText("invalid")
    editor.editingFinished.emit()
    assert model.value == 1
    assert model.commits == []
    assert view._rows[0].message.text()

    editor.setText("42")
    editor.editingFinished.emit()
    assert model.value == 42
    assert model.commits == [42]


def test_model_replacement_disconnects_old_model_and_stale_editor(qtbot):
    old_model, model = EditableModel(1, int), EditableModel(2, int)
    view = InspectorView()
    qtbot.addWidget(view)
    view.setModel(old_model)
    old_editor = view.findChild(QLineEdit)
    view.setModel(model)
    editor = view._rows[0].editor.widget
    old_editor.editingFinished.emit()
    old_model.setData(old_model.index(0), 99)
    assert editor.text() == "2"
    assert model.commits == []
    view.setModel(None)
    assert view.model() is None
    assert view._rows == []


def test_document_and_window_follow_current_node(qtbot):
    from pyflow5.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    document = window._document
    operator = next(iter(document._imagi_module.operators()))
    document.graphmodel().addNode(operator)
    name = document.graphmodel().nodes()[0]
    document.graphselectionmodel().selectNode(name)
    assert document.inspectormodel().node() == name
    assert window._inspector_view.model() is document.inspectormodel()
    assert document.inspectormodel().rowCount() > 0
    document.graphselectionmodel().clearSelection()
    assert document.inspectormodel().node() is None


def test_none_and_mismatched_annotations_display_actual_values(qtbot):
    graph = GraphRT()

    @graph.node(enabled=None, count="hello")
    def target(enabled: bool = False, count: int = 1):
        return enabled

    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    view = InspectorView()
    qtbot.addWidget(view)
    view.setModel(inspector)
    assert view._rows[0].editor.widget.text() == "None"
    assert view._rows[1].editor.widget.text() == "hello"


def test_replaced_editor_cannot_commit_through_new_binding(qtbot):
    model = EditableModel(1, int)
    view = InspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    old_editor = view._rows[0].editor.widget
    model.annotation = str
    model.value = "hello"
    model.dataChanged.emit(model.index(0), model.index(0), [])
    assert view._rows[0].editor.widget is not old_editor
    old_editor.editingFinished.emit()
    assert model.commits == []


def test_model_destruction_clears_view(qtbot):
    model = EditableModel(1, int)
    view = InspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    model.deleteLater()
    qtbot.waitUntil(lambda: view.model() is None)
    assert view._rows == []


@pytest.mark.parametrize("binding", ["default", "positional", "keyword"])
def test_color_input_edit_preserves_other_bindings(qapp, binding):
    from pyflow5.pyflow5_document import PyFlowDocument

    document = PyFlowDocument()
    ColorData = OperatorRef(document._imagi_module, "constant").get_parameters()["color"].annotation

    graph = GraphRT()
    original = ColorData(0.1, 0.2, 0.3, 0.4)

    def target(color: ColorData = original, count: int = 3):
        return color

    args = (original,) if binding == "positional" else ()
    kwargs = {"color": original} if binding == "keyword" else {}
    node = graph.node(*args, count=7, **kwargs)(target)
    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    updated = ColorData(0.8, 0.7, 0.6, 0.5)
    assert inspector.setData(inspector.index(0), updated)
    args, kwargs = node.get_inputs()
    assert kwargs["count"] == 7
    assert (args[0] if binding == "positional" else kwargs["color"]) == updated
    assert inspector.index(0).data(Qt.EditRole) == updated
    assert original == ColorData(0.1, 0.2, 0.3, 0.4)


def test_connected_color_cannot_be_overwritten(qapp):
    from pyflow5.pyflow5_document import PyFlowDocument

    document = PyFlowDocument()
    ColorData = OperatorRef(document._imagi_module, "constant").get_parameters()["color"].annotation

    graph = GraphRT()

    @graph.node()
    def source():
        return ColorData()

    @graph.node(color=source)
    def target(color: ColorData):
        return color

    inspector = NodeInspectorModel(PyFlowRTModel(graph))
    inspector.setNode("target")
    assert not inspector.flags(inspector.index(0)) & Qt.ItemFlag.ItemIsEditable
    assert not inspector.setData(inspector.index(0), ColorData(1, 0, 0))
    assert target.get_inputs()[1]["color"] == source


def test_app_color_editor_updates_graph(qtbot):
    from dataclasses import FrozenInstanceError
    from myqtx.color_editor_widget import ColorEdit
    from pyflow5.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    document = window._document
    ColorData = OperatorRef(document._imagi_module, "constant").get_parameters()["color"].annotation
    assert ColorData.__module__ == "imagi"
    original = ColorData(0.5, 0.5, 0.5)
    with pytest.raises(FrozenInstanceError):
        original.r = 1.0
    document.graphmodel().addNode(OperatorRef(document._imagi_module, "constant"))
    name = document.graphmodel().nodes()[0]
    document.graphselectionmodel().selectNode(name)
    node = document.graphmodel().getNode(name)
    editor = window._inspector_view.findChild(ColorEdit)
    assert editor is not None and editor.isEnabled()
    assert editor.color() == (0.5, 0.5, 0.5, 1.0)
    assert node.get_inputs() == ((), {})

    editor._showColorWheel()
    editor._color_wheel.setColor(0.8, 0.2, 0.1, 0.5)
    assert node.get_inputs()[1]["color"] == ColorData(0.8, 0.2, 0.1, 0.5)
    assert window._inspector_view.findChild(ColorEdit) is editor
    assert editor._color_wheel.isVisible()
    assert document._G.execute(node).data[0, 0].tolist() == pytest.approx([0.8, 0.2, 0.1, 0.5])
    editor._color_wheel.hide()


def test_inline_color_editor_registration_survives_script_reload(qtbot):
    from myqtx.color_editor_widget import ColorEdit
    from pyflow5.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    document = window._document
    module = document._imagi_module
    operator = OperatorRef(module, "constant")
    old_type = operator.get_parameters()["color"].annotation
    document.graphmodel().addNode(operator)
    name = document.graphmodel().nodes()[0]
    document.graphselectionmodel().selectNode(name)
    module.set_script(module.get_script().replace(
        "color: ColorData=ColorData(0.5, 0.5, 0.5)",
        "color: ColorData=ColorData(0.3, 0.4, 0.5)",
    ))
    new_type = operator.get_parameters()["color"].annotation
    assert new_type is not old_type
    editor = next(row.editor.widget for row in window._inspector_view._rows
                  if isinstance(row.editor.widget, ColorEdit))
    assert editor.color() == (0.3, 0.4, 0.5, 1.0)
    editor.setColor(0.9, 0.8, 0.7, 0.6)
    node = document.graphmodel().getNode(name)
    assert type(node.get_inputs()[1]["color"]) is new_type
    assert node.get_inputs()[1]["color"] == new_type(0.9, 0.8, 0.7, 0.6)
