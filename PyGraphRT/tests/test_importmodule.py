from pathlib import Path

import pytest

from pygraphrt.import_module import ImportModuleRT


def test_edits_write_source_before_notifying_observers(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 1", encoding="utf-8")
    module = ImportModuleRT(str(path))
    observed = []
    module.script_changed.connect(lambda: observed.append(path.read_text(encoding="utf-8")))
    source = "def op(): return 'Mása'"
    module.set_script(source)
    assert path.read_text(encoding="utf-8") == source
    assert module.get_script() == source
    assert observed == [source]

    module.set_script("def op(:")
    assert path.read_text(encoding="utf-8") == "def op(:"
    assert isinstance(module.get_state(), SyntaxError)


def test_reload_does_not_write_to_the_file(tmp_path, monkeypatch):
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 1", encoding="utf-8")
    module = ImportModuleRT(str(path))
    source = "def op(): return 2"
    path.write_text(source, encoding="utf-8")

    def unexpected_write(*args, **kwargs):
        pytest.fail("Reload must only read the file")

    monkeypatch.setattr(Path, "write_text", unexpected_write)
    module.reload_file()
    assert module.get_script() == source
    module.set_script(source)


def test_failed_write_does_not_change_runtime_or_emit_success(tmp_path, monkeypatch):
    path = tmp_path / "tools.py"
    source = "def op(): return 1"
    path.write_text(source, encoding="utf-8")
    module = ImportModuleRT(str(path))
    changes = []
    module.script_changed.connect(lambda: changes.append(True))

    def denied(*args, **kwargs):
        raise PermissionError("read-only file")

    monkeypatch.setattr(Path, "write_text", denied)
    with pytest.raises(PermissionError):
        module.set_script("def op(): return 2")
    assert module.get_script() == source
    assert path.read_text(encoding="utf-8") == source
    assert changes == []


def test_invalid_value_does_not_touch_file(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("original", encoding="utf-8")
    module = ImportModuleRT(str(path))
    with pytest.raises(TypeError):
        module.set_script(None)
    assert path.read_text(encoding="utf-8") == "original"

def test_file_missing_reload_reports_no_operators(tmp_path):
    path = tmp_path / "tools.py"
    source = "def op(): return 1"
    path.write_text(source, encoding="utf-8")
    module = ImportModuleRT(str(path))

    assert len(list(module.operators())) > 0

    # delete source file
    path.unlink()
    with pytest.raises(FileNotFoundError):
        module.reload_file()
    assert len(list(module.operators())) > 0
