from qtpy.QtCore import Property, QSignalBlocker, Qt, Signal
from qtpy.QtGui import QColor, QPaintEvent, QPainter
from qtpy.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .colorwheel import ColorWheel
from .qfloatslider import QFloatSlider


class _ColorPreview(QWidget):
    """Show the selected color over a checkerboard to reveal its opacity."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(Qt.GlobalColor.white)
        self.setFixedHeight(24)

    def setColor(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        tile_size = 8
        for y in range(0, self.height(), tile_size):
            for x in range(0, self.width(), tile_size):
                shade = 220 if (x // tile_size + y // tile_size) % 2 else 255
                painter.fillRect(x, y, tile_size, tile_size, QColor(shade, shade, shade))
        painter.fillRect(self.rect(), self._color)
        painter.end()


class ColorPicker(QWidget):
    """A hue/saturation wheel with brightness and opacity controls."""

    colorChanged = Signal(QColor)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._wheel = ColorWheel(self)
        self._wheel.setFixedSize(180, 180)
        wheel_row = QHBoxLayout()
        wheel_row.addWidget(self._wheel)

        self._brightness = QFloatSlider(Qt.Orientation.Vertical, parent=self)
        self._brightness.setAccessibleName("Brightness")
        self._brightness.setToolTip("Brightness: 0 is black, 1 is full brightness")
        brightness_column = QVBoxLayout()
        brightness_label = QLabel("Brightness", self)
        brightness_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        brightness_column.addWidget(brightness_label)
        brightness_column.addWidget(self._brightness, stretch=1)
        wheel_row.addLayout(brightness_column)
        layout.addLayout(wheel_row)

        self._opacity = QFloatSlider(parent=self)
        self._opacity.setAccessibleName("Opacity")
        self._opacity.setToolTip("Opacity: 0 is transparent, 1 is opaque")
        controls = QFormLayout()
        controls.addRow("Opacity", self._opacity)
        layout.addLayout(controls)

        self._preview = _ColorPreview(self)
        layout.addWidget(self._preview)
        self._color = QColor()
        self.setColor(self._wheel.getColor())

        self._wheel.colorChanged.connect(self.setColor)
        self._brightness.valueChanged.connect(self._setBrightness)
        self._opacity.valueChanged.connect(self._setOpacity)

    def getColor(self) -> QColor:
        return QColor(self._color)

    def setColor(self, color: QColor) -> None:
        if not color.isValid():
            return
        # The wheel retains HSV coordinates even at zero brightness.
        with QSignalBlocker(self._wheel):
            self._wheel.setColor(color)
        color = self._wheel.getColor()
        if color == self._color:
            return
        self._color = QColor(color)
        with QSignalBlocker(self._brightness):
            self._brightness.setValue(color.valueF())
        with QSignalBlocker(self._opacity):
            self._opacity.setValue(color.alphaF())
        self._preview.setColor(color)
        self.colorChanged.emit(self.getColor())

    def _setBrightness(self, value: float) -> None:
        color = self._wheel.getColor()
        self.setColor(QColor.fromHsvF(
            color.hsvHueF(), color.hsvSaturationF(), value, color.alphaF(),
        ))

    def _setOpacity(self, alpha: float) -> None:
        color = self._wheel.getColor()
        color.setAlphaF(alpha)
        self.setColor(color)

    color = Property(QColor, getColor, setColor, notify=colorChanged, user=True)
