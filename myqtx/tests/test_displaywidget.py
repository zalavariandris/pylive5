import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QPoint, QPointF, Qt
from qtpy.QtGui import QImage, QPixmap, QWheelEvent
from qtpy.QtWidgets import QApplication, QLabel

from myqtx.displaywidget import DisplayWidget
from myqtx.imagecanvas import ImageCanvas


@pytest.fixture
def display(qtbot: QtBot) -> DisplayWidget:
    widget = DisplayWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    QApplication.processEvents()
    return widget


@pytest.mark.parametrize(
    "data, expected",
    [
        (np.full((5, 7), 64, dtype=np.uint8), (64, 64, 64, 255)),
        (np.full((5, 7, 1), 64, dtype=np.uint8), (64, 64, 64, 255)),
        (np.tile(np.array([10, 20, 30], dtype=np.uint8), (5, 7, 1)), (10, 20, 30, 255)),
        (np.tile(np.array([10, 20, 30, 255], dtype=np.uint8), (5, 7, 1)), (10, 20, 30, 255)),
        (np.tile(np.array([-1, 0.5, 2], dtype=np.float32), (5, 7, 1)), (0, 127, 255, 255)),
        (np.tile(np.array([-1, 0.5, 2], dtype=np.float64), (5, 7, 1)), (0, 127, 255, 255)),
    ],
)
def test_array_pixels_survive_source_changes(
    display: DisplayWidget, data: np.ndarray, expected: tuple[int, int, int, int],
) -> None:
    # Reverse columns to also exercise non-contiguous inputs and odd row widths.
    source = data[:, ::-1].copy()[:, ::-1]
    display.display(source)
    source[:] = 0
    canvas = display.findChild(ImageCanvas)
    assert canvas is not None and canvas.isVisible()
    rendered = canvas.item.pixmap().toImage()
    assert (rendered.width(), rendered.height()) == (7, 5)
    assert rendered.pixelColor(6, 4).getRgb() == expected


@pytest.mark.parametrize("use_pixmap", [False, True])
def test_qt_images_are_displayed(display: DisplayWidget, use_pixmap: bool) -> None:
    image = QImage(13, 7, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.red)
    display.display(QPixmap.fromImage(image) if use_pixmap else image)
    image.fill(Qt.GlobalColor.blue)
    canvas = display.findChild(ImageCanvas)
    assert canvas is not None and canvas.isVisible()
    assert canvas.item.pixmap().toImage().pixelColor(12, 6) == Qt.GlobalColor.red


@pytest.mark.parametrize(
    "value, expected",
    [("hello", "hello"), (ValueError("bad input"), "Exception: bad input"), (None, "None")],
)
def test_switching_to_text_releases_image(
    display: DisplayWidget, value: object, expected: str,
) -> None:
    display.display(np.zeros((600, 900, 3), dtype=np.uint8))
    canvas = display.findChild(ImageCanvas)
    assert canvas is not None
    canvas.scale(2, 2)

    display.display(value)
    label = display.findChild(QLabel)
    assert label is not None and label.isVisible()
    assert label.text() == expected
    assert not canvas.isVisible()
    assert canvas.item.pixmap().isNull()

    display.display(np.zeros((600, 900, 3), dtype=np.uint8))
    assert canvas.isVisible()
    assert not label.isVisible()
    assert 0 < canvas.transform().m11() < 1


def test_zoom_survives_new_frames_and_fit_restores_view(
    display: DisplayWidget, qtbot: QtBot,
) -> None:
    display.display(np.zeros((600, 900, 3), dtype=np.uint8))
    QApplication.processEvents()
    canvas = display.findChild(ImageCanvas)
    assert canvas is not None
    assert QApplication.focusWidget() is canvas
    fitted_scale = canvas.transform().m11()
    position = canvas.viewport().rect().center()
    event = QWheelEvent(
        QPointF(position), QPointF(canvas.viewport().mapToGlobal(position)),
        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(canvas.viewport(), event)
    zoomed_scale = canvas.transform().m11()
    assert zoomed_scale == pytest.approx(fitted_scale * 1.25)

    display.display(np.full((600, 900, 3), 127, dtype=np.uint8))
    assert canvas.transform().m11() == pytest.approx(zoomed_scale)

    qtbot.keyClick(canvas, Qt.Key.Key_F)
    assert canvas.transform().m11() == pytest.approx(fitted_scale)


def test_first_image_fits_after_hidden_widget_is_shown(qtbot: QtBot) -> None:
    widget = DisplayWidget()
    qtbot.addWidget(widget)
    widget.display(np.zeros((900, 1600, 3), dtype=np.uint8))
    widget.resize(640, 360)
    widget.show()
    QApplication.processEvents()
    canvas = widget.findChild(ImageCanvas)
    assert canvas is not None
    viewport = canvas.viewport().rect()
    ideal_scale = min(viewport.width() / 1600, viewport.height() / 900)
    assert 0.9 * ideal_scale <= canvas.transform().m11() <= ideal_scale


def test_clear_resets_image_and_text(display: DisplayWidget) -> None:
    display.display(np.zeros((600, 900, 3), dtype=np.uint8))
    canvas = display.findChild(ImageCanvas)
    label = display.findChild(QLabel)
    assert canvas is not None and label is not None
    canvas.scale(2, 2)
    display.clear()
    assert canvas.item.pixmap().isNull()
    assert canvas.transform().isIdentity()
    assert display.current_viewer is None
    assert not canvas.isVisible() and label.text() == ""

    display.display("hello")
    display.clear()
    assert label.text() == ""

    display.display(np.zeros((600, 900, 3), dtype=np.uint8))
    assert canvas.isVisible()
    assert 0 < canvas.transform().m11() < 1


@pytest.mark.parametrize(
    "data, error",
    [
        (np.zeros(3, dtype=np.uint8), ValueError),
        (np.zeros((5, 7, 2), dtype=np.uint8), ValueError),
        (np.zeros((0, 7, 3), dtype=np.uint8), ValueError),
        (np.zeros((5, 7, 3), dtype=np.int32), TypeError),
    ],
)
def test_invalid_array_keeps_previous_display(
    display: DisplayWidget, data: np.ndarray, error: type[Exception],
) -> None:
    display.display("previous result")
    with pytest.raises(error):
        display.display(data)
    label = display.findChild(QLabel)
    assert label is not None and label.isVisible()
    assert label.text() == "previous result"
