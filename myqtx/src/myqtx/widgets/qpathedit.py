from typing import *
from qtpy.QtCore import Signal, Property, Qt
from qtpy.QtWidgets import QStyle, QLineEdit, QHBoxLayout, QWidget, QFileDialog
from qtpy.QtWidgets import QAction

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

        self._lineedit.textChanged.connect(
            lambda text: self.pathChanged.emit(pathlib.Path(text))
        )

        self._lineedit.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._lineedit.customContextMenuRequested.connect(
            self._show_context_menu
        )

    def sizeHint(self):
        hint = self._lineedit.sizeHint()
        hint.setWidth(200)  # Example adjustment, increase width by 50 pixels
        return hint
    
    def open(self):
        filename, _ = QFileDialog.getOpenFileName(self)
        if filename:
            self._lineedit.setText(filename)
        
    def getPath(self) -> pathlib.Path:
        return pathlib.Path(self._lineedit.text())
        
    def setPath(self, path:pathlib.Path|str):
        self._lineedit.setText(str(path))

    def _set_relative_to_cwd(self):
        self.setPath(self.getPath().relative_to(pathlib.Path.cwd()))

    def _set_absolute(self):
        self.setPath(self.getPath().absolute())

    def _show_context_menu(self, pos):
        menu = self._lineedit.createStandardContextMenu()
        assert menu is not None, "Failed to create context menu"
        
        
        make_relative_action = QAction("Make Path Relative", self._lineedit, 
            triggered=lambda: self._set_relative_to_cwd()
        )
        menu.addAction(make_relative_action)

        make_absolute_action = QAction("Make Path Absolute", self._lineedit, 
            triggered=lambda: self._set_absolute()
        )
        menu.addAction(make_absolute_action)
        if self.getPath().is_absolute():
            make_relative_action.setEnabled(True)
            make_absolute_action.setEnabled(False)
        else:
            make_relative_action.setEnabled(False)
            make_absolute_action.setEnabled(True)

        action_clear = QAction("Clear", self._lineedit, triggered=lambda: self._lineedit.clear())
        menu.addAction(action_clear)
        menu.exec(self._lineedit.mapToGlobal(pos))



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