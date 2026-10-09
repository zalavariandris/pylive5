"""Optional UI integration for vfxops, without importing its image dependencies."""

from importlib.util import find_spec
from pathlib import Path
from typing import get_args, get_origin

from qtpy.QtWidgets import QWidget

from myqtx.color_editor_widget import ColorEdit
from myqtx.editorregistry import EditorContext, EditorRegistry
from myqtx.editors import Editor, EditorFactory
from myqtx.tuple_editor import numeric_tuple_editor


def vector_editor(
    annotation: object, parent: QWidget | None,
) -> Editor[tuple[int | float, ...]]:
    labels = ("X", "Y", "Z")[:len(get_args(annotation))]
    return numeric_tuple_editor(annotation, parent, labels=labels)


def size_editor(
    annotation: object, parent: QWidget | None,
) -> Editor[tuple[int | float, ...]]:
    return numeric_tuple_editor(annotation, parent, labels=("W", "H"))


def rect_editor(
    annotation: object, parent: QWidget | None,
) -> Editor[tuple[int | float, ...]]:
    return numeric_tuple_editor(annotation, parent, labels=("X", "Y", "W", "H"))


def color_editor(
    annotation: object, parent: QWidget | None,
) -> Editor[tuple[float, float, float, float]]:
    widget = ColorEdit(parent)

    def set_value(value: tuple[float, float, float, float] | None) -> None:
        widget.setColor(*(value if value is not None else (0.0, 0.0, 0.0, 1.0)))

    return Editor(widget, widget.color, set_value, widget.valueChanged)


def vfxops_editor_provider(context: EditorContext) -> EditorFactory | None:
    """Interpret tuple shapes using vfxops' own alias conventions."""
    if get_origin(context.annotation) is not tuple:
        return None
    components = get_args(context.annotation)
    if components == (float, float, float, float):
        return color_editor
    if components in ((float, float), (float, float, float)):
        return vector_editor
    if components == (int, int):
        return size_editor
    if components == (int, int, int, int):
        return rect_editor
    return None


def register_vfxops_editors(
    registry: EditorRegistry, source_path: Path | None = None,
) -> None:
    """Register vfxops by Python name and by its exact source file.

    Pass source_path for a separate copy loaded through PyGraphRT's file import.
    Otherwise discover the installed package and the development workspace copy.
    """
    registry.register_provider("vfxops.vfxops", vfxops_editor_provider)
    if source_path is not None:
        registry.register_provider(source_path, vfxops_editor_provider)
        return

    try:
        spec = find_spec("vfxops.vfxops")
    except ModuleNotFoundError:
        spec = None
    if spec is not None and spec.origin is not None:
        registry.register_provider(Path(spec.origin), vfxops_editor_provider)

    workspace_source = Path(__file__).resolve().parents[3] / "vfxops/src/vfxops/vfxops.py"
    if workspace_source.is_file():
        registry.register_provider(workspace_source, vfxops_editor_provider)
