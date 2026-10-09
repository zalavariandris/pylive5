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

Factories receive the full parameter annotation and a parent widget. For ordinary
class annotations this is the actual Python datatype; parameterized annotations
such as `Tuple[float, float]` are passed intact. They return
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

## Contextual editor providers

Use a provider when the meaning of an annotation depends on the operator's
module or parameter. Plain aliases do not preserve their semantic names:
`Color = Tuple[float, float, float, float]` compares equal to any other alias
with that same tuple shape.

A provider is a function accepting an `EditorContext` and returning an
`EditorFactory`, or `None` to defer to the next lookup. The context contains
`module_name`, `operator_name`, `parameter_name`, the full `annotation`, and
`source_path` (`Path | None`). Providers select factories; factories create widgets.

```python
from pathlib import Path
from typing import get_args, get_origin

from myqtx import EditorContext, EditorFactory
from myqtx.tuple_editor import numeric_tuple_editor


def geometry_editors(context: EditorContext) -> EditorFactory | None:
    if (
        context.operator_name == "transform"
        and context.parameter_name == "position"
        and get_origin(context.annotation) is tuple
        and get_args(context.annotation) == (float, float, float)
    ):
        return numeric_tuple_editor
    return None


# PyGraphRT imports a file as an executed script. Use its exact file path.
window.editor_registry.register_provider(
    module=Path("operators/geometry.py"), provider=geometry_editors,
)

# For ordinary Python functions, register their defining Python module name.
window.editor_registry.register_provider(
    module="geometry.transforms", provider=geometry_editors,
)
```

Lookup tries the resolved source-file provider, then the exact module-name
provider, then the ordinary type registry. `None` continues that lookup.
Paths are resolved when registered and looked up; strings always mean module
names, so use `Path` for files. Registrations replace an existing provider for
the same scope and remain local to that registry. Module names do not match
submodules automatically. The delegate also exposes `register_provider`.

File scope is useful because PyGraphRT gives imported scripts names such as
`geometry.py`, which may differ from their Python package name and may be
shared by files in different directories. File providers survive display-name
changes and source reloads. Connected parameters remain read-only.

Fixed-length numeric tuple editors return actual tuples; the input model checks
their length and converts numeric components according to the annotation.
Opening an editor or clearing an input does not store the displayed default.
Unsupported annotations still use read-only text.

## vfxops integration

PyFlow's window registers `pyflow5.vfxops_editors.vfxops_editor_provider` for the
workspace's `vfxops/src/vfxops/vfxops.py`, an installed `vfxops.vfxops` source
file when discoverable, and the Python module name `vfxops.vfxops`.
It supplies X/Y/Z controls for `Vec2` and `Vec3`, W/H controls for `Size`,
X/Y/W/H controls for `Rect`, and an RGBA editor with a color picker for `Color`.
The integration lives in PyFlow; vfxops itself has no Qt dependency.

For a separate copy of the source, register its path explicitly:

```python
from pathlib import Path
from pyflow5.vfxops_editors import register_vfxops_editors

register_vfxops_editors(window.editor_registry, Path("my_operators/vfxops.py"))
```

Other files receive none of these tuple-specific editors unless they register
a provider. A provider for another module can choose a different editor for
exactly the same tuple shape.
