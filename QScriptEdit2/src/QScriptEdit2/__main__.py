from qtpy.QtCore import (
    Qt,
    QModelIndex,
)
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QMessageBox
)

from QScriptEdit2.script_edit import ScriptEdit2
from pygments_highlighter import PygmentsHighlighter
from pygments.styles import get_all_styles

class ScriptEditorApp(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        print("Available Pygments styles:", list(get_all_styles()))
        layout = QVBoxLayout()
        self.editor = ScriptEdit2()
        layout.addWidget(self.editor)

        self.run_button = QPushButton("Run Script")
        self.run_button.clicked.connect(self.run_script)
        layout.addWidget(self.run_button)

        self.setLayout(layout)

    def run_script(self):
        code = self.editor.toPlainText()
        try:
            exec(code, globals(), locals())
        except Exception as e:
            QMessageBox.critical(self, "Script Error", f"Error running script:\n{e}")


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication

    app = QApplication([])
    editor = ScriptEditorApp()
    editor.show()
    app.exec()