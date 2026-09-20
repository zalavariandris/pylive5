import pytest
from pygraphrt.abstract_module_rt import OperatorRef
from pyflow5.pyflow5_window import PyFlow5Window


@pytest.mark.parametrize("upstream", [False, True])
def test_display_recovers_after_script_syntax_error(qtbot, upstream):
    window = PyFlow5Window()
    qtbot.addWidget(window)
    module = window._script_module
    module.set_script("def answer(): return 1")
    node = window._G.node()(OperatorRef(module, "answer"))
    if upstream:
        @window._G.node(value=node)
        def output(value):
            return value
        node = output
    window.set_output_node(node)
    watcher = window._watcher
    try:
        assert window._display_widget.label.text() == "1"
        for value in (2, 3):
            window._code_editor.setPlainText("def answer(:")
            assert window._display_widget.label.text().startswith("Exception:")
            assert watcher._running
            window._code_editor.setPlainText(f"def answer(): return {value}")
            assert window._display_widget.label.text() == str(value)
            assert window._watcher is watcher
        watcher.stop()
        window._code_editor.setPlainText("def answer(): return 4")
        assert window._display_widget.label.text() == "3"
    finally:
        window.set_output_node(None)
