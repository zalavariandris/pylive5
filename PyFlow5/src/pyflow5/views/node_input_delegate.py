from functools import partial
import inspect
from pathlib import Path
import traceback
from typing import ClassVar
from uuid import uuid4

from qtpy.QtCore import (
    Property,
    QAbstractItemModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from qtpy.QtGui import QPaintEvent, QPainter
from qtpy.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

import pygraphrt2 as rt2

from ..core.input_roles import InputDataRole
from .abstract_input_editor_provider import AbstractInputEditorProvider

# Custom Widgets for the NodesInspector
class InputClearButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("✖", parent)
        self.setToolTip("Clear input")
        self.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; padding: 0; margin: 0;
            }
            QPushButton:hover {
                color: palette(Highlight);
            }
        """)

        # make it a fixed size matching an M character
        fm = self.fontMetrics()
        m_width = fm.horizontalAdvance("M")
        self.setFixedSize(m_width, m_width)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        m_width = fm.horizontalAdvance("M")
        return QSize(m_width, m_width)

    def maximumSizeHint(self) -> QSize:
        fm = self.fontMetrics()
        m_width = fm.horizontalAdvance("M")
        return QSize(m_width, m_width)

    def minimumSizeHint(self) -> QSize:
        fm = self.fontMetrics()
        m_width = fm.horizontalAdvance("M")
        return QSize(m_width, m_width)


class InputLabelWidget(QWidget):
    def __init__(self, label_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(label_text, self)
        self._layout.addWidget(self._label)

        self._clearbtn = InputClearButton(self)
        self._clearbtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._layout.addSpacing(5)
        self._layout.addWidget(self._clearbtn)
        self._clearbtn.pressed.connect(self.clearRequested.emit)

    # def paintEvent(self, event: QPaintEvent) -> None:
    #     # paint bg
    #     painter = QPainter(self)
    #     painter.drawRect(self.rect())
    #     super().paintEvent(event)

    # define text as qt user prop
    def setText(self, text: str) -> None:
        self._label.setText(text)

    def getText(self) -> str:
        return self._label.text()

    text = Property(
        str,
        getText,
        setText,
        user=True
    )

    clearRequested = Signal()

# Delegates for the NodesInspector
class NodeInputLabelDelegate(QStyledItemDelegate):
    def createEditor(
        self, parent: QWidget | None, option: QStyleOptionViewItem, index: QModelIndex,
    ) -> QWidget:
        data_text = index.data(Qt.ItemDataRole.DisplayRole)
        input_label_widget = InputLabelWidget(data_text, parent)
        persistent_index = QPersistentModelIndex(index)

        def clear_input() -> None:
            if persistent_index.isValid():
                label_index = QModelIndex(persistent_index)
                label_index.model().setData(label_index.siblingAtColumn(1), rt2.ParameterData.EMPTY)

        input_label_widget.clearRequested.connect(clear_input)
        # expland the widget to fill the available space
        input_label_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return input_label_widget


class NodeInputFieldDelegate(QStyledItemDelegate):
    """Route editor creation and value conversion to registered providers."""

    _provider_classes: ClassVar[list[type[AbstractInputEditorProvider]]] = []
    _plugins_loaded: ClassVar[bool] = False

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._providers: list[AbstractInputEditorProvider] = []
        self._editor_providers: dict[QWidget, AbstractInputEditorProvider] = {}
        self._loaded_values: dict[QWidget, object] = {}
        self._updating_editors: set[QWidget] = set()
        self._committing_editors: set[QWidget] = set()

        if not NodeInputFieldDelegate._plugins_loaded:
            self._discover_providers()
            NodeInputFieldDelegate._plugins_loaded = True

        for provider_class in self._provider_classes:
            try:
                provider = provider_class(self)
                provider.commitData.connect(self.commitData.emit)
                self._providers.append(provider)
            except Exception:
                plugin_path = Path(inspect.getfile(provider_class))
                QTimer.singleShot(
                    0,
                    partial(self._show_plugin_error, plugin_path, traceback.format_exc()),
                )

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(300, 30)  # Example size, adjust as needed

    def _discover_providers(self) -> None:
        """Load shipped sidecars in a stable order during startup only."""
        plugin_directory = Path(__file__).parent.parent / "input_editor_plugins"
        # Specialized providers see metadata before the built-in type fallback.
        plugin_paths = sorted(
            plugin_directory.glob("*.editors.py"),
            key=lambda path: (path.name == "builtins.editors.py", path.name),
        )
        for path in plugin_paths:
            if not path.is_file():
                continue

            previous_providers = self._provider_classes.copy()
            try:
                self._load_plugin_from_file(path)
            except Exception:
                # A failing sidecar may already have registered some classes.
                self._provider_classes[:] = previous_providers
                QTimer.singleShot(
                    0,
                    partial(self._show_plugin_error, path, traceback.format_exc()),
                )

    @classmethod
    def register_input_editor_provider(
        cls, provider_class: type[AbstractInputEditorProvider],
    ) -> None:
        """Register an editor provider class to instantiate for each new router."""
        if not isinstance(provider_class, type) or not issubclass(
            provider_class, AbstractInputEditorProvider
        ):
            raise TypeError("Expected an InputEditorProvider subclass")

        if provider_class not in cls._provider_classes:
            cls._provider_classes.append(provider_class)

    def _show_plugin_error(self, path: Path, details: str) -> None:
        parent = self.parent()
        dialog = QMessageBox(
            parent if isinstance(parent, QWidget) else None
        )
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Editor plugin could not be loaded")
        dialog.setText(f"Could not load {path.name}.")
        dialog.setInformativeText(
            "The application will continue without this editor plugin."
        )
        dialog.setDetailedText(details)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    def _load_plugin_from_file(self, path: Path) -> None:
        import importlib.util
        import sys
        path = Path(path)
        module_name = f"_pyflow_editor_{uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load editor module: {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as err:
            del sys.modules[module_name]
            raise ImportError(f"Cannot load editor module: {path}") from err

    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget:
        connected_node = index.data(InputDataRole.ConnectionRole)
        
        editor:QWidget | None = None

        # if input is connected, show that.
        if connected_node is not None:
            editor = QLineEdit(parent)
            editor.setText(f"-> {connected_node}")
            editor.setReadOnly(True)
            editor.destroyed.connect(lambda: self._forget_editor(editor))
            return editor

        # Route future value transfers to the provider that created the editor.
        for provider in self._providers:
            editor = provider.createEditor(parent, option, index)
            try:
                editor.setReadOnly(False)
            except AttributeError:
                pass
            if editor is not None:
                self._editor_providers[editor] = provider
                editor.destroyed.connect(lambda: self._forget_editor(editor))
                return editor

        editor = QLineEdit(parent)
        editor.destroyed.connect(lambda: self._forget_editor(editor))
        return editor

    def _forget_editor(self, editor: QWidget) -> None:
        self._editor_providers.pop(editor, None)
        self._loaded_values.pop(editor, None)

    def _editor_value(self, editor: QWidget) -> object:
        provider = self._editor_providers.get(editor)
        if provider is not None:
            return provider.editorValue(editor)
        return editor.metaObject().userProperty().read(editor)

    def setModelData(
        self, editor: QWidget|None, model: QAbstractItemModel|None, index: QModelIndex,
    ) -> None:
        # Signals emitted while loading an editor must not write back to the model.
        if editor is None or model is None or editor in self._updating_editors:
            return

        if index.data(InputDataRole.ConnectionRole) is not None:
            return

        value = self._editor_value(editor)
        if editor in self._loaded_values:
            previous = self._loaded_values[editor]
            if value is previous:
                return
            try:
                if value == previous:
                    return
            except (TypeError, ValueError):
                pass  # Some custom values do not support scalar equality.
        self._committing_editors.add(editor)
        try:
            if model.setData(index, value, Qt.ItemDataRole.EditRole):
                self._loaded_values[editor] = self._editor_value(editor)
        finally:
            self._committing_editors.discard(editor)
        
    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if editor is None or editor in self._updating_editors:
            return

        # Load a new editor once, even if the view has already focused it.
        focus = QApplication.focusWidget()
        if editor in self._loaded_values and (
            focus is editor or (focus is not None and editor.isAncestorOf(focus))
        ):
            return
        if editor in self._committing_editors:
            return

        self._updating_editors.add(editor)
        try:
            connected_node = index.data(InputDataRole.ConnectionRole)
            if isinstance(editor, QLineEdit):
                editor.setReadOnly(connected_node is not None)
                if connected_node is not None:
                    editor.setText(f"-> {connected_node}")
                    return

            is_using_default = bool(index.data(InputDataRole.IsUsingDefaultRole))
            effect = editor.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(editor)
                editor.setGraphicsEffect(effect)
            effect.setOpacity(0.5 if is_using_default else 1.0)

            value = index.data(Qt.ItemDataRole.EditRole)
            provider = self._editor_providers.get(editor)
            if provider is None:
                super().setEditorData(editor, index)
                return

            try:
                provider.setEditorValue(editor, value)
            except Exception as e:
                print(f"Error setting editor value: {e}")
        finally:
            self._updating_editors.remove(editor)
            self._loaded_values[editor] = self._editor_value(editor)

    # def initStyleOption(
    #     self, option: QStyleOptionViewItem | None, index: QModelIndex
    # ) -> None:
    #     if option is None:
    #         return
    #     super().initStyleOption(option, index)

    #     if index.data(NodeRTInputRole.IsUsingDefaultRole):
    #         color = option.palette.color(
    #             QPalette.ColorGroup.Disabled,
    #             QPalette.ColorRole.Text,
    #         )
    #         option.font.setItalic(True)
    #         for group in (
    #             QPalette.ColorGroup.Active,
    #             QPalette.ColorGroup.Inactive,
    #         ):
    #             option.palette.setColor(group, QPalette.ColorRole.Text, color)
    #             option.palette.setColor(
    #                 group, QPalette.ColorRole.HighlightedText, color
    #             )
