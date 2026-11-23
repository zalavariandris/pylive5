from enum import IntEnum
from qtpy.QtCore import Qt

class InspectorRoles(IntEnum):
    DataTypeRole = Qt.ItemDataRole.UserRole + 100
    DefaultValueRole = Qt.ItemDataRole.UserRole + 101
    