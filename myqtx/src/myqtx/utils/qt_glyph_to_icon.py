from typing import (
    Literal,
    List,
    Mapping,
    Any,
    Self,
    MutableMapping,
)

from qtpy.QtCore import (
    Qt
)

from qtpy.QtGui import (
    QColor, QFont, QIcon, QPainter, QPixmap, QFontMetrics
)

from qtpy.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QMessageBox,
    QTreeView,
    QTextEdit,
    QStyle,
)

def make_glyph_icon(glyph, size: int = 32, color: QColor|None = None, font:QFont|None=None) -> QIcon:
    """Convert a single-character glyph to a QIcon."""

    # create transparent pixmap
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    # set color
    if color is None:
        color = QApplication.palette().text().color()
        # print(f"make glyph icon: Using default text color: {color.name()}")
    painter.setPen(color)

    # set font
    if font is None:
        font = QApplication.font()
    font.setPixelSize(size - 4)  # Adjust font size to fit the pixmap
    painter.setFont(font)
            
    # Center the character in the pixmap
    fm = QFontMetrics(painter.font())
    char_rect = fm.boundingRect(glyph)
    
    # Calculate center position
    x = (size - char_rect.width()) / 2
    y = (size + fm.ascent() - fm.descent()) / 2
    
    painter.drawText(int(x), int(y), glyph)
    painter.end()

    return QIcon(pixmap)

if __name__ == "__main__":
    app = QApplication([])
    glyphs = {
        "package": make_glyph_icon("⛶"),
        "package_module": make_glyph_icon("⛶📦"),
        "module": make_glyph_icon("📦"),
        "function": make_glyph_icon("ƒ"),
        "class": make_glyph_icon("◉"),
    }
    window = QWidget()
    layout = QVBoxLayout(window)
    for name, icon in glyphs.items():
        button = QPushButton(name)
        button.setIcon(icon)
        layout.addWidget(button)
    window.show()
    app.exec()