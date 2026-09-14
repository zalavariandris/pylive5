from qtpy.QtCore import (
    Qt,
    QModelIndex,
)
from qtpy.QtGui import QTextOption
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QMessageBox,
    QPlainTextEdit,
)

from QScriptEdit2.pygments_highlighter import PygmentsHighlighter
from pygments.styles import get_all_styles

class ScriptEdit2(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        # self.setFontFamily("Courier New")
        # self.setFontPointSize(10)
        self.highlighter = PygmentsHighlighter(self.document())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # self.setWordWrapMode(QTextEdit.WordWrapMode.NoWrap)

        self.setPlaceholderText("Write your script here...")

if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication

    app = QApplication([])
    editor = ScriptEdit2()
    from textwrap import dedent
    editor.setPlainText(dedent("""\
        import pathlib
        p = pathlib.Path('path/to/file')
        print(p)
        """
    ))
    editor.show()
    app.exec()