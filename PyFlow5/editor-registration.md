# Registering input editors

PyFlow's form inspector and Node Tree share `window.editor_registry`.
Register a factory with `register_editor(datatype, factory)` to add an editor or
replace an existing one. Registrations belong to that registry instance.

Default editors:

| Python datatype | Qt widget |
| --- | --- |
| `str` | `QLineEdit` |
| `int` | `QSpinBox` |
| `float` | `QDoubleSpinBox` |
| `bool` | `QCheckBox` |
| `enum.Enum` subclasses | `QComboBox` showing member names |
| `pathlib.Path` subclasses | `QLineEdit` |

The numeric editors retain the existing range of ±1,000,000; the float editor
uses three decimal places. A registration can supply different settings.
Unsupported types appear as read-only text. Clear buttons remain available.

Factories receive the actual Python datatype and a parent widget. They return
an `Editor` containing a widget, a value getter, a value setter, and a change
signal. The setter must accept `None` for an input without a value or default.
The getter returns the Python value to store in the model.

Defaults use the widget property `usingDefault`, styled with dim, italic text.
String and path editors show defaults as placeholders; other controls display
their default values. Checkboxes also show a “Default” label. Explicit values
use normal styling, even if equal to the default. Custom editors may provide an
optional `set_default` callback on `Editor` for their own default presentation;
otherwise the delegate uses `set_value`. Both callbacks run without committing
changes. `set_value` should undo any presentation applied by `set_default`.

```python
from dataclasses import dataclass

from qtpy.QtWidgets import QSpinBox, QWidget

from myqtx import Editor


@dataclass
class Reading:
    value: int


def reading_editor(
    datatype: type[Reading], parent: QWidget | None,
) -> Editor[Reading]:
    widget = QSpinBox(parent)
    widget.setRange(-1000, 1000)
    return Editor(
        widget=widget,
        get_value=lambda: datatype(widget.value()),
        set_value=lambda value: widget.setValue(0 if value is None else value.value),
        changed=widget.valueChanged,
    )


window.editor_registry.register_editor(Reading, reading_editor)
```

Annotate a node parameter with `Reading` or supply a `Reading` value/default
without an annotation. The model preserves custom objects returned by editors.
It also preserves `Enum` members and `Path` objects through `EditRole`.

Lookup checks the exact datatype, then its Python base classes. Enum lookup
stays within enum bases so `IntEnum`, `StrEnum`, and primitive mixins use a
selector. An explicit registration for a particular enum takes priority.

Register factories during setup. An already visible form uses a changed factory
when its values are next refreshed or when another node is selected. A tree
editor uses it when editing starts. Populating widgets does not commit values;
the delegate handles change signals and clearing for every registered editor.

For a standalone delegate, use `delegate.register_editor(Reading, reading_editor)`.
To share registrations between delegates, construct an `EditorRegistry` and pass
it as `NodeInputDelegate(parent, editor_registry=registry)`.
