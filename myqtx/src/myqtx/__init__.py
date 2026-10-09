from importlib import import_module

_EXPORTS = {
    "QPathEdit": "qpathedit",
    "DisplayWidget": "displaywidget",
    "DisplayView": "displayviews",
    "EditorRegistry": "editorregistry",
    "Editor": "editors",
    "blockingSignals": "block_signals_context_manager",
    "FileBinding": "file_binding",
    "FormWidget": "formwidget",
    "Interactive": "formwidget",
    "LockSwitch": "lock_switch",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    module = import_module(f".{_EXPORTS[name]}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))