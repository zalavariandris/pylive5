from qtpy.QtCore import QObject, QPointF, QRectF, Qt
from qtpy.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen, QPen
from qtpy.QtWidgets import QStyle, QStyleOptionGraphicsItem, QStyleOptionViewItem
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qdageditor5.models.abstract_dag_model import AbstractDAGModel, NodeName, InletName, OutletName


class StyledNodeDelegate(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

    def rect(self, model: AbstractDAGModel, node: NodeName) -> QRectF:
        """Return the node rectangle in scene coordinates."""
        text = model.nodeData(node, Qt.ItemDataRole.DisplayRole)
        font = QFont("Courier", 9)
        fm = QFontMetricsF(font)
        text_rect = fm.boundingRect(QRectF(), Qt.AlignmentFlag.AlignCenter, text)

        padding = 5.0
        scene_rect = QRectF(
            0.0,
            0.0,
            max(65.0, text_rect.width() + 2 * padding),
            max(16.0, text_rect.height() + 2 * padding),
        )
        scene_rect.moveCenter(model.nodePosition(node))
        return scene_rect

    def shape(self, model: AbstractDAGModel, node: NodeName) -> QPainterPath:
        rect = self.rect(model, node)
        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        return path
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, model: AbstractDAGModel, node_name: NodeName):
        palette:QPalette = option.palette
        if option.state & QStyle.StateFlag.State_Selected:
            brush = QBrush(QColor(0, 120, 215))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            brush = QBrush(palette.highlight())
        else:
            brush = QBrush(palette.base())

        scene_rect = self.rect(model, node_name)

        if model and model.nodeData(node_name, Qt.ItemDataRole.BackgroundRole) is not None:
            brush = model.nodeData(node_name, Qt.ItemDataRole.BackgroundRole)

        # paint background
        painter.setPen(QPen(palette.text().color(), 0)) # cosmetic pen: always 1 device pixel, even when scaled
        painter.setBrush(brush)
        painter.drawRoundedRect(scene_rect, 5, 5)

        # paint text
        painter.setPen(palette.text().color())
        painter.setFont(QFont("Courier", 9))
        text = model.nodeData(node_name, Qt.ItemDataRole.DisplayRole)
        painter.drawText(scene_rect, Qt.AlignmentFlag.AlignCenter, f"{text}")
