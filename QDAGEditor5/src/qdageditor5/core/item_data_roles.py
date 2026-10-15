from enum import IntEnum
from qtpy.QtCore import Qt


class NodeDataRole(IntEnum):
    SocketAlignmentRole = Qt.ItemDataRole.UserRole+11
    ShapeDataRole = Qt.ItemDataRole.UserRole+22
    LeadingRole = Qt.ItemDataRole.UserRole+33
    TrailingRole = Qt.ItemDataRole.UserRole+44
