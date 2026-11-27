from qtpy.QtWidgets import QLabel, QWidget
from qtpy.QtGui import QFont

class QHeading(QLabel):
    def __init__(
        self,
        text: str,
        level: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        if not 1 <= level <= 6:
            raise ValueError("Heading level must be between 1 and 6")

        super().__init__(text, parent)

        scales = (2.0, 1.5, 1.25, 1.0, 0.875, 0.75)

        font = self.font()
        font.setBold(True)
        font.setPointSize(round(font.pointSize() * scales[level - 1]))
        self.setFont(font)