from pathlib import Path
from typing import Tuple

import pygraphrt as rt
import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDoubleSpinBox, QLineEdit, QSpinBox, QStyleOptionViewItem

from myqtx import EditorContext, EditorRegistry
from myqtx.color_editor_widget import ColorEdit
from pyflow5.editors import NumericTupleEdit, numeric_tuple_editor
from pyflow5.views.formview import FormView
from pyflow5.core.nodert_input_roles import NodeRTInputRole
from pyflow5.views.node_input_delegate import NodeInputDelegate
from pyflow5.vfxops_editors import register_vfxops_editors, vfxops_editor_provider


@pytest.fixture
def make_provider_form(qtbot, make_input_model):
    def make(module: rt.ScriptModuleRT, editors: EditorRegistry):
        modules = rt.ModuleRegistry()
        modules.add_module(module)
        graph = rt.GraphDefinitionRT()
        node = graph._create_node(module.get_operator_by_name("operation"))
        model = make_input_model(graph, modules)
        form = FormView()
        qtbot.addWidget(form)
        form.setItemDelegate(NodeInputDelegate(form, editor_registry=editors))
        form.setModel(model)
        form.setRootIndex(model.index(0, 0))
        return node, model, form
    return make


@pytest.mark.parametrize("components, default, expected", [
    ("float, float", "(1, 2)", (0.25, 2.0)),
    ("float, float, float", "(1, 2, 3)", (0.25, 2.0, 3.0)),
    ("int, int", "(640, 480)", (42, 480)),
    ("int, int, int, int", "(1, 2, 640, 480)", (42, 2, 640, 480)),
    ("float, float, float, float", "(1, 0.5, 0, 1)", (0.25, 0.5, 0.0, 1.0)),
])
def test_vfxops_aliases_edit_clear_and_preserve_defaults(
    make_provider_form, tmp_path: Path, components: str, default: str, expected: tuple,
) -> None:
    path = tmp_path / "vfxops.py"
    path.write_text(
        f"from typing import Tuple\nAlias = Tuple[{components}]\n"
        f"def operation(value: Alias = {default}): return value\n",
        encoding="utf-8",
    )
    module = rt.ImportModuleRT("arbitrary display name", path)
    editors = EditorRegistry()
    register_vfxops_editors(editors, path)
    node, model, form = make_provider_form(module, editors)
    wrapper = form._mapper.mappedWidgetAt(0)
    index = model.index(0, 1, model.index(0, 0))
    context = index.data(NodeRTInputRole.EditorContextRole)
    assert context.source_path == path.resolve()
    assert context.module_name == "arbitrary display name"
    assert context.operator_name == "operation"
    assert context.parameter_name == "value"
    assert context.annotation is index.data(NodeRTInputRole.AnnotationRole)
    assert wrapper.editor.property("usingDefault") is True
    form._mapper.submit()
    assert node.get_inputs() == ((), {})

    if isinstance(wrapper.editor, ColorEdit):
        wrapper.editor.setColor(*expected)
    else:
        assert isinstance(wrapper.editor, NumericTupleEdit)
        spin_type = QSpinBox if components.startswith("int") else QDoubleSpinBox
        wrapper.editor.findChildren(spin_type)[0].setValue(expected[0])
    value = node.get_inputs()[1]["value"]
    assert value == expected
    assert type(value) is tuple
    assert all(type(item) is type(target) for item, target in zip(value, expected))
    assert wrapper.editor.property("usingDefault") is False
    wrapper.clear_button.click()
    form._mapper.submit()
    assert node.get_inputs() == ((), {})
    assert wrapper.editor.property("usingDefault") is True


def test_same_named_files_can_choose_different_editors(make_provider_form, tmp_path: Path) -> None:
    source = "from typing import Tuple\ndef operation(value: Tuple[float, float, float, float]): return value"
    color_path = tmp_path / "vfxops.py"
    geometry_path = tmp_path / "geometry" / "vfxops.py"
    geometry_path.parent.mkdir()
    color_path.write_text(source, encoding="utf-8")
    geometry_path.write_text(source, encoding="utf-8")
    editors = EditorRegistry()
    register_vfxops_editors(editors, color_path)
    _, _, colors = make_provider_form(rt.ImportModuleRT("vfxops.py", color_path), editors)
    _, _, geometry = make_provider_form(rt.ImportModuleRT("vfxops.py", geometry_path), editors)
    assert isinstance(colors._mapper.mappedWidgetAt(0).editor, ColorEdit)
    wrapper = geometry._mapper.mappedWidgetAt(0)
    assert isinstance(wrapper.editor, QLineEdit) and wrapper.editor.isReadOnly()

    editors.register_provider(geometry_path, lambda context: numeric_tuple_editor)
    geometry._mapper.revert()
    assert isinstance(wrapper.editor, NumericTupleEdit)
    assert len(wrapper.editor.findChildren(QDoubleSpinBox)) == 4
    assert isinstance(colors._mapper.mappedWidgetAt(0).editor, ColorEdit)


