from qtpy.QtCore import Qt
from qtpy.QtGui import QImage, QKeyEvent, QPainter, QPixmap, QShowEvent, QWheelEvent
from qtpy.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QWidget


class ImageCanvas(QGraphicsView):
    """An image view with wheel zoom, drag panning, and F to fit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.item = QGraphicsPixmapItem()
        self.scene_.addItem(self.item)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit_pending = False

    def set_image(self, image: QImage) -> None:
        first_image = self.item.pixmap().isNull()
        self.item.setPixmap(QPixmap.fromImage(image))
        self.scene_.setSceneRect(self.item.boundingRect())
        if first_image:
            self.fit_image()

    def fit_image(self) -> None:
        if self.item.pixmap().isNull():
            return
        # Embedded widgets may receive an image before their layout is visible.
        if not self.isVisible():
            self._fit_pending = True
            return
        # A fitted image needs no scrollbars. Size the viewport accordingly
        # before fitting, then restore the policies for zooming and panning.
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
        self.item.setPixmap(QPixmap())
        self.scene_.setSceneRect(self.item.boundingRect())
        self.resetTransform()
        self._fit_pending = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._fit_pending:
            self.fit_image()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if self.item.pixmap().isNull() or delta == 0:
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
