import os
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
from qtpy.QtGui import QAction, QCloseEvent, QColor, QPainter
from qtpy.QtWidgets import (
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProxyStyle,
    QStyle,
    QStyleOption,
    QWidget,
    QFileDialog
)

from .models.pyflow5_document import PyFlowDocument
from .views.pyflow5_documentwindow import PyFlow5DocumentWindow
from .app_window import AppWindow

class HoverFusionStyle(QProxyStyle):
    def __init__(self) -> None:
        super().__init__("Fusion")

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        super().drawPrimitive(element, option, painter, widget)

        if element in {
            QStyle.PrimitiveElement.PE_PanelItemViewItem, 
            # QStyle.PrimitiveElement.CE_ItemViewItem
        }:

            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            selected = bool(option.state & QStyle.StateFlag.State_Selected)

            if hovered and not selected:
                color = QColor(option.palette.highlight().color())
                color.setAlpha(80)
                painter.fillRect(option.rect, color)



if __name__ == "__main__":
    try:
        import pytracy
        import sys
        pytracy.set_filtering_mode(True, False, False)
        pytracy.enable_tracing(True)
        print("Tracing enabled")
        print("Python profile callback:", sys.getprofile())
    except ImportError:
        print("pytracy not available")

    from qtpy.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    app.setStyle(HoverFusionStyle()) # note: without the fusion style, the currect index is not visible at all.

    document_window = AppWindow()
    document_window.show()
    sys.exit(app.exec())
