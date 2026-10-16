from turtle import color
from dataclasses import dataclass

from qtpy.QtCore import QObject, QPointF, QRect, QRectF, Qt
from qtpy.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen, QPen
from qtpy.QtWidgets import QApplication, QStyle, QStyleOptionGraphicsItem, QStyleOptionViewItem
from typing import TYPE_CHECKING, Iterable

# if TYPE_CHECKING:
from qdageditor5.models.abstract_dag_model import AbstractDAGModel, NodeName, InletName, OutletName


import abc

from ..core.item_data_roles import NodeDataRole

class _Graphics(abc.ABC):
    @abc.abstractmethod
    def boundingRect(self, option: QStyleOptionViewItem) -> QRectF:
        pass

    @abc.abstractmethod
    def paint(self, painter: QPainter, option: QStyleOptionViewItem):
        pass

class _Label(_Graphics):
    def __init__(self, text: str | None, pos: QPointF, alignment: Qt.AlignmentFlag, pen: QPen, padding: tuple[float, float] = (4.0, 2.0)) -> None:
        self.text = "" if text is None else str(text)
        self.pos = pos
        self.alignment = alignment
        self.pen = pen
        self.padding = padding

    def boundingRect(self, option: QStyleOptionViewItem) -> QRectF:
        text_rect = QRectF(
            option.fontMetrics.boundingRect(
                QRect(),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                self.text,
            )
        )
        text_rect.adjust(-self.padding[0], -self.padding[1], self.padding[0], self.padding[1])

        h = self.alignment & Qt.AlignmentFlag.AlignHorizontal_Mask
        if h == Qt.AlignmentFlag.AlignRight:
            x = self.pos.x() - text_rect.width()
        elif h == Qt.AlignmentFlag.AlignHCenter:
            x = self.pos.x() - text_rect.width() / 2
        else:  # AlignLeft (default)
            x = self.pos.x()

        v = self.alignment & Qt.AlignmentFlag.AlignVertical_Mask
        if v == Qt.AlignmentFlag.AlignBottom:
            y = self.pos.y() - text_rect.height()
        elif v == Qt.AlignmentFlag.AlignVCenter:
            y = self.pos.y() - text_rect.height() / 2
        else:  # AlignTop (default)
            y = self.pos.y()

        text_rect.moveTopLeft(QPointF(x, y))
        return text_rect

    def paint(self, painter: QPainter, option: QStyleOptionViewItem) -> None:
        rect = self.boundingRect(option)
        padding_x, padding_y = self.padding
        rect.adjust(padding_x, padding_y, -padding_x, -padding_y)

        painter.save()
        painter.setFont(option.font)
        painter.setPen(self.pen)
        painter.drawText(rect, int(self.alignment), self.text)
        painter.restore()

class _AnchorPoint:
    def __init__(self, pos: QPointF, radius: float) -> None:
        super().__init__()
        self.pos = pos
        self.radius = radius

    def boundingRect(self, option: QStyleOptionViewItem) -> QRectF:
        return QRectF(self.pos.x() - self.radius, self.pos.y() - self.radius, 2 * self.radius, 2 * self.radius)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem):
        rect = self.boundingRect(option)
        painter.save()
        painter.drawEllipse(rect)
        painter.restore()

# class _Chip(_Label):
#     def __init__(self, text: str, pos: QPointF, alignment: Qt.AlignmentFlag, brush: QBrush, pen: QPen,) -> None:
#         super().__init__(text, pos, alignment, pen)
#         self.brush = brush

#     def paint(self, painter: QPainter, option: QStyleOptionViewItem):
#         rect = self.boundingRect(option)
#         painter.save()
#         painter.setBrush(self.brush)
#         painter.setPen(self.pen)
#         painter.drawRoundedRect(rect, 5, 5)
#         super().paint(painter, option)
#         painter.restore()

def _bounding_rect(rects: list[QRectF]) -> QRectF:
    if not rects:
        return QRectF()
    united_rect = rects[0]
    for rect in rects[1:]:
        united_rect = united_rect.united(rect)
    return united_rect


