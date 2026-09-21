from typing import Any
import numpy as np

from qtpy.QtCore import (
    Qt
)
from qtpy.QtWidgets import QSizePolicy, QVBoxLayout, QLabel

from qtpy.QtWidgets import (
    QWidget
)

from qtpy.QtGui import (
    QFont,
    QFontMetrics,
    QImage,
    QPixmap
)

class DisplayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel("Viewer")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.label)

    def _update_label_font_size(self):
        min_font_size = 10
        text = self.label.text()
        if not text:
            return
        font = QFont(self.label.font())
        font.setPointSize(min_font_size)
        fm = QFontMetrics(font)
        text_rect = fm.boundingRect(text)
        text_width = text_rect.width() or 1
        text_height = text_rect.height() or 1
        # scale relative to the min_font_size measurement, so text grows to fill the available space
        margin=50
        scale = min((self.width() - margin) / text_width, (self.height() - margin) / text_height)
        font.setPointSize(max(min_font_size, int(min_font_size * scale)))
        self.label.setFont(font)

    def resizeEvent(self, event):
        # set label font size, so text fits right in the widget
        self._update_label_font_size()
        
    def display(self, data:Any):
        match data:
            case str() | int() | float() | bool():
                self.label.setStyleSheet("color: black")
                self.label.setText(str(data))
                self._update_label_font_size()

            case list() | tuple():
                self.label.setStyleSheet("color: black")
                self.label.setText(f"Output: {data}")
                self._update_label_font_size()

            case dict():
                self.label.setStyleSheet("color: black")
                self.label.setText(f"Output: {data}")
                self._update_label_font_size()

            case np.ndarray():
                self.label.setStyleSheet("color: black")
                # Accept grayscale (H, W) or channel-last (H, W, C) images.
                if data.ndim == 2:
                    channels = 1
                elif data.ndim == 3 and data.shape[2] in (1, 3, 4):
                    channels = data.shape[2]
                else:
                    raise ValueError("Expected an image with shape (H, W), (H, W, 1), (H, W, 3), or (H, W, 4)")

                # Floating-point images use the normalized range [0, 1].
                if data.dtype == np.float32 or data.dtype == np.float64:
                    data = (np.clip(data, 0.0, 1.0) * 255).astype(np.uint8)
                elif data.dtype != np.uint8:
                    raise TypeError("Image dtype must be uint8, float32, or float64")

                data = np.ascontiguousarray(data)
                image_format = {
                    1: QImage.Format.Format_Grayscale8,
                    3: QImage.Format.Format_RGB888,
                    4: QImage.Format.Format_RGBA8888,
                }[channels]
                qimg = QImage(data.data, data.shape[1], data.shape[0], data.strides[0], image_format)
                self.label.setPixmap(QPixmap(qimg))
                self._update_label_font_size()

            case BaseException():
                self.label.setStyleSheet("color: red")
                self.label.setText(f"Exception: {data}")
                self._update_label_font_size()
                

            case _:
                self.label.setStyleSheet("color: orange")
                self.label.setText(f"Unsupported output type: {type(data)}")
                self._update_label_font_size()
