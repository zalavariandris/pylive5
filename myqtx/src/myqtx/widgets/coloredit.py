from qtpy.QtCore import (
    QPoint, 
    QSignalBlocker, 
    Signal, 
    Qt,
    Property
)

from qtpy.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget, QDoubleSpinBox
from qtpy.QtGui import QColor

from .colorwheel import ColorWheel

class ColorEdit(QWidget):
    colorChanged = Signal(QColor)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)

        self._r_edit = QDoubleSpinBox(self)
        self._g_edit = QDoubleSpinBox(self)
        self._b_edit = QDoubleSpinBox(self)
        self._a_edit = QDoubleSpinBox(self)
        self._editors = (self._r_edit, self._g_edit, self._b_edit, self._a_edit)
        for editor, channel in zip(self._editors, "RGBA"):
            editor.setRange(0.0, 1.0)
            editor.setSingleStep(0.01)
            editor.setPrefix(channel + ": ")
            editor.valueChanged.connect(self._updateValue)
            layout.addWidget(editor)
            editor.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )

        self._color_swatch = QPushButton(self)
        self._color_swatch.setFixedSize(20, 20)
        self._color_swatch.setToolTip("Choose color")
        self._color_swatch.setAccessibleName("Choose color")
        self._color_swatch.clicked.connect(self._showColorWheel)
        layout.addWidget(self._color_swatch)

        self._color_wheel = ColorWheel(self)
        self._color_wheel.setWindowFlags(Qt.Popup)
        self._color_wheel.resize(180, 180)
        self._color_wheel.colorChanged.connect(self.setColor)

        self._color = QColor()
        self.setColor(QColor.fromRgbF(0.0, 0.0, 0.0, 1.0))

    def _showColorWheel(self) -> None:
        with QSignalBlocker(self._color_wheel):
            self._color_wheel.setColor(self._color)
        self._color_wheel.move(
            self._color_swatch.mapToGlobal(QPoint(0, self._color_swatch.height()))
        )
        self._color_wheel.show()

    def _updateValue(self) -> None:
        self.setColor(QColor.fromRgbF(
            self._r_edit.value(),
            self._g_edit.value(),
            self._b_edit.value(),
            self._a_edit.value(),
        ))

    def _updateColorSwatch(self) -> None:
        color = (
            f"rgba({self._color.red()}, {self._color.green()}, "
            f"{self._color.blue()}, {self._color.alpha()})"
        )
        self._color_swatch.setStyleSheet(f"background-color: {color};")

    def getColor(self) -> QColor:
        return QColor(self._color)

    def setColor(self, color: QColor) -> None:
        if color == self._color:
            return
        
        self._color = QColor(color)
        for editor, value in zip(self._editors, self._color.getRgbF()):
            with QSignalBlocker(editor):
                editor.setValue(value)
        self._updateColorSwatch()
        self.colorChanged.emit(self.getColor())

    color = Property(QColor, getColor, setColor, notify=colorChanged, user=True)

