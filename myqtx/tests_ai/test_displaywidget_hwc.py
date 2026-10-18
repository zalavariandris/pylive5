import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtWidgets import QLabel

from myqtx.widgets.displaywidget import DisplayWidget
from myqtx.widgets.imagecanvas import ImageCanvas


@pytest.mark.parametrize("dtype", [np.float32, np.uint8])
def test_hwc_image_pixels_and_redisplay_after_clear(qtbot: QtBot, dtype: type) -> None:
    image = np.zeros((3, 5, 4), dtype=dtype)
    if dtype is np.float32:
        image[1, 2] = (0.25, 0.5, 0.75, 1.0)
        expected = (63, 127, 191, 255)
    else:
        image[1, 2] = (10, 20, 30, 255)
        expected = (10, 20, 30, 255)

    display = DisplayWidget()
    qtbot.addWidget(display)
    display.display(image)
    canvas = display._stack.currentWidget()
    assert isinstance(canvas, ImageCanvas)
    assert canvas.item.boundingRect().width() == 5
    assert canvas.item.boundingRect().height() == 3
    assert canvas.item._image.pixelColor(2, 1).getRgb() == expected

    display.clear()
    assert display._stack.currentWidget() is display._empty
    display.display(image)
    assert display._stack.currentWidget() is canvas
    assert canvas.item._image.pixelColor(2, 1).getRgb() == expected


def test_same_error_type_reappears_after_clear(qtbot: QtBot) -> None:
    display = DisplayWidget()
    qtbot.addWidget(display)
    display.display(ValueError("first error"))
    label = display._stack.currentWidget()
    assert isinstance(label, QLabel)
    display.clear()
    display.display(ValueError("next error"))
    assert display._stack.currentWidget() is label
    assert label.text() == "next error"


def test_rejected_image_does_not_hide_previous_display(qtbot: QtBot) -> None:
    display = DisplayWidget()
    qtbot.addWidget(display)
    display.display("previous result")
    previous = display._stack.currentWidget()
    with pytest.raises(ValueError):
        display.display(np.zeros((3, 5, 2), dtype=np.float32))
    assert display._stack.currentWidget() is previous
    assert display._cached_data == "previous result"
