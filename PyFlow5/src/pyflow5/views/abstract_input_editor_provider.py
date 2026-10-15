"""Adapters between editor widgets and Python input values."""

from abc import ABCMeta, abstractmethod
from typing import Any

from qtpy.QtCore import QModelIndex, QObject, Signal
from qtpy.QtWidgets import QStyleOptionViewItem, QWidget


class _AbstractQObjectMeta(type(QObject), ABCMeta):
    pass


class AbstractInputEditorProvider(QObject, metaclass=_AbstractQObjectMeta):
    """Create editors and adapt their values without accessing the model.

    Return None from createEditor for unsupported inputs. Standard Qt editors
    retain their normal Enter/focus-loss commits. Optionally emit commitData(editor)
    to request an immediate commit. The router suppresses commits while loading
    values and supplies the input's default, or None when no value is available.
    QLineEdit defaults are shown as placeholders and receive None instead.

    Override the value methods when a widget's user property does not match the
    computation's Python type. Widgets without a user property can be used too,
    by overriding both methods.
    """

    commitData = Signal(QWidget)

    @abstractmethod
    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget | None:
        """Create an editor for this input, or decline with None."""
        raise NotImplementedError

    def setEditorValue(self, editor: QWidget, value: Any) -> None:
        """Display a Python value; accept None for an input without a value."""
        value_property = editor.metaObject().userProperty()
        if not value_property.isValid() or not value_property.write(editor, value):
            raise TypeError(f"Failed to set value '{value}' on the user property of {type(editor).__name__}")

    def editorValue(self, editor: QWidget) -> Any:
        """Return the Python value to store in the computation's input."""
        value_property = editor.metaObject().userProperty()
        if not value_property.isValid():
            raise TypeError(f"{type(editor).__name__} has no user property")
        return value_property.read(editor)
