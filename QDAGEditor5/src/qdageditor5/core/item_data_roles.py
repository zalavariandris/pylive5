from enum import IntEnum
from qtpy.QtCore import Qt


class NodeDataRole(IntEnum):
    TrailingRole = Qt.ItemDataRole.UserRole+44

class SocketDataRole(IntEnum):
    HiddenRole = Qt.ItemDataRole.UserRole+101
    SocketAlignmentRole = Qt.ItemDataRole.UserRole+111
    ShapeDataRole = Qt.ItemDataRole.UserRole+222
