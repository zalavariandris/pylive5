from qtpy.QtCore import Qt




from enum import Enum, auto, IntEnum
class ShapeData(Enum):
    Circle = auto()
    Square = auto()
    Diamond = auto()
    Bar = auto()

class NodeDataRole(IntEnum):
    SocketAlignmentRole = Qt.ItemDataRole.UserRole+11
    ShapeDataRole = Qt.ItemDataRole.UserRole+22
    LeadingRole = Qt.ItemDataRole.UserRole+33
    TrailingRole = Qt.ItemDataRole.UserRole+44