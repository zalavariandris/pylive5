from qtpy.QtCore import (
    Qt
)
from qtpy.QtGui import (
    QIcon
)
from qtpy.QtWidgets import (
    QApplication,
    QStyle,
    QWidget,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QListWidgetItem
) 

class QtBuiltinIconsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Qt Builtin Icons")

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter icon names...")
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.icons_list = QListWidget(self)
        self.icons_list.setUniformItemSizes(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.icons_list)

        self._populate()

    def _standard_pixmap_names(self) -> list[str]:
        enum_cls = getattr(QStyle, "StandardPixmap", None)
        if enum_cls is None:
            return []
        return sorted(name for name in dir(enum_cls) if name.startswith("SP_"))

    def _populate(self) -> None:
        self.icons_list.clear()
        style = QApplication.style()
        if style is None:
            return

        enum_cls = getattr(QStyle, "StandardPixmap", None)
        if enum_cls is None:
            return

        for name in self._standard_pixmap_names():
            pixmap_enum = getattr(enum_cls, name, None)
            if pixmap_enum is None:
                continue
            icon = style.standardIcon(pixmap_enum)
            item = QListWidgetItem(icon, name)
            item.setData(Qt.UserRole, name.lower())
            self.icons_list.addItem(item)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.icons_list.count()):
            item = self.icons_list.item(i)
            haystack = str(item.data(Qt.UserRole) or "")
            item.setHidden(bool(needle) and needle not in haystack)


if __name__ == "__main__":
    app = QApplication([])
    window = QtBuiltinIconsWidget()
    window.show()
    app.exec()