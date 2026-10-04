from pyflow5.pyflow5_window import PyFlow5Window


from qtpy.QtGui import QColor, QPainter
from qtpy.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleOption,
    QWidget,
)


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
    from qtpy.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    
    app.setStyle(HoverFusionStyle()) # note: without the fusion style, the currect index is not visible at all.
    window = PyFlow5Window(use_session=True)
    window.setWindowTitle("PyFlow5 - DirectionalGraphView5")
    window.show()
    sys.exit(app.exec_())
    