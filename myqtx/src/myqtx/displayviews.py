"""Viewer contract and the standard viewers registered by DisplayWidget."""

from typing import Generic, TypeVar

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtGui import QFont, QFontMetrics, QImage, QPainter, QPixmap, QResizeEvent
from qtpy.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QSlider, QTextBrowser, QVBoxLayout, QWidget,
)

from myqtx.cmdstage.data import HTML, Image, ImageCompare, Markdown

from .imagecanvas import ImageCanvas


T = TypeVar("T")


class DisplayView(QWidget, Generic[T]):
    """A reusable viewer. Factories accept a parent; set_data updates content."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_data(self, data: T) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        """Release displayed data when this viewer is hidden or cleared."""


def image_to_qimage(data: np.ndarray | QImage | QPixmap) -> QImage:
    if isinstance(data, QImage):
        return data.copy()
    if isinstance(data, QPixmap):
        return data.toImage().copy()
    if not isinstance(data, np.ndarray):
        raise TypeError("Image data must be a NumPy array, QImage, or QPixmap")
    if data.ndim == 2:
        channels = 1
    elif data.ndim == 3 and data.shape[2] in (1, 3, 4):
        channels = data.shape[2]
    else:
        raise ValueError(
            "Expected an image with shape (H, W), (H, W, 1), (H, W, 3), or (H, W, 4)"
        )
    if data.shape[0] == 0 or data.shape[1] == 0:
        raise ValueError("Image dimensions must be positive")
    if data.dtype in (np.dtype(np.float32), np.dtype(np.float64)):
        data = (np.clip(data, 0.0, 1.0) * 255).astype(np.uint8)
    elif data.dtype != np.uint8:
        raise TypeError("Image dtype must be uint8, float32, or float64")
    data = np.ascontiguousarray(data)
    image_format = {
        1: QImage.Format.Format_Grayscale8,
        3: QImage.Format.Format_RGB888,
        4: QImage.Format.Format_RGBA8888,
    }[channels]
    # The caller may modify or release its array after display() returns.
    return QImage(
        data.data, data.shape[1], data.shape[0], data.strides[0], image_format,
    ).copy()


class ImageView(DisplayView[Image | np.ndarray | QImage | QPixmap]):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = ImageCanvas(self)
        layout.addWidget(self.canvas)
        self.setFocusProxy(self.canvas)

    def set_data(self, data: Image | np.ndarray | QImage | QPixmap) -> None:
        if isinstance(data, Image):
            data = data.data
        self.canvas.set_image(image_to_qimage(data))

    def clear(self) -> None:
        self.canvas.clear()


class ImageCompareView(DisplayView[ImageCompare]):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._a = QImage()
        self._b = QImage()
        self.canvas = ImageCanvas(self)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 1000)
        self.slider.setValue(500)
        self.slider.setToolTip("Move the divider: image A on the left, image B on the right")
        self.slider.valueChanged.connect(self._render)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("A", self))
        controls.addWidget(self.slider)
        controls.addWidget(QLabel("B", self))
        layout.addLayout(controls)
        self.setFocusProxy(self.canvas)

    def set_data(self, data: ImageCompare) -> None:
        a = image_to_qimage(data.a)
        b = image_to_qimage(data.b)
        if a.size() != b.size():
            b = b.scaled(
                a.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._a, self._b = a, b
        self._render()

    def _render(self) -> None:
        if self._a.isNull() or self._b.isNull():
            return
        result = QImage(self._a.size(), QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        try:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(0, 0, self._b)
            split = self._a.width() * self.slider.value() // self.slider.maximum()
            painter.setClipRect(0, 0, split, self._a.height())
            painter.drawImage(0, 0, self._a)
        finally:
            painter.end()
        self.canvas.set_image(result)

    def clear(self) -> None:
        self._a = QImage()
        self._b = QImage()
        self.canvas.clear()


class RichTextView(DisplayView[T]):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.browser = QTextBrowser(self)
        layout.addWidget(self.browser)
        self.setFocusProxy(self.browser)

    def clear(self) -> None:
        self.browser.clear()


class HTMLView(RichTextView[HTML]):
    def set_data(self, data: HTML) -> None:
        self.browser.setHtml(data.data)


class MarkdownView(RichTextView[Markdown]):
    def set_data(self, data: Markdown) -> None:
        self.browser.setMarkdown(data.data)


class TextView(DisplayView[object]):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.label)

    def set_data(self, data: object) -> None:
        color = "black"
        match data:
            case str() | int() | float() | bool():
                text = str(data)
            case list() | tuple() | dict():
                text = f"Output: {data}"
            case BaseException():
                text, color = f"Exception: {data}", "red"
            case None:
                text, color = "None", "gray"
            case _:
                text, color = f"Unsupported output type: {type(data)}", "orange"
        self.label.setStyleSheet(f"color: {color}")
        self.label.setText(text)
        self._update_font_size()

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

    def clear(self) -> None:
        self.label.clear()
