from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from qtpy.QtCore import QSize, Qt
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from myqtx.cmdstage.data import HTML, Image, ImageCompare, Markdown

from .displayviews import (
    DisplayView, HTMLView, ImageCompareView, ImageView, MarkdownView, TextView,
)


ViewerFactory = Callable[[QWidget | None], DisplayView[Any]]


@dataclass
class _CachedView:
    factory: ViewerFactory
    view: DisplayView[Any]


class DisplayWidget(QWidget):
    """Choose a registered viewer and reuse it for subsequent data updates."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._registry: dict[type, ViewerFactory] = {}
        self._views: dict[type, _CachedView] = {}
        layout = QVBoxLayout(self)
        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack)
        self._empty = QWidget(self._stack)
        self._stack.addWidget(self._empty)

        for datatype in (Image, np.ndarray, QImage, QPixmap):
            self.register_viewer(datatype, ImageView)
        self.register_viewer(ImageCompare, ImageCompareView)
        self.register_viewer(HTML, HTMLView)
        self.register_viewer(Markdown, MarkdownView)
        self.register_viewer(object, TextView)
        self.display("Viewer")

    def register_viewer(self, datatype: type, factory: ViewerFactory) -> None:
        """Register or replace a viewer for this instance, effective on next display.

        A factory accepts a parent widget and returns a DisplayView. Lookup uses
        the displayed object's Python MRO: exact type, then nearest base class.
        """
        if not isinstance(datatype, type):
            raise TypeError("datatype must be a Python type")
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._registry[datatype] = factory

    @property
    def current_viewer(self) -> DisplayView[Any] | None:
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, DisplayView) else None

    def display(self, data: object) -> None:
        datatype = next(base for base in type(data).__mro__ if base in self._registry)
        factory = self._registry[datatype]
        cached = self._views.get(datatype)
        if cached is not None and cached.factory is factory:
            view = cached.view
            view.set_data(data)
        else:
            view = self._create_view(factory, data)
            self._stack.addWidget(view)
            self._views[datatype] = _CachedView(factory, view)

        previous = self.current_viewer
        self._stack.setCurrentWidget(view)
        self.setFocusProxy(view)
        if previous is not None and previous is not view:
            previous.clear()
        if cached is not None and cached.view is not view:
            self._remove_view(cached.view)

    def _create_view(self, factory: ViewerFactory, data: object) -> DisplayView[Any]:
        view = factory(self._stack)
        if not isinstance(view, DisplayView):
            if isinstance(view, QWidget):
                self._remove_view(view)
            raise TypeError("Viewer factories must return a DisplayView")
        try:
            view.set_data(data)
        except BaseException:
            self._remove_view(view)
            raise
        return view

    def _remove_view(self, view: QWidget) -> None:
        self._stack.removeWidget(view)
        view.setParent(None)
        view.deleteLater()

    def clear(self) -> None:
        for cached in self._views.values():
            cached.view.clear()
        self._stack.setCurrentWidget(self._empty)
        self.setFocusProxy(None)

    def minimumSizeHint(self) -> QSize:
        return QSize(320, 240)

    def sizeHint(self) -> QSize:
        return QSize(320, 240)
