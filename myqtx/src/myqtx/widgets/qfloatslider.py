from math import ceil, isfinite

from qtpy.QtCore import Property, QSignalBlocker, Qt, Signal
from qtpy.QtWidgets import QHBoxLayout, QSlider, QWidget


class QFloatSlider(QWidget):
    """A bounded float slider with evenly spaced, inclusive endpoints."""

    valueChanged = Signal(float)

    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Orientation.Horizontal,
        parent: QWidget | None = None,
        *,
        minimum: float = 0.0,
        maximum: float = 1.0,
        step: float = 0.01,
    ) -> None:
        super().__init__(parent)
        self._minimum = 0.0
        self._maximum = 1.0
        self._steps = 100
        self._step = 0.01
        self._slider = QSlider(orientation, self)
        self._slider.setRange(0, self._steps)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._slider)
        self._slider.valueChanged.connect(self._emit_value)
        self.setRange(minimum, maximum, step=step)

    def _emit_value(self, position: int) -> None:
        self.valueChanged.emit(self.value())

    def minimum(self) -> float:
        return self._minimum

    def maximum(self) -> float:
        return self._maximum

    def setRange(
        self, minimum: float, maximum: float, *, step: float | None = None,
    ) -> None:
        """Set bounds and maximum spacing, preserving the value when possible."""
        step = self._step if step is None else step
        if not all(isfinite(x) for x in (minimum, maximum, step)):
            raise ValueError("Slider settings must be finite")
        if minimum >= maximum or step <= 0:
            raise ValueError("Expected minimum < maximum and step > 0")
        intervals = (maximum - minimum) / step
        if not isfinite(intervals) or intervals > 2_147_483_647:
            raise ValueError("Slider range requires too many steps")

        old_value = self.value()
        with QSignalBlocker(self._slider):
            self._minimum = float(minimum)
            self._maximum = float(maximum)
            self._step = step
            self._steps = max(1, ceil(intervals))
            self._slider.setRange(0, self._steps)
            self.setValue(old_value)
        if self.value() != old_value:
            self.valueChanged.emit(self.value())

    def value(self) -> float:
        if self._slider.value() == self._steps:
            return self._maximum
        fraction = self._slider.value() / self._steps
        return self._minimum + fraction * (self._maximum - self._minimum)

    def setValue(self, value: float) -> None:
        if not isfinite(value):
            raise ValueError("Slider value must be finite")
        value = min(self._maximum, max(self._minimum, value))
        fraction = (value - self._minimum) / (self._maximum - self._minimum)
        self._slider.setValue(round(fraction * self._steps))

    floatValue = Property(float, value, setValue, notify=valueChanged, user=True)


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    window = QWidget()
    main_layout = QVBoxLayout()
    window.setLayout(main_layout)
    path_edit = QFloatSlider()

    main_layout.addWidget(path_edit)
    window.show()
    app.exec()
