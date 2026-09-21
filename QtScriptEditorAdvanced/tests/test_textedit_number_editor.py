import pytest
from qtpy.QtCore import QCoreApplication, QEvent
from qtpy.QtWidgets import QPlainTextEdit, QTextEdit

from QtScriptEditorAdvanced.components.textedit_number_editor import TextEditNumberEditor
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced


@pytest.mark.parametrize("editor_type", [QPlainTextEdit, QTextEdit, ScriptEditAdvanced])
@pytest.mark.parametrize("read_only", [False, True])
def test_editor_deletion_does_not_raise_in_viewport_filter(qtbot, editor_type, read_only):
    if editor_type is ScriptEditAdvanced:
        editor = editor_type(completer=None)
        number_editor = editor.number_editor
    else:
        editor = editor_type()
        number_editor = TextEditNumberEditor(editor)
    editor.setPlainText("value = 100")
    editor.setReadOnly(read_only)
    destroyed = []
    number_editor.destroyed.connect(lambda: destroyed.append(True))

    # The viewport receives teardown events after its editor is invalidated.
    with qtbot.captureExceptions() as exceptions:
        editor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert destroyed == [True]
    assert exceptions == []
