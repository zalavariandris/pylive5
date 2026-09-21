"""Roles shared by flat inspector models and InspectorView.

DisplayRole is the property label; EditRole is its raw value.
Horizontal header section 0 supplies the title and optional tooltip/subtitle.
UNSET distinguishes an absent value/default from an explicit None.
"""
from enum import IntEnum

from qtpy.QtCore import Qt


UNSET = object()


class InspectorRole(IntEnum):
    KeyRole = int(Qt.ItemDataRole.UserRole) + 1
    TypeRole = KeyRole + 1
    DefaultRole = KeyRole + 2
    BindingRole = KeyRole + 3
    ConnectionRole = KeyRole + 4
    EditorHintsRole = KeyRole + 5
    ErrorRole = KeyRole + 6
