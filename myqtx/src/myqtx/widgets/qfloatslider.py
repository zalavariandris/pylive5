from typing import *
from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import QSlider, QStyle, QLineEdit, QHBoxLayout, QWidget, QFileDialog

import pathlib


class QFloatSlider(QWidget):
    valueChanged = Signal(float)
    
    def __init__(self, 
        orientation:Qt.Orientation=Qt.Orientation.Horizontal, 
        parent:QWidget|None=None
    ):
        super().__init__(parent=parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._slider = QSlider(
            orientation=orientation,
            parent=self
        )
        style = self.style()
        assert style is not None, "Style is not set"

        layout.addWidget(self._slider)

        self._slider.valueChanged.connect(lambda value: self.valueChanged.emit(float(value)))
                
    def value(self) -> float:
        return float(self._slider.value()/100.0)  # Assuming the slider's range is 0-100 for float representation

    def setValue(self, value:float):
        self._slider.setValue(int(value*100.0))  # Convert float to slider's integer range


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    window = QWidget()
    main_layout = QVBoxLayout()
    window.setLayout(main_layout)
    path_edit = QFloatSlider()

    main_layout.addWidget(path_edit)
    window.show()
    app.exec()