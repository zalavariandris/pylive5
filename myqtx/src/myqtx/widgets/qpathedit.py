from typing import *
from qtpy.QtCore import Signal
from qtpy.QtWidgets import QStyle, QLineEdit, QHBoxLayout, QWidget, QFileDialog

import pathlib


class QPathEdit(QWidget):
    pathChanged = Signal(pathlib.Path)
    
    def __init__(self, 
        path:pathlib.Path=pathlib.Path.cwd(), 
        parent:QWidget|None=None
    ):
        super().__init__(parent=parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._lineedit = QLineEdit(str(path))
        style = self.style()
        assert style is not None, "Style is not set"
        folder_pixmap = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        action = self._lineedit.addAction(folder_pixmap, QLineEdit.ActionPosition.TrailingPosition)
        action.triggered.connect(self.open)

        layout.addWidget(self._lineedit)

        self._lineedit.textChanged.connect(lambda text: self.pathChanged.emit(pathlib.Path(text)))
        
    def open(self):
        filename, _ = QFileDialog.getOpenFileName(self)
        if filename:
            self._lineedit.setText(filename)
        
    def path(self) -> pathlib.Path:
        return pathlib.Path(self._lineedit.text())
        
    def setPath(self, path:pathlib.Path|str):
        self._lineedit.setText(str(path))


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    window = QWidget()
    main_layout = QVBoxLayout()
    window.setLayout(main_layout)
    path_edit = QPathEdit()

    main_layout.addWidget(path_edit)
    window.show()
    app.exec()