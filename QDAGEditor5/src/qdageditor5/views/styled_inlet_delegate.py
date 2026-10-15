from qtpy.QtCore import QObject, QRectF, QPointF
from qtpy.QtGui import QPainter, QPainterPath, QFontMetrics
from qtpy.QtWidgets import QStyleOptionViewItem

class StyledNodeDelegate(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)


    def paint(self, painter: QPainter, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName, inlet: InletName):
        ...
