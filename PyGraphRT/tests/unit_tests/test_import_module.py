from pathlib import Path

from pygraphrt import ImportModuleRT


def test_import_loads_and_reloads_without_saving_in_memory_edits(tmp_path: Path) -> None:
    path = tmp_path / "external.py"
    source = "def value() -> int: return 1\n"
    path.write_text(source, encoding="utf-8")

    module = ImportModuleRT("external", path=path)
    assert module.path() == path
    assert module.get_source() == source
    assert module.get_operator_by_name("value")() == 1

    module.set_script("def value() -> int: return 2\n")
    assert module.get_operator_by_name("value")() == 2
    assert path.read_text(encoding="utf-8") == source

    updated_source = "def value() -> int: return 3\n"
    path.write_text(updated_source, encoding="utf-8")
    module.reload_file()
    assert module.get_source() == updated_source
    assert module.get_operator_by_name("value")() == 3
    assert path.read_text(encoding="utf-8") == updated_source
