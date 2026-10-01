from turtle import color

from qtpy.QtCore import QObject, QPointF, QRect, QRectF, Qt
from qtpy.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen, QPen
from qtpy.QtWidgets import QStyle, QStyleOptionGraphicsItem, QStyleOptionViewItem
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from qdageditor5.models.abstract_dag_model import AbstractDAGModel, NodeName, InletName, OutletName


import abc

from ..core.item_data_roles import NodeDataRole

class _Graphics(abc.ABC):
    @abc.abstractmethod
    def boundingRect(self) -> QRectF:
        pass

    @abc.abstractmethod
    def paint(self, painter: QPainter, option: QStyleOptionViewItem):
        pass

class _Label:
    def __init__(self, text: str, pos: QPointF, alignment: Qt.AlignmentFlag, pen: QPen, padding: tuple[float, float] = (4.0, 2.0)) -> None:
        self.text = text
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

class StyledNodeDelegate(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

    def __labels(self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName) -> Iterable[_Graphics]:
        palette:QPalette = option.palette

        title_label = _Label(
            text=model.nodeData(node, Qt.ItemDataRole.DisplayRole),
            pos=model.nodePosition(node),
            alignment=Qt.AlignmentFlag.AlignCenter,
            pen=QPen(palette.text().color(), 0)
        )

        leading_label = _Label(
            text=model.nodeData(node, NodeDataRole.LeadingRole),
            pos=title_label.boundingRect(option).topLeft(),
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            pen=QPen(palette.placeholderText().color(), 0)
        )

        trailing_label = _Label(
            text=model.nodeData(node, NodeDataRole.TrailingRole),
            pos=title_label.boundingRect(option).topRight(),
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            pen=QPen(palette.placeholderText().color(), 0)
        )

        return [title_label, leading_label, trailing_label]

    def rect(self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName) -> QRectF:
        # assert isinstance(model, AbstractDAGModel)
        assert isinstance(option, QStyleOptionViewItem)

        scene_rect = _bounding_rect([
            item.boundingRect(option) 
            for item in self.__labels(option, model, node)
        ])
  
        # text = model.nodeData(node, Qt.ItemDataRole.DisplayRole)
        # fm = option.fontMetrics
        # text_rect = fm.boundingRect(QRect(), Qt.AlignmentFlag.AlignCenter, f"{text}")

        # padding = 4.0, 1.0
        # scene_rect = QRectF(
        #     0.0,
        #     0.0,
        #     max(65.0, text_rect.width() + 2 * padding[0]),
        #     max(16.0, text_rect.height() + 2 * padding[1]),
        # )
        # scene_rect.moveCenter(model.nodePosition(node))
        return scene_rect

    def shape(self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName) -> QPainterPath:
        # rect = self.rect(option, model, node)
        title_label, leading_label, trailing_label = self.__labels(option, model, node)

        path = QPainterPath()
        path.addRoundedRect(title_label.boundingRect(option), 5, 5)
        return path
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName):
        painter.save()
        # paint shape
        palette:QPalette = option.palette


        if option.state & QStyle.StateFlag.State_Selected:
            brush = QBrush(QColor(0, 120, 215))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            brush = QBrush(palette.highlight())
        else:
            brush = QBrush(palette.base())

        if model and model.nodeData(node, Qt.ItemDataRole.BackgroundRole) is not None:
            brush = model.nodeData(node, Qt.ItemDataRole.BackgroundRole)
        path = self.shape(option, model, node)
        painter.setPen(QPen(palette.text().color(), 0)) # cosmetic pen: always 1 device pixel, even when scaled
        painter.setBrush(brush)
        painter.drawPath(path)
        painter.restore()

        # paint labels
        painter.save()
        for graphic in self.__labels(option, model, node):
            graphic.paint(painter, option)
        painter.restore()

        # # debug
        # painter.save()
        # painter.setPen(QPen(Qt.GlobalColor.darkMagenta, 0))
        # _AnchorPoint(
        #     pos=model.nodePosition(node),
        #     radius=3.0,
        # ).paint(painter, option)
        # painter.setPen(QPen(Qt.GlobalColor.darkMagenta, 0, Qt.PenStyle.DashLine))
        # painter.drawRect(self.rect(option, model, node))
        
        # painter.restore()
        
        # palette:QPalette = option.palette
        # if option.state & QStyle.StateFlag.State_Selected:
        #     brush = QBrush(QColor(0, 120, 215))
        # elif option.state & QStyle.StateFlag.State_MouseOver:
        #     brush = QBrush(palette.highlight())
        # else:
        #     brush = QBrush(palette.base())

        # scene_rect = self.rect(option, model, node_name)

        # if model and model.nodeData(node_name, Qt.ItemDataRole.BackgroundRole) is not None:
        #     brush = model.nodeData(node_name, Qt.ItemDataRole.BackgroundRole)

        # # paint background
        # painter.setPen(QPen(palette.text().color(), 0)) # cosmetic pen: always 1 device pixel, even when scaled
        # painter.setBrush(brush)
        # painter.drawRoundedRect(scene_rect, 5, 5)

        # # paint text
        # painter.setPen(palette.text().color())
        # painter.setFont(option.font)
        # text = model.nodeData(node_name, Qt.ItemDataRole.DisplayRole)
        # painter.drawText(scene_rect, Qt.AlignmentFlag.AlignCenter, f"{text}")