def test_required_tuple_and_tree_delegate_keep_values_unset_until_edited(
    make_provider_form, qtbot,
) -> None:
    module = rt.ScriptModuleRT("vfxops.vfxops")
    module.set_script("def operation(value: tuple[int, int]): return value")
    editors = EditorRegistry()
    register_vfxops_editors(editors)
    node, model, form = make_provider_form(module, editors)
    index = model.index(0, 1, model.index(0, 0))
    assert index.flags() & Qt.ItemFlag.ItemIsEditable
    assert index.data(Qt.ItemDataRole.EditRole) is None
    delegate = NodeInputDelegate(editor_registry=editors)
    tree_editor = delegate.createEditor(None, QStyleOptionViewItem(), index)
    qtbot.addWidget(tree_editor)
    delegate.setEditorData(tree_editor, index)
    delegate.setModelData(tree_editor, model, index)
    form._mapper.submit()
    assert node.get_inputs() == ((), {})
    tree_editor.editor.findChildren(QSpinBox)[0].setValue(800)
    delegate.setModelData(tree_editor, model, index)
    assert node.get_inputs() == ((), {"value": (800, 0)})
    assert not model.setData(index, (1,))
    assert not model.setData(index, ("bad", 2))
    assert node.get_inputs() == ((), {"value": (800, 0)})
    form._mapper.mappedWidgetAt(0).clear_button.click()
    form._mapper.submit()
    assert node.get_inputs() == ((), {})


def test_context_for_function_operators_and_connected_inputs(make_input_model, qtbot) -> None:
    graph = rt.GraphDefinitionRT()
    source = graph._create_node()

    @graph.node(value=source)
    def operation(value: Tuple[float, float]) -> object:
        return value

    model = make_input_model(graph)
    index = model.index(0, 1, model.mapFromSource(graph.nodes()[1].get_name()))
    context = index.data(NodeRTInputRole.EditorContextRole)
    assert context.module_name == __name__
    assert context.source_path == Path(__file__).resolve()
    assert context.parameter_name == "value"
    calls: list[EditorContext] = []
    editors = EditorRegistry()
    editors.register_provider(__name__, lambda context: calls.append(context))
    delegate = NodeInputDelegate(editor_registry=editors)
    editor = delegate.createEditor(None, QStyleOptionViewItem(), index)
    qtbot.addWidget(editor)
    assert calls == []
    assert not index.flags() & Qt.ItemFlag.ItemIsEditable


def test_live_tuple_annotation_changes_refresh_component_count(make_provider_form) -> None:
    module = rt.ScriptModuleRT("vfxops.vfxops")
    module.set_script("def operation(value: tuple[float, float] = (1, 2)): return value")
    editors = EditorRegistry()
    register_vfxops_editors(editors)
    node, _, form = make_provider_form(module, editors)
    form._mapper.mappedWidgetAt(0).editor.findChildren(QDoubleSpinBox)[0].setValue(5.0)
    module.set_script("def operation(value: tuple[float, float, float] = (1, 2, 3)): return value")
    wrapper = form._mapper.mappedWidgetAt(0)
    assert len(wrapper.editor.findChildren(QDoubleSpinBox)) == 3
    assert wrapper.binding.get_value() == (5.0, 2.0, 0.0)
    form._mapper.submit()
    assert node.get_inputs() == ((), {"value": (5.0, 2.0)})
    wrapper.editor.findChildren(QDoubleSpinBox)[2].setValue(3.0)
    assert node.get_inputs() == ((), {"value": (5.0, 2.0, 3.0)})


def test_window_registers_the_workspace_vfxops_file(qtbot) -> None:
    from pyflow5.views.pyflow5_window import PyFlow5Window

    window = PyFlow5Window()
    qtbot.addWidget(window)
    path = Path(__file__).resolve().parents[2] / "vfxops/src/vfxops/vfxops.py"
    module = window._document.importModule(path)
    assert module is not None and module.get_status() == "VALID"
    operator = module.get_operator_by_name("constant")
    assert operator is not None
    parameter = operator.get_parameters()["color"]
    context = EditorContext(
        operator.get_module_name(), operator.get_name(), parameter.name,
        parameter.annotation, operator.get_source_path(),
    )
    assert window.editor_registry.factory_for(parameter.annotation, context=context) is vfxops_editor_provider(context)
