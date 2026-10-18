import numpy as np
from qtpy.QtCore import QSize, Qt, Property, Signal
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QLabel, QTextBrowser, QVBoxLayout, QWidget, QStackedWidget
)

# from .display_data import HTML, Image, ImageCompare, Markdown

from .imagecanvas import ImageCanvas
from .responsive_label import ResponsiveLabel
from .image_compare_widget import ImageCompareWidget


class DisplayWidget(QWidget):
    """Choose a registered viewer and reuse it for subsequent data updates."""
    """Data objects describing content to display; no Qt objects are created here."""

    from dataclasses import dataclass

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import numpy as np


    @dataclass
    class Image:
        data: np.ndarray
        channel_axis: int | None = None


    @dataclass
    class HTML:
        data: str


    @dataclass
    class Markdown:
        data: str


    @dataclass
    class ImageCompare:
        """Two images with a wipe slider; B is stretched to fit the dimensions of A."""
        a: np.ndarray
        b: np.ndarray
        channel_axis: int | None = None

    def __init__(self, parent: QWidget | None = None, *, channel_axis: int = -1) -> None:
        super().__init__(parent)
        self._channel_axis = channel_axis
        # setup widget
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("Display Widget")

        # private members
        self._cached_data: object | None = None
        self._view_for_data:    dict[type, QWidget] = {}

        # layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack)
        self._empty = QWidget(self._stack)
        self._stack.addWidget(self._empty)

        self.display("Viewer")

    def _create_editor(self, data: object) -> QWidget:
        """Create an editor for the given data, if possible."""
        match data:
            case DisplayWidget.Image() | np.ndarray() | QImage() | QPixmap():
                print("create image canvas")
                return ImageCanvas(parent=self._stack)
            
            case DisplayWidget.ImageCompare():
                return ImageCompareWidget(parent=self._stack)
            
            case DisplayWidget.HTML():
                return QTextBrowser(parent=self._stack)
            
            case DisplayWidget.Markdown():
                return QTextBrowser(parent=self._stack)

            case Exception():
                label = QLabel("An exception occurred", parent=self._stack)
                label.setStyleSheet("{color: red; font-weight: bold;}")
                return label

            case str():
                return ResponsiveLabel(parent=self._stack)
            
            case _:
                return QLabel("No suitable editor found")

    def _set_editor_data(self, editor: QWidget, data: object) -> None:
        """Set the data for the given editor view."""
        match data, editor:
            case DisplayWidget.Image(), ImageCanvas() as image_canvas:
                axis = self._channel_axis if data.channel_axis is None else data.channel_axis
                image_canvas.set_image(data.data, channel_axis=axis)

            case np.ndarray()|QImage()|QPixmap(), ImageCanvas() as image_canvas:
                image_canvas.set_image(data, channel_axis=self._channel_axis)

            case DisplayWidget.ImageCompare(), ImageCompareWidget() as image_compare_view:
                axis = self._channel_axis if data.channel_axis is None else data.channel_axis
                image_compare_view.set_images(data.a, data.b, channel_axis=axis)

            case DisplayWidget.HTML(), QTextBrowser() as html_browser:
                html_browser.setHtml(data.data)

            case DisplayWidget.Markdown(), QTextBrowser() as md_browser:
                md_browser.setMarkdown(data.data)

            case Exception(), QLabel() as text_view:
                text_view.setText(str(data))
                text_view.setStyleSheet("color: red;")

            case str(), ResponsiveLabel() as text_view:
                text_view.setText(data)

            case _, QLabel() as text_view:
                text_view.setText(str(data))

            case _, QWidget():
                # get qt user property from meta
                meta = editor.metaObject()
                if meta is not None:
                    userprop = meta.userProperty()
                    if userprop.isValid():
                        userprop.write(editor, data)

    def display(self, data: object) -> None:
        if type(data) not in self._view_for_data:
            editor = self._create_editor(data)
            self._view_for_data[type(data)] = editor
            self._stack.addWidget(editor)

        editor = self._view_for_data[type(data)]
        self._set_editor_data(editor, data)
        # clear() may have hidden this editor even when the data type is unchanged.
        self._stack.setCurrentWidget(editor)
        self._cached_data = data

    def clear(self) -> None:
        self._stack.setCurrentWidget(self._empty)
        self.setFocusProxy(None)

    def minimumSizeHint(self) -> QSize:
        return QSize(320, 240)

    def sizeHint(self) -> QSize:
        return QSize(320, 240)
