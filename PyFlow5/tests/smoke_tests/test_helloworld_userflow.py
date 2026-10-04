"""Exercise the real application widgets with mouse and keyboard events."""

from textwrap import dedent
from typing import Literal

from pyflow5.pygraphrt_dag_model import PyFlowRTModel
from pyflow5.viewer_view import Viewer
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QMimeData, QModelIndex, Qt, QTimer
from qtpy.QtWidgets import QApplication, QDialogButtonBox

from pyflow5.modules_operator_tree_model import ModulesOperatorsTreeModel
from pyflow5.pyflow5_window import PyFlow5Window
from pyflow5.pyflow5_document import PyFlowDocument


import pygraphrt as rt
from pygraphrt.graph_executor import (
    ExecutionFailure, 
    ExecutionSuccess, 
    NodeExecution
)

global WAIT_TIME_MS
WAIT_TIME_MS = 1000


def test_create_node_from_local_script(qtbot: QtBot, tmp_path) -> None:
    # - Open Appplication Window with new document
    print("opening window")
    window = PyFlow5Window()
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    print("window opened")
    qtbot.wait(WAIT_TIME_MS)

    document: PyFlowDocument = window._document
    assert list(document.graph_model.nodes()) == []
    assert not window._node_tree_view.isVisible()

    # - no module is selected now. check if the details view shows "<No Selection>", and disabled.
    assert window._module_details_view.currentIndex() == QModelIndex()
    code_editor = window._module_details_view._code_editor
    assert not window._module_details_view._code_editor.isEnabled()

    # - Create a new embedded module
    document.addEmbeddedModule("_local_")
    
    # - Click the local module in the modules view to select it
    modules_listview = window._modules_listview
    local_module_index = document.modules_model.index(0, 0)
    qtbot.mouseClick(
        modules_listview.viewport(),
        Qt.MouseButton.LeftButton,
        pos=modules_listview.visualRect(local_module_index).center(),
    )
    qtbot.wait(WAIT_TIME_MS)
    assert document.modulesselection_model.currentIndex() == local_module_index
    assert document.modulesselection_model.isSelected(local_module_index)
    assert window._module_details_view.currentIndex() == local_module_index

    
    # - Edit the currently selected module through the code editor.
    # todo: do this with mouse and keyboard inputs

    module_details_view = window._module_details_view
    qtbot.waitUntil(module_details_view._code_editor.isEnabled)
    qtbot.mouseClick(module_details_view._code_editor.viewport(), Qt.MouseButton.LeftButton)
    script = dedent("""\
        def helloworld() -> str:
            return "hello from userflow"
    """)

    def set_code_editor_text(text, mode:Literal['direct', 'paste']='direct'):
        code_editor = window._module_details_view._code_editor
        match mode:
            case 'direct':
                code_editor.setPlainText(text)

            case 'paste':
                clipboard = QApplication.clipboard()
                saved_clipboard = QMimeData()
                previous_data = clipboard.mimeData()
                if previous_data is not None:
                    for mime_type in previous_data.formats():
                        saved_clipboard.setData(mime_type, previous_data.data(mime_type))
                try:
                    clipboard.setText(text)
                    qtbot.mouseClick(code_editor.viewport(), Qt.MouseButton.LeftButton)
                    qtbot.keyClick(code_editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                    qtbot.keyClick(code_editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
                finally:
                    clipboard.setMimeData(saved_clipboard)


    set_code_editor_text(script)
    assert local_module_index.data(ModulesOperatorsTreeModel.SourceRole) == script
    qtbot.wait(WAIT_TIME_MS)

    # - open OperatorSelector dialog with a doublclick on the graphview
    graph_view = window._graph_view
    
    # - Add helloworld through the operator picker.
    def add_node_using_the_operator_picker(operator_name) -> None:
        def find_operator_index(operator_name:str, module_idx:QModelIndex) -> QModelIndex:
            for row in range(document.modules_model.rowCount(module_idx)):
                operator_index = document.modules_model.index(row, 0, module_idx)
                if operator_index.data() == operator_name:
                    return operator_index
            return QModelIndex()

        local_module_index = document.modules_model.index(0, 0)
        operator_index = find_operator_index(operator_name, local_module_index)
        assert operator_index.isValid(), f"Operator '{operator_name}' not found in local module"

        # QDialog.exec() blocks, so queue the dialog clicks on a timer.
        dialog_driver = QTimer(window)
        dialog_driver.setSingleShot(True)
        @dialog_driver.timeout.connect
        def _():
            QApplication.activeModalWidget()._operator_tree.scrollTo(operator_index)
            qtbot.mouseClick(
                (tree := QApplication.activeModalWidget()._operator_tree).viewport(),
                Qt.MouseButton.LeftButton,
                pos=tree.visualRect(operator_index).center(),
            )
            qtbot.waitUntil(
                lambda: QApplication.activeModalWidget().selected_index() == operator_index
            )
            qtbot.mouseClick(
                QApplication.activeModalWidget()._buttons.button(QDialogButtonBox.StandardButton.Ok),
                Qt.MouseButton.LeftButton,
            )
        
        # Close the modal loop if a queued interaction fails, so pytest can finish.
        dialog_timeout = QTimer(window)
        dialog_timeout.setSingleShot(True)
        @dialog_timeout.timeout.connect
        def _():
            QApplication.activeModalWidget().reject()

        dialog_driver.start(WAIT_TIME_MS)
        dialog_timeout.start(5000)
        try:
            qtbot.mouseDClick(graph_view, Qt.MouseButton.LeftButton)
        finally:
            dialog_driver.stop()
            dialog_timeout.stop()

    add_node_using_the_operator_picker("helloworld")
    qtbot.wait(WAIT_TIME_MS)

    assert list(document.graph_model.nodes()) == ["helloworld"]

    # - Select helloworld as the output node.
    graph_view = window._graph_view
    scene_pos = document.graph_model.nodePosition("helloworld")
    view_pos = graph_view.mapFromScene(scene_pos).toPoint()
    assert graph_view.contentsRect().contains(view_pos), "Node must be visible to click it"
    qtbot.mouseClick(graph_view, Qt.MouseButton.LeftButton, pos=view_pos)
    qtbot.waitUntil(lambda: document.graphselection_model.selectedNodes() == ("helloworld",))
    qtbot.wait(WAIT_TIME_MS)
    assert window._node_tree_view.isVisible()
    
    # Check the displayed result and the document output.
    viewer:Viewer = window._viewer
    assert viewer.currentNodeName() is "helloworld", f"The current node should be 'helloworld' got:{viewer.currentNodeName()}"
    assert viewer._display_widget._label.text() == "hello from userflow"
    qtbot.wait(WAIT_TIME_MS)
    # return
    # qtbot.waitUntil(lambda: viewer._display_widget._label.text() == "hello from userflow")
    # assert label.isVisible()

    # Extend the script with name and greeting inputs, keeping the existing node.
    set_code_editor_text(dedent("""\
        def the_name() -> str:
            return "Mása"

        def the_greeting() -> str:
            return "Hey"

        def helloworld(name: str, greeting: str = "Hello") -> str:
            return f"{greeting} {name}!"
        """))
    
    qtbot.wait(WAIT_TIME_MS)
    current_excecution_data = document.graph_model.nodeData("helloworld", role=PyFlowRTModel.ExecutionRole)
    assert isinstance(current_excecution_data, Exception), f"Expected an Exception, got: {current_excecution_data}"
    qtbot.wait(WAIT_TIME_MS)

    # Add 'the_name' and the 'the_greeting' NODE through the operator picker.
    add_node_using_the_operator_picker("the_name")
    qtbot.wait(WAIT_TIME_MS)
    add_node_using_the_operator_picker("the_greeting")
    qtbot.wait(WAIT_TIME_MS)

    # Arrange the nodes so their ports are visible.
    graph_view = window._graph_view
    graph_view.layout_nodes()
    graph_view.centerNodes()
    qtbot.wait(WAIT_TIME_MS)

    # Connect the name input and check the default greeting.
    model = document.graph_model
    assert "out" in model.outlets("the_name")
    assert "name" in model.inlets("helloworld")
    start = graph_view.mapFromScene(graph_view._outletPos("the_name", "out")).toPoint()
    end = graph_view.mapFromScene(graph_view._inletPos("helloworld", "name")).toPoint()
    assert graph_view.contentsRect().contains(start), "Source outlet must be visible"
    assert graph_view.contentsRect().contains(end), "Target inlet must be visible"

    # Drag between the actual ports so the view creates the link.
    qtbot.mousePress(graph_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(graph_view, pos=end)
    qtbot.wait(WAIT_TIME_MS)
    qtbot.mouseRelease(graph_view, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: ("the_name", "out", "helloworld", "name") in model.links())
    qtbot.wait(WAIT_TIME_MS)

    # Check the displayed result and the document output.
    viewer = window._viewer
    label = viewer._display_widget._label
    qtbot.waitUntil(lambda: label.text() == "Hello Mása!")
    assert label.isVisible()
    qtbot.wait(WAIT_TIME_MS)

    # Connect the greeting input and check that it replaces the default.
    assert "out" in model.outlets("the_greeting")
    assert "greeting" in model.inlets("helloworld")
    start = graph_view.mapFromScene(graph_view._outletPos("the_greeting", "out")).toPoint()
    end = graph_view.mapFromScene(graph_view._inletPos("helloworld", "greeting")).toPoint()
    assert graph_view.contentsRect().contains(start), "Source outlet must be visible"
    assert graph_view.contentsRect().contains(end), "Target inlet must be visible"

    # Drag between the actual ports so the view creates the link.
    qtbot.mousePress(graph_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(graph_view, pos=end)
    qtbot.wait(WAIT_TIME_MS)
    qtbot.mouseRelease(graph_view, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: ("the_greeting", "out", "helloworld", "greeting") in model.links())
    qtbot.wait(WAIT_TIME_MS)

    # Check the displayed result and the document output.
    viewer = window._viewer
    label = viewer._display_widget._label
    qtbot.waitUntil(lambda: label.text() == "Hey Mása!")
    assert label.isVisible()

    qtbot.wait(WAIT_TIME_MS)
    assert set(document.graph_model.links()) == {
        ("the_name", "out", "helloworld", "name"),
        ("the_greeting", "out", "helloworld", "greeting"),
    }

    # Arrange the nodes so their ports are visible.
    graph_view = window._graph_view
    graph_view.layout_nodes()
    graph_view.centerNodes()
    qtbot.wait(WAIT_TIME_MS)
    qtbot.wait(3000)

    # save to  a file
    # save to  a file
    output_file = tmp_path / "test_helloworld_userflow_output.json"
    document.save(str(output_file))
    
if __name__ == "__main__":
    import pytest
    WAIT_TIME_MS = 1000
    pytest.main([__file__])
