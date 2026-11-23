from qtpy.QtCore import (
    QPoint, 
    QSignalBlocker, 
    Signal, 
    Qt,
    Property
)

from qtpy.QtWidgets import QAbstractSpinBox, QHBoxLayout, QPushButton, QSizePolicy, QWidget, QDoubleSpinBox
from qtpy.QtGui import QColor, QPaintEvent, QPainter

from .colorpicker import ColorPicker


class _ColorSwatch(QPushButton):
    """Compare the opaque color with its alpha over a checkerboard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(Qt.GlobalColor.black)

    def setColor(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        rect = self.rect().adjusted(3, 3, -3, -3)
        top = rect.adjusted(0, 0, 0, -rect.height() // 2)
        bottom = rect.adjusted(0, top.height(), 0, 0)

        opaque = QColor(self._color)
        opaque.setAlpha(255)
        painter.fillRect(top, opaque)

        painter.setClipRect(bottom)
        tile_size = 4
        for y in range(bottom.top(), bottom.bottom() + 1, tile_size):
            for x in range(bottom.left(), bottom.right() + 1, tile_size):
                column = (x - bottom.left()) // tile_size
                row = (y - bottom.top()) // tile_size
                shade = 220 if (column + row) % 2 else 255
                painter.fillRect(x, y, tile_size, tile_size, QColor(shade, shade, shade))
        painter.fillRect(bottom, self._color)
        painter.end()


class ColorEdit(QWidget):
    colorChanged = Signal(QColor)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setSpacing(0)

        self._r_edit = QDoubleSpinBox(self)
        self._g_edit = QDoubleSpinBox(self)
        self._b_edit = QDoubleSpinBox(self)
        self._a_edit = QDoubleSpinBox(self)
        self._editors = (self._r_edit, self._g_edit, self._b_edit, self._a_edit)
        for editor, channel in zip(self._editors, "RGBA"):
            editor.setRange(0.0, 1.0)
            editor.setSingleStep(0.01)
            editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            # editor.setPrefix(channel + ": ")
            editor.valueChanged.connect(self._updateValue)
            layout.addWidget(editor)
            editor.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )

        self._color_swatch = _ColorSwatch(self)
        self._color_swatch.setFixedSize(20, 20)
        self._color_swatch.setToolTip("Choose color")
        self._color_swatch.setAccessibleName("Choose color")
        self._color_swatch.clicked.connect(self._showColorWheel)
        layout.addWidget(self._color_swatch)

        self._color_picker = ColorPicker(self)
        self._color_picker.setWindowFlags(Qt.Popup)
        self._color_picker.colorChanged.connect(self.setColor)

        self._color = QColor()
        self.setColor(QColor.fromRgbF(0.0, 0.0, 0.0, 1.0))

    def _showColorWheel(self) -> None:
        with QSignalBlocker(self._color_picker):
            self._color_picker.setColor(self._color)
        self._color_picker.adjustSize()
        self._color_picker.move(
            self._color_swatch.mapToGlobal(QPoint(0, self._color_swatch.height()))
        )
        self._color_picker.show()

    def _updateValue(self) -> None:
        self.setColor(QColor.fromRgbF(
            self._r_edit.value(),
            self._g_edit.value(),
            self._b_edit.value(),
            self._a_edit.value(),
        ))

    def _updateColorSwatch(self) -> None:
        self._color_swatch.setColor(self._color)

    def getColor(self) -> QColor:
        return QColor(self._color)

    def setColor(self, color: QColor) -> None:
        if color == self._color:
            return
        
        self._color = QColor(color)
        for editor, value in zip(self._editors, self._color.getRgbF()):
            with QSignalBlocker(editor):
                editor.setValue(value)
        with QSignalBlocker(self._color_picker):
            self._color_picker.setColor(self._color)
        self._updateColorSwatch()
        self.colorChanged.emit(self.getColor())

    color = Property(QColor, getColor, setColor, notify=colorChanged, user=True)

