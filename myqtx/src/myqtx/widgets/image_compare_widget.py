from qtpy.QtCore import Qt
from qtpy.QtGui import QImage, QPainter
from qtpy.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

import numpy as np

from .. import utils
from .imagecanvas import ImageCanvas


class ImageCompareWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._A = QImage()
        self._B = QImage()
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

    def set_images(self, A: np.ndarray, B: np.ndarray, *, channel_axis: int = -1) -> None:
        A = utils.img_to_qimage(A, channel_axis=channel_axis)
        B = utils.img_to_qimage(B, channel_axis=channel_axis)
        if A.size() != B.size():
            B = B.scaled(
                A.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._A, self._B = A, B
        self._render()

    def _render(self) -> None:
        if self._A.isNull() or self._B.isNull():
            return
        result = QImage(self._A.size(), QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        try:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(0, 0, self._B)
            split = self._A.width() * self.slider.value() // self.slider.maximum()
            painter.setClipRect(0, 0, split, self._A.height())
            painter.drawImage(0, 0, self._A)
        finally:
            painter.end()
        self.canvas.set_image(result)

    def clear(self) -> None:
        self._A = QImage()
        self._B = QImage()
        self.canvas.clear()
        self.slider.setValue(500)
