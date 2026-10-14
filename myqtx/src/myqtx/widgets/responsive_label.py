from qtpy.QtCore import Qt, Signal, Property
from qtpy.QtGui import QFont, QFontMetrics, QImage, QPainter, QPixmap, QResizeEvent
from qtpy.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QSlider, QTextBrowser, QVBoxLayout, QWidget,
)


class ResponsiveLabel(QWidget):
    textChanged = Signal(str)
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.label)

    def getText(self) -> str:
        return self.label.text()

    def setText(self, text: str) -> None:
        self.label.setText(text)
        self._update_font_size()
        self.textChanged.emit(text)

    def _update_font_size(self) -> None:
        text = self.label.text()
        if not text:
            return
        font = QFont(self.label.font())
        font.setPointSize(10)
        rect = QFontMetrics(font).boundingRect(text)
        width_scale = (self.width() - 50) / (rect.width() or 1)
        height_scale = (self.height() - 50) / (rect.height() or 1)
        scale = min(width_scale, height_scale)
        font.setPointSize(max(10, int(10 * scale)))
        self.label.setFont(font)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_font_size()

    text = Property(str, getText, setText, notify=textChanged, user=True)


