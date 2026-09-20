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
    QLabel,
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

        self._message_line = QLabel(self)
        # make sure, the message line is always at the bottom. we cant use a layout because QPlainTextEdit does not support child widgets properly. so we just position it manually.
        self._message_line.setStyleSheet("background-color: white;")
        self._message_line.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # style the message line to have dark background and red text for errors
        # with padding and rounded corners
        self._message_line.setStyleSheet("""
        background-color: rgb(40, 40, 40); 
        color: darkred;
        border-radius: 4px;
        """)
        self.clearError()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._message_line.setGeometry(0, self.height() - 20, self.width(), 20)


    def showError(self, error: BaseException):
        # set border to red, but only for the widget itselfe, not the child widgets
        self.setStyleSheet("QPlainTextEdit{border: 2px solid red;}")
        self._message_line.setText(str(error))
        self._message_line.show()

    def clearError(self):
        self.setStyleSheet("")
        self._message_line.setText("")
        self._message_line.hide()

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