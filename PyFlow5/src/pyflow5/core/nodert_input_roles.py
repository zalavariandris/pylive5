"""Roles to describe the properties and metadata of node inputs 
in the runtime.
"""
from enum import IntEnum

from qtpy.QtCore import Qt


class NodeRTInputRole(IntEnum):
    # display the value (as string?)
    DisplayRole = int(Qt.ItemDataRole.DisplayRole)
    # the actual editable value
    EditRole = int(Qt.ItemDataRole.EditRole)
    # placeholder to start custom roles
    UserRole = int(Qt.ItemDataRole.UserRole)

    # The location of the input within the arguments
    #   int if the input is positional, str if it is keyword
    InputLocationRole = UserRole + 1
    # whether the input is using its default value

    IsUsingDefaultRole = UserRole + 2
    # the default value of the input for display
    DefaultValueRole = UserRole + 3
    
    # whether the input has an annotation
    HasAnnotationRole = UserRole + 4
    # the annotation associated with the input
    AnnotationRole = UserRole + 5
    
    # the node connected to this input, should return None if no connection exists
    ConnectionRole = UserRole + 6
