from qtpy.QtWidgets import QCheckBox, QWidget


class LockSwitch(QCheckBox):
    """Checkbox that shows a lock glyph instead of the box, followed by a name."""

    LOCKED = "🔒"       # ASCII alternative: "[#]"🔒
    UNLOCKED = "🔓"     # ASCII alternative: "[ ]"

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = text
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }")
        self.toggled.connect(self._refresh)
        self._refresh()

    def setText(self, text: str) -> None:
        self._name = text
        self._refresh()

    def _refresh(self) -> None:
        glyph = self.LOCKED if self.isChecked() else self.UNLOCKED
        super().setText(f"{glyph} {self._name}")