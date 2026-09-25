from pathlib import Path
from textwrap import dedent

import pytest

from pygraphrt.script_module import ScriptModuleRT
from pygraphrt.import_module import ImportModuleRT
from pygraphrt.abstract_module_rt import ParameterData

@pytest.mark.parametrize("ModuleClass, name", [
    (ScriptModuleRT, "script"), 
    (ImportModuleRT, "import"),
    (ScriptModuleRT, None), 
    (ImportModuleRT, None)
])
def test_initialization(ModuleClass, name):
    im = ModuleClass(name)
    im.set_script("def hello(): return 'Hello!'")
    assert 'hello' in [op.name for op in im.operators()]

    im.set_script(dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))
    assert im is not None

    assert set(op.name for op in im.operators()) == {"one", "pow", "mult"}

    mult_op = next(op for op in im.operators() if op.name == 'mult')
    actual_parameters = list(mult_op.get_parameters().values())
    expected_parameters = [
        ParameterData("a"), 
        ParameterData("b")
    ]
    assert actual_parameters == expected_parameters


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

def test_reading_script_with_inconsistent__all__(monkeypatch: pytest.MonkeyPatch) -> None:
    source = dedent("""\
        def op(): return 0
        def op1(): return 1

        __all__ = ['op', 'op2']
    """)
    def read_source(self: Path, encoding: str) -> str:
        return source

    monkeypatch.setattr(Path, "read_text", read_source)
    module = ImportModuleRT("tools.py")
    assert isinstance(module.get_state(), AttributeError)
    assert "op2" in str(module.get_state())
    assert module.get_script() == source
    assert list(module.operators()) == []

@pytest.mark.parametrize("source, error_type", [
    ("def broken(:", SyntaxError),
    ("raise RuntimeError('broken')", RuntimeError),
])
def test_reload_records_script_errors(
    monkeypatch: pytest.MonkeyPatch, source: str, error_type: type[Exception]
) -> None:
    file_source = "def op(): return 1"

    def read_source(self: Path, encoding: str) -> str:
        return file_source

    monkeypatch.setattr(Path, "read_text", read_source)
    module = ImportModuleRT("tools.py")
    observed: list[str] = []
    module.script_changed.connect(lambda: observed.append(module.get_script()))

    file_source = source
    module.reload_file()

    assert isinstance(module.get_state(), error_type)
    assert list(module.operators()) == []
    assert observed == [source]


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
def test_reload_read_errors_propagate_without_committing(
    monkeypatch: pytest.MonkeyPatch, error_type: type[OSError]
) -> None:
    source = "def op(): return 1"

    def read_source(self: Path, encoding: str) -> str:
        return source

    monkeypatch.setattr(Path, "read_text", read_source)
    module = ImportModuleRT("tools.py")
    observed: list[str] = []
    module.script_changed.connect(lambda: observed.append(module.get_script()))
    error = error_type("cannot read source")

    def failed_read(self: Path, encoding: str) -> str:
        raise error

    monkeypatch.setattr(Path, "read_text", failed_read)
    with pytest.raises(error_type) as caught:
        module.reload_file()

    assert caught.value is error
    assert module.get_script() == source
    assert module.get_state() == "VALID"
    assert next(iter(module.operators()))() == 1
    assert observed == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
