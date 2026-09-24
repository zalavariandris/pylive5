"""Exercise the real application widgets with mouse and keyboard events."""

from textwrap import dedent

from pytestqt.qtbot import QtBot
from qtpy.QtCore import QMimeData, Qt, QTimer
from qtpy.QtWidgets import QApplication, QDialogButtonBox

from pyflow5.modules_operator_tree_model import ModulesOperatorsTreeModel
from pyflow5.pyflow5_window import PyFlow5Window
from pygraphrt.abstract_module_rt import OperatorRef


WAIT_TIME_MS = 500


def test_create_node_from_local_script(qtbot: QtBot) -> None:
    # Open the application and start with an empty graph.
    window = PyFlow5Window()
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.wait(1000)
    document = window._document
    assert list(document.graphmodel.nodes()) == []

    # Edit the local module through the code editor.
    script = 'def helloworld() -> str: return "hello from userflow"'
    modules_view = window._module_list_view
    local_index = document.modulesmodel.index(0, 0)
    assert local_index.isValid()

    qtbot.mouseClick(
        modules_view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=modules_view.visualRect(local_index).center(),
    )

    editor = window._module_details_view._code_editor
    qtbot.waitUntil(editor.isEnabled)
    qtbot.wait(WAIT_TIME_MS)
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton)
    qtbot.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    # Paste supports multiline and Unicode text, including accented names.
    clipboard = QApplication.clipboard()
    saved_clipboard = QMimeData()
    previous_data = clipboard.mimeData()
    if previous_data is not None:
        for mime_type in previous_data.formats():
            saved_clipboard.setData(mime_type, previous_data.data(mime_type))
    try:
        clipboard.setText(script)
        qtbot.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    finally:
        clipboard.setMimeData(saved_clipboard)
    assert editor.toPlainText() == script
    assert local_index.data(ModulesOperatorsTreeModel.SourceRole) == script
    qtbot.wait(WAIT_TIME_MS)

    # Add helloworld through the operator picker.
    operator_name = "helloworld"
    modules_model = document.modulesmodel
    local_index = modules_model.index(0, 0)
    for row in range(modules_model.rowCount(local_index)):
        operator_index = modules_model.index(row, 0, local_index)
        if operator_index.data() == operator_name:
            break
    else:
        raise AssertionError(f"Local operator {operator_name!r} is missing from the selector")

    operator = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
    assert isinstance(operator, OperatorRef)
    assert operator.module is document._G.local()

    # Ctrl+P blocks in QDialog.exec(), so queue the dialog clicks on a timer.
    dialog_driver = QTimer(window)
    dialog_driver.setSingleShot(True)
    dialog_driver.timeout.connect(
        lambda: QApplication.activeModalWidget()._operator_tree.scrollTo(operator_index)
    )
    dialog_driver.timeout.connect(
        lambda: qtbot.mouseClick(
            (tree := QApplication.activeModalWidget()._operator_tree).viewport(),
            Qt.MouseButton.LeftButton,
            pos=tree.visualRect(operator_index).center(),
        )
    )
    dialog_driver.timeout.connect(
        lambda: qtbot.waitUntil(
            lambda: QApplication.activeModalWidget().selected_index() == operator_index
        )
    )
    dialog_driver.timeout.connect(lambda: qtbot.wait(WAIT_TIME_MS))
    dialog_driver.timeout.connect(
        lambda: qtbot.mouseClick(
            QApplication.activeModalWidget()._buttons.button(QDialogButtonBox.StandardButton.Ok),
            Qt.MouseButton.LeftButton,
        )
    )
    # Close the modal loop if a queued interaction fails, so pytest can finish.
    dialog_timeout = QTimer(window)
    dialog_timeout.setSingleShot(True)
    dialog_timeout.timeout.connect(lambda: QApplication.activeModalWidget().reject())
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    editor.setFocus()
    dialog_driver.start(WAIT_TIME_MS)
    dialog_timeout.start(5000)
    try:
        qtbot.keyClick(editor, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
    finally:
        dialog_driver.stop()
        dialog_timeout.stop()

    qtbot.waitUntil(lambda: list(document.graphmodel.nodes()) == ["helloworld"])
    node = document.graphmodel.getNode("helloworld")
    assert node is not None
    assert document._G.execute(node) == "hello from userflow"

    # Select helloworld as the output node.
    graph_view = window._graph_view
    scene_pos = document.graphmodel.nodePosition("helloworld")
    view_pos = graph_view.mapFromScene(scene_pos).toPoint()
    assert graph_view.contentsRect().contains(view_pos), "Node must be visible to click it"
    qtbot.mouseClick(graph_view, Qt.MouseButton.LeftButton, pos=view_pos)
    qtbot.waitUntil(
        lambda: document.graphselectionmodel.selectedNodes() == ("helloworld",)
    )
    assert document.getOutputNode() == "helloworld"
    qtbot.wait(WAIT_TIME_MS)

    # Check the displayed result and the document output.
    label = window._display_widget.label
    qtbot.waitUntil(lambda: label.text() == "hello from userflow")
    assert label.isVisible()
    assert document.output_value() == "hello from userflow"
    qtbot.wait(WAIT_TIME_MS)

    # Extend the script with name and greeting inputs, keeping the existing node.
    script = dedent('''\
        def the_name() -> str:
            return "Mása"

        def the_greeting() -> str:
            return "Hey"

        def helloworld(name: str, greeting: str = "Hello") -> str:
            return f"{greeting} {name}!"
        ''')
    modules_view = window._module_list_view
    local_index = document.modulesmodel.index(0, 0)
    assert local_index.isValid()

    qtbot.mouseClick(
        modules_view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=modules_view.visualRect(local_index).center(),
    )

    editor = window._module_details_view._code_editor
    qtbot.waitUntil(editor.isEnabled)
    qtbot.wait(WAIT_TIME_MS)
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton)
    qtbot.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    # Paste supports multiline and Unicode text, including accented names.
    clipboard = QApplication.clipboard()
    saved_clipboard = QMimeData()
    previous_data = clipboard.mimeData()
    if previous_data is not None:
        for mime_type in previous_data.formats():
            saved_clipboard.setData(mime_type, previous_data.data(mime_type))
    try:
        clipboard.setText(script)
        qtbot.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    finally:
        clipboard.setMimeData(saved_clipboard)
    assert editor.toPlainText() == script
    assert local_index.data(ModulesOperatorsTreeModel.SourceRole) == script
    qtbot.wait(WAIT_TIME_MS)

    model = document.modulesmodel
    local_index = model.index(0, 0)
    operators: dict[str, OperatorRef] = {
        model.index(row, 0, local_index).data():
        model.index(row, 0, local_index).data(ModulesOperatorsTreeModel.OperatorRole)
        for row in range(model.rowCount(local_index))
    }
    assert set(operators) == {"the_name", "the_greeting", "helloworld"}
    assert operators["the_name"]() == "Mása"
    assert operators["the_greeting"]() == "Hey"
    assert operators["helloworld"]("Mása") == "Hello Mása!"
    assert operators["helloworld"]("Mása", "Hey") == "Hey Mása!"
    assert document.graphmodel.getNode("helloworld") == node

    # Add the_name through the operator picker.
    operator_name = "the_name"
    modules_model = document.modulesmodel
    local_index = modules_model.index(0, 0)
    for row in range(modules_model.rowCount(local_index)):
        operator_index = modules_model.index(row, 0, local_index)
        if operator_index.data() == operator_name:
            break
    else:
        raise AssertionError(f"Local operator {operator_name!r} is missing from the selector")

    operator = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
    assert isinstance(operator, OperatorRef)
    assert operator.module is document._G.local()

    # Ctrl+P blocks in QDialog.exec(), so queue the dialog clicks on a timer.
    dialog_driver = QTimer(window)
    dialog_driver.setSingleShot(True)
    dialog_driver.timeout.connect(
        lambda: QApplication.activeModalWidget()._operator_tree.scrollTo(operator_index)
    )
    dialog_driver.timeout.connect(
        lambda: qtbot.mouseClick(
            (tree := QApplication.activeModalWidget()._operator_tree).viewport(),
            Qt.MouseButton.LeftButton,
            pos=tree.visualRect(operator_index).center(),
        )
    )
    dialog_driver.timeout.connect(
        lambda: qtbot.waitUntil(
            lambda: QApplication.activeModalWidget().selected_index() == operator_index
        )
    )
    dialog_driver.timeout.connect(lambda: qtbot.wait(WAIT_TIME_MS))
    dialog_driver.timeout.connect(
        lambda: qtbot.mouseClick(
            QApplication.activeModalWidget()._buttons.button(QDialogButtonBox.StandardButton.Ok),
            Qt.MouseButton.LeftButton,
        )
    )
    # Close the modal loop if a queued interaction fails, so pytest can finish.
    dialog_timeout = QTimer(window)
    dialog_timeout.setSingleShot(True)
    dialog_timeout.timeout.connect(lambda: QApplication.activeModalWidget().reject())
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    editor.setFocus()
    dialog_driver.start(WAIT_TIME_MS)
    dialog_timeout.start(5000)
    try:
        qtbot.keyClick(editor, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
    finally:
        dialog_driver.stop()
        dialog_timeout.stop()

    # Add the_greeting through the operator picker.
    operator_name = "the_greeting"
    modules_model = document.modulesmodel
    local_index = modules_model.index(0, 0)
    for row in range(modules_model.rowCount(local_index)):
        operator_index = modules_model.index(row, 0, local_index)
        if operator_index.data() == operator_name:
            break
    else:
        raise AssertionError(f"Local operator {operator_name!r} is missing from the selector")

    operator = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
    assert isinstance(operator, OperatorRef)
    assert operator.module is document._G.local()

    # Ctrl+P blocks in QDialog.exec(), so queue the dialog clicks on a timer.
    dialog_driver = QTimer(window)
    dialog_driver.setSingleShot(True)
    dialog_driver.timeout.connect(
        lambda: QApplication.activeModalWidget()._operator_tree.scrollTo(operator_index)
    )
    dialog_driver.timeout.connect(
        lambda: qtbot.mouseClick(
            (tree := QApplication.activeModalWidget()._operator_tree).viewport(),
            Qt.MouseButton.LeftButton,
            pos=tree.visualRect(operator_index).center(),
        )
    )
    dialog_driver.timeout.connect(
        lambda: qtbot.waitUntil(
            lambda: QApplication.activeModalWidget().selected_index() == operator_index
        )
    )
    dialog_driver.timeout.connect(lambda: qtbot.wait(WAIT_TIME_MS))
    dialog_driver.timeout.connect(
        lambda: qtbot.mouseClick(
            QApplication.activeModalWidget()._buttons.button(QDialogButtonBox.StandardButton.Ok),
            Qt.MouseButton.LeftButton,
        )
    )
    # Close the modal loop if a queued interaction fails, so pytest can finish.
    dialog_timeout = QTimer(window)
    dialog_timeout.setSingleShot(True)
    dialog_timeout.timeout.connect(lambda: QApplication.activeModalWidget().reject())
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    editor.setFocus()
    dialog_driver.start(WAIT_TIME_MS)
    dialog_timeout.start(5000)
    try:
        qtbot.keyClick(editor, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
    finally:
        dialog_driver.stop()
        dialog_timeout.stop()

    assert set(document.graphmodel.nodes()) == {"helloworld", "the_name", "the_greeting"}

    # Arrange the nodes so their ports are visible.
    graph_view = window._graph_view
    graph_view.layout_nodes()
    graph_view.centerNodes()
    qtbot.wait(WAIT_TIME_MS)

    # Connect the name input and check the default greeting.
    model = document.graphmodel
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
    label = window._display_widget.label
    qtbot.waitUntil(lambda: label.text() == "Hello Mása!")
    assert label.isVisible()
    assert document.output_value() == "Hello Mása!"
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
    label = window._display_widget.label
    qtbot.waitUntil(lambda: label.text() == "Hey Mása!")
    assert label.isVisible()
    assert document.output_value() == "Hey Mása!"
    qtbot.wait(WAIT_TIME_MS)
    assert set(document.graphmodel.links()) == {
        ("the_name", "out", "helloworld", "name"),
        ("the_greeting", "out", "helloworld", "greeting"),
    }

    # Arrange the nodes so their ports are visible.
    graph_view = window._graph_view
    graph_view.layout_nodes()
    graph_view.centerNodes()
    qtbot.wait(WAIT_TIME_MS)
    qtbot.wait(3000)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
