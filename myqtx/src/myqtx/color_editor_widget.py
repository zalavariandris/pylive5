from qtpy.QtCore import QPoint, QSignalBlocker, Signal, Qt
from qtpy.QtWidgets import QLineEdit, QHBoxLayout, QPushButton, QWidget
from qtpy.QtGui import QDoubleValidator

from myqtx.colorwheel import ColorWheel


class ColorEdit(QWidget):
    valueChanged = Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)

        self._r_edit = QLineEdit(self)
        self._g_edit = QLineEdit(self)
        self._b_edit = QLineEdit(self)
        self._a_edit = QLineEdit(self)
        self._editors = (self._r_edit, self._g_edit, self._b_edit, self._a_edit)
        for editor, channel in zip(self._editors, "RGBA"):
            editor.setValidator(QDoubleValidator(0.0, 1.0, 3, self))
            editor.setPlaceholderText(channel)
            editor.textChanged.connect(self._updateValue)
            layout.addWidget(editor)

        self._color_swatch = QPushButton(self)
        self._color_swatch.setFixedSize(20, 20)
        self._color_swatch.setToolTip("Choose color")
        self._color_swatch.setAccessibleName("Choose color")
        self._color_swatch.clicked.connect(self._showColorWheel)
        layout.addWidget(self._color_swatch)

        self._color_wheel = ColorWheel(self)
        self._color_wheel.setWindowFlags(Qt.Popup)
        self._color_wheel.resize(180, 180)
        self._color_wheel.valueChanged.connect(self.setColor)

        self.setColor(0.0, 0.0, 0.0, 1.0)

    def _showColorWheel(self):
        with QSignalBlocker(self._color_wheel):
            self._color_wheel.setColor(*self._color)
        self._color_wheel.move(
            self._color_swatch.mapToGlobal(QPoint(0, self._color_swatch.height()))
        )
        self._color_wheel.show()

    def _updateValue(self):
        try:
            color = tuple(
                float(editor.text() or default)
                for editor, default in zip(self._editors, (0.0, 0.0, 0.0, 1.0))
            )
        except ValueError:
            return
        self._color = color
        self._updateColorSwatch(*color)
        self.valueChanged.emit(*color)

    def _updateColorSwatch(self, r: float, g: float, b: float, a: float):
        color = f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {a})"
        self._color_swatch.setStyleSheet(f"background-color: {color};")

    def color(self) -> tuple[float, float, float, float]:
        return self._color

    def setColor(self, r: float, g: float, b: float, a: float = 1.0):
        self._color = (r, g, b, a)
        for editor, value in zip(self._editors, self._color):
            with QSignalBlocker(editor):
                editor.setText(str(value))
        self._updateColorSwatch(r, g, b, a)
        self.valueChanged.emit(r, g, b, a)
