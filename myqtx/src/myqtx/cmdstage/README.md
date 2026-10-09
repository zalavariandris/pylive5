# cmdstage

A persistent visual stage for command-line programs. Use `import stage` for the
short public API; the implementation lives in `myqtx.cmdstage`.

```python
import numpy as np
import stage
from stage import Image, ImageCompare, HTML, Markdown

a = np.zeros((480, 640, 3), dtype=np.uint8)
b = np.full_like(a, 255)

stage.show()  # Start the viewer automatically.
stage.show(ImageCompare(a, b))
input("Press Enter to close the stage...")
stage.close()
```

Importing the module does not start a viewer. The first `show()` starts it;
subsequent calls reuse it. Call `close()` explicitly to stop it. Closing the
window hides it but keeps the server running; `show()` opens it again. After
`close()`, another `show()` starts a fresh viewer. `clear()` and `close()` are
harmless when the viewer is not running.

Exceptions are visible in the terminal and do not automatically close the
viewer. Viewer request failures print their original traceback to stderr and
raise a `RuntimeError` at the calling `show()`.

For independent windows, create separate `Stage` instances with
`from stage import Stage`. They use the same automatic startup and explicit
`close()` lifecycle, without a context manager.

Each `show()` replaces the current content. Repeated updates of the same type
reuse the existing viewer, preserving image zoom, pan, and comparison-slider
position. `show()` returns after the GUI has taken ownership of the submitted
data, so source arrays can then be modified or released. Calls on a stage are
intended to be sequential.

## Display objects

```python
stage.show(Image(data=a))
stage.show(ImageCompare(a, b))
stage.show(HTML("<h1>Results</h1><p>Some <b>formatted text</b>.</p>"))
stage.show(Markdown("# Results\n\nSome **formatted text**."))
stage.clear()
```

- `Image` accepts NumPy images with shape `(H, W)`, `(H, W, 1)`, `(H, W, 3)`, or
  `(H, W, 4)`. Channels are grayscale, RGB, or RGBA. Use `uint8`, or normalized
  `float32`/`float64` values in `[0, 1]` (values outside that range are clipped).
- `ImageCompare` accepts two such arrays with the same width and height. A wipe
  slider shows A on the left and B on the right. Wheel zoom, drag pan, and `F`
  to fit work in both image viewers. Comparison does not resize or independently
  normalize the images.
- `HTML` uses Qt's [supported rich-text HTML subset](https://doc.qt.io/qt-6/richtext-html-subset.html).
  It is not a web browser and does not execute JavaScript.
- `Markdown` uses Qt's Markdown renderer in a read-only text browser.
- Raw arrays retain the image behavior. Strings are plain text; numbers,
  booleans, lists, tuples, dictionaries, and `None` also have text displays.

The payloads are plain dataclasses. Importing `stage` loads `myqtx` and its Qt
imports, but does not create a QApplication or launch a process. The viewer's
QApplication runs in its own process.

Run the interactive demo from the repository root:

```console
python myqtx/examples/cmd_display_demo.py
```

## Custom viewers inside a Qt application

Registration belongs to each `DisplayWidget`, not to `Stage`. The widget installs
its built-in registrations automatically. Register a factory accepting a parent
widget and returning a `DisplayView`; implement `set_data()` to update it:

```python
from dataclasses import dataclass
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget
from myqtx import DisplayView, DisplayWidget

@dataclass
class Measurement:
    value: float

class MeasurementView(DisplayView[Measurement]):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLabel(self)
        QVBoxLayout(self).addWidget(self.label)

    def set_data(self, data: Measurement) -> None:
        self.label.setText(f"{data.value:.2f}")

    def clear(self) -> None:
        self.label.clear()

# Inside an existing QApplication:
display = DisplayWidget()
display.register_viewer(Measurement, MeasurementView)
display.display(Measurement(12.345))
display.show()
```

The exact type takes precedence, followed by registered base classes in Python's
MRO. Registering again replaces the factory on the next `display()` call.
Each registered type's viewer is created lazily and reused. `clear()` releases
its content when hidden; override it when retaining images, arrays, or media.
Validate new data before mutating the current display so a failed update can
preserve the previous one. Image fitting is handled by the canvas itself.

Custom registrations currently work in the Qt application that owns the widget.
The separate command-line GUI uses only the built-in registrations. Custom GUI
setup/loading and arbitrary custom payload codecs are deferred.

## Transport

Commands and typed payload metadata travel over a Qt local socket. NumPy arrays
travel through per-call shared-memory blocks with their shape and dtype. The
receiver copies array data before acknowledging the command, and the sender
always releases its blocks afterward, including on errors. Numeric/boolean
arrays are supported by the transport, with a 1 GiB limit per array; the image
viewers apply the narrower image requirements above. Object and structured
arrays are rejected. No Python objects or widget factories are pickled.

Use Python 3.13+ on POSIX for independent-process shared-memory tracking via
`track=False` in the receiver. On older POSIX Python versions, resource-tracker
warnings may occur at shutdown. Windows uses handle lifetime for shared memory.

`from myqtx import cmdstage as stage` provides the same API and shares the same
default viewer as `import stage`.
