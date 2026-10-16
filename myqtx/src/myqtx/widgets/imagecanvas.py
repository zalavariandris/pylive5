from __future__ import annotations

import numpy as np

from qtpy.QtCore import Qt, QRectF
from qtpy.QtGui import QImage, QKeyEvent, QPainter, QPixmap, QShowEvent, QWheelEvent
from qtpy.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)


class NumpyImageItem(QGraphicsItem):
    """Paint an RGBA image without constructing a QPixmap per frame.

    The cached uint8 array backs QImage's pixels. Both are owned by this item.
    Call setImage only from the GUI thread, not concurrently with painting.
    """

    def __init__(self) -> None:
        super().__init__()
        self._rect = QRectF()
        self._image = QImage()
        self._byte_buffer: np.ndarray | None = None
        self._float_buffer: np.ndarray | None = None
        self._image_owner: np.ndarray | None = None

    def boundingRect(self) -> QRectF:
        return self._rect

    def hasImage(self) -> bool:
        return not self._image.isNull()

    def clear(self) -> None:
        if not self._rect.isEmpty():
            self.prepareGeometryChange()
        self._image = QImage()
        self._rect = QRectF()
        self._image_owner = None
        self._byte_buffer = None
        self._float_buffer = None
        self.update()

    def setImage(self, data: np.ndarray | QImage | QPixmap) -> None:
        if isinstance(data, QPixmap):
            data = data.toImage()

        if isinstance(data, QImage):
            image = data.copy()  # independent of caller's subsequent changes
            owner = None
        elif isinstance(data, np.ndarray):
            if data.ndim != 3 or data.shape[2] != 4:
                raise ValueError('Expected RGBA data with shape (H, W, 4)')
            if data.shape[0] == 0 or data.shape[1] == 0:
                raise ValueError('Image dimensions must be positive')

            if data.dtype == np.float32:
                if self._byte_buffer is None or self._byte_buffer.shape != data.shape:
                    self._byte_buffer = np.empty(data.shape, dtype=np.uint8)
                    self._float_buffer = np.empty(data.shape, dtype=np.float32)
                assert self._float_buffer is not None
                np.clip(data, 0.0, 1.0, out=self._float_buffer)
                np.multiply(self._float_buffer, 255.0, out=self._float_buffer)
                np.copyto(self._byte_buffer, self._float_buffer, casting='unsafe')
                pixels = self._byte_buffer
            elif data.dtype == np.uint8:
                # Copy into owned storage: the caller may reuse/modify data immediately.
                if self._byte_buffer is None or self._byte_buffer.shape != data.shape:
                    self._byte_buffer = np.empty(data.shape, dtype=np.uint8)
                np.copyto(self._byte_buffer, data)
                pixels = self._byte_buffer
            else:
                raise TypeError(f'Expected float32 or uint8 RGBA NumPy array, got {data.dtype}')

            height, width = pixels.shape[:2]
            owner = pixels
            image = QImage(
                pixels.data, width, height, pixels.strides[0],
                QImage.Format.Format_RGBA8888,
            )
        else:
            raise TypeError(f'Unsupported image type: {type(data)!r}')

        new_rect = QRectF(0, 0, image.width(), image.height())
        if new_rect != self._rect:
            self.prepareGeometryChange()
            self._rect = new_rect
        self._image_owner = owner
        self._image = image
        self.update()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        if not self._image.isNull():
            painter.drawImage(self._rect, self._image)


class ImageCanvas(QGraphicsView):
    """Image view with wheel zoom, drag panning and F to fit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-1e6, -1e6, 2e6, 2e6)
        self.setScene(self._scene)

        self.item = NumpyImageItem()
        self._scene.addItem(self.item)

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit_pending = False

    def set_image(self, data: np.ndarray | QImage | QPixmap) -> None:
        first_image = not self.item.hasImage()
        self.item.setImage(data)
        if first_image:
            self.fit_image()

    def fit_image(self) -> None:
        if not self.item.hasImage():
            return
        if not self.isVisible():
            self._fit_pending = True
            return

        horizontal = self.horizontalScrollBarPolicy()
        vertical = self.verticalScrollBarPolicy()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self.fitInView(self.item, Qt.AspectRatioMode.KeepAspectRatio)
        finally:
            self.setHorizontalScrollBarPolicy(horizontal)
            self.setVerticalScrollBarPolicy(vertical)
        self._fit_pending = False

    def clear(self) -> None:
        self.item.clear()
        self._scene.setSceneRect(self.item.boundingRect())
        self.resetTransform()
        self._fit_pending = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._fit_pending:
            self.fit_image()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if not self.item.hasImage() or delta == 0:
            event.ignore()
            return
        factor = 1.25 if delta > 0 else 0.8
        self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F:
            self.fit_image()
            event.accept()
        else:
            super().keyPressEvent(event)