@dataclass(frozen=True)
class _LabelGeometry:
    text: str
    rect: QRectF
    alignment: Qt.AlignmentFlag
    padding: tuple[float, float]


@dataclass(frozen=True)
class NodeLocalGeometry:
    """Measured node layout relative to its origin, owned by the view."""

    labels: tuple[_LabelGeometry, ...]
    bounding_rect: QRectF
    shape: QPainterPath


class StyledNodeDelegate(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

    def __labels(self, option: QStyleOptionViewItem, model: 'AbstractDAGModel', node: NodeName) -> tuple[_Label, _Label, _Label]:
        palette:QPalette = option.palette

        title_label = _Label(
            text=model.nodeData(node, Qt.ItemDataRole.DisplayRole),
            pos=QPointF(),
            alignment=Qt.AlignmentFlag.AlignCenter,
            pen=QPen(palette.text().color(), 0)
        )

        title_rect = title_label.boundingRect(option)
        leading_label = _Label(
            text=model.nodeData(node, NodeDataRole.LeadingRole),
            pos=title_rect.topLeft(),
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            pen=QPen(palette.placeholderText().color(), 0)
        )

        trailing_label = _Label(
            text=model.nodeData(node, NodeDataRole.TrailingRole),
            pos=title_rect.topRight(),
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            pen=QPen(palette.placeholderText().color(), 0)
        )

        return title_label, leading_label, trailing_label

    def createNodeLocalGeometry(
        self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName,
    ) -> NodeLocalGeometry:
        """Measure once in node-local coordinates; do not retain paint state."""
        labels = tuple(
            _LabelGeometry(
                label.text, label.boundingRect(option), label.alignment, label.padding,
            )
            for label in self.__labels(option, model, node)
        )
        shape = QPainterPath()
        shape.addRoundedRect(labels[0].rect, 5, 5)
        return NodeLocalGeometry(labels, _bounding_rect([label.rect for label in labels]), shape)

    def _nodeLocalRect(self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName) -> QRectF:
        """Measure bounds relative to the node origin; do not apply its position."""
        assert isinstance(option, QStyleOptionViewItem)

        geometry = self.createNodeLocalGeometry(option, model, node)
        return QRectF(geometry.bounding_rect)

    def _nodeLocalShape(self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName) -> QPainterPath:
        """Measure the body shape relative to the node origin."""
        geometry = self.createNodeLocalGeometry(option, model, node)
        return QPainterPath(geometry.shape)
    
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem,
        model: AbstractDAGModel, node: NodeName, geometry: NodeLocalGeometry | None = None,
    ) -> None:
        """Paint node-local geometry; the view positions the painter in the scene."""
        if geometry is None:
            geometry = self.createNodeLocalGeometry(option, model, node)
        style:QStyle = option.widget.style() if option.widget else QApplication.style()
        title_rect = geometry.labels[0].rect

        # Style options and measured geometry both use node-local coordinates.
        option = QStyleOptionViewItem(option)
        option.rect = title_rect.toAlignedRect()

        painter.save()

        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.setFont(option.font)
        painter.setPen(QPen(option.palette.placeholderText().color(), 0))
        for label in geometry.labels[1:]:
            padding_x, padding_y = label.padding
            rect = label.rect.adjusted(padding_x, padding_y, -padding_x, -padding_y)
            painter.drawText(rect, int(label.alignment), label.text)
        painter.restore()

        # paint ouside
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipPath(geometry.shape, Qt.ClipOperation.IntersectClip)
        painter.setPen(QPen(option.palette.text().color(), 0)) # cosmetic pen: always 1 device pixel, even when scaled
        painter.drawRoundedRect(title_rect, 5, 5)
        
        if option.state & QStyle.StateFlag.State_HasFocus:
            # draw a horizontal line at the top of the title label
            painter.setPen(QPen(option.palette.text().color(), 0))
            padding = 2
            inner_rect = title_rect.adjusted(padding, padding, -padding, -padding)
            pen = QPen()
            pen.setColor(option.palette.placeholderText().color())
            # dashed line
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(inner_rect, 3,3)
        painter.restore()
