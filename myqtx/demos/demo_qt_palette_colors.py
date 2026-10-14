
from qtpy.QtCore import Qt
from qtpy.QtGui import QColor, QPixmap, QIcon
from qtpy.QtWidgets import (
    QApplication,
    QWidget,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QListWidgetItem
)


class QtPaletteColorsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Qt Palette Colors")

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter color roles...")
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.colors_list = QListWidget(self)
        self.colors_list.setUniformItemSizes(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.colors_list)

        self._populate()

    def _color_role_names(self) -> list[str]:
        from qtpy.QtGui import QPalette
        enum_cls = getattr(QPalette, "ColorRole", None)
        if enum_cls is None:
            return []
        return sorted(name for name in dir(enum_cls) if not name.startswith("_") and not name.islower())

    def _populate(self) -> None:
        self.colors_list.clear()
        from qtpy.QtGui import QPalette
        palette = QApplication.palette()
        enum_cls = getattr(QPalette, "ColorRole", None)
        if enum_cls is None:
            return

        for name in self._color_role_names():
            role = getattr(enum_cls, name, None)
            if role is None:
                continue
            color = palette.color(role)
            pixmap = QPixmap(32, 32)
            pixmap.fill(color)
            icon = QIcon(pixmap)
            item = QListWidgetItem()
            item.setIcon(icon)
            item.setText(f"{name}: {color.name()}")
            item.setData(Qt.UserRole, name.lower())
            self.colors_list.addItem(item)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.colors_list.count()):
            item = self.colors_list.item(i)
            haystack = str(item.data(Qt.UserRole) or "")
            item.setHidden(bool(needle) and needle not in haystack)


if __name__ == "__main__":
    app = QApplication([])
    window = QtPaletteColorsWidget()
    window.show()
    app.exec()