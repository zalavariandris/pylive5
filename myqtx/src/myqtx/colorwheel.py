from math import atan2, cos, hypot, sin, tau

from qtpy.QtCore import QPointF, QRectF, QSize, Signal, Qt
from qtpy.QtWidgets import QWidget
from qtpy.QtGui import QColor, QConicalGradient, QPainter, QPen, QRadialGradient


class ColorWheel(QWidget):
    valueChanged = Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor.fromRgbF(1.0, 1.0, 1.0)
        self._dragging = False

    def minimumSizeHint(self):
        return QSize(100, 100)

    def sizeHint(self):
        return QSize(100, 100)

    def maximumSize(self):
        return QSize(100, 100)

    def setColor(self, r: float, g: float, b: float, a: float = 1.0):
        self._color = QColor.fromRgbF(r, g, b, a)
        self.update()
        self.valueChanged.emit(r, g, b, a)

    def _wheelRect(self):
        size = max(0, min(self.width(), self.height()) - 2)
        return QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)

    def paintEvent(self, event):
        rect = self._wheelRect()
        radius = rect.width() / 2
        if radius <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = rect.center()
        hues = QConicalGradient(center, 0)
        for index in range(7):
            position = index / 6
            hues.setColorAt(position, QColor.fromHsvF(position, 1.0, 1.0))

        painter.setPen(Qt.NoPen)
        painter.setBrush(hues)
        painter.drawEllipse(rect)

        saturation = QRadialGradient(center, radius)
        saturation.setColorAt(0, QColor(255, 255, 255))
        saturation.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(saturation)
        painter.drawEllipse(rect)

        angle = max(0.0, self._color.hsvHueF()) * tau
        distance = self._color.hsvSaturationF() * radius
        marker = center + QPointF(cos(angle) * distance, -sin(angle) * distance)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(Qt.black, 3))
        painter.drawEllipse(marker, 4, 4)
        painter.setPen(QPen(Qt.white, 1))
        painter.drawEllipse(marker, 4, 4)
        painter.end()

    def _selectColor(self, position):
        rect = self._wheelRect()
        radius = rect.width() / 2
        if radius <= 0:
            return

        offset = position - rect.center()
        hue = (atan2(-offset.y(), offset.x()) / tau) % 1.0
        saturation = min(1.0, hypot(offset.x(), offset.y()) / radius)
        color = QColor.fromHsvF(hue, saturation, 1.0, self._color.alphaF())
        self.setColor(*color.getRgbF())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            rect = self._wheelRect()
            offset = QPointF(event.pos()) - rect.center()
            if rect.width() > 0 and hypot(offset.x(), offset.y()) <= rect.width() / 2:
                self._dragging = True
                self._selectColor(QPointF(event.pos()))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton:
            self._selectColor(QPointF(event.pos()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self._selectColor(QPointF(event.pos()))
            event.accept()
            return
        super().mouseReleaseEvent(event)
