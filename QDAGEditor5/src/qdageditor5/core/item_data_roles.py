from qtpy.QtCore import Qt

SocketAlignmentRole = Qt.ItemDataRole.UserRole+13
ShapeDataRole = Qt.ItemDataRole.UserRole+22

from enum import Enum, auto
class ShapeData(Enum):
    Circle = auto()
    Square = auto()
    Diamond = auto()
    Bar = auto()