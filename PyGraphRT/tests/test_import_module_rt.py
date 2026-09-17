from textwrap import dedent

import pytest

from pygraphrt.graph_rt import GraphRT
from pygraphrt.import_module_rt import ImportModuleRT
from pygraphrt.operator_rt import ParameterRT
from pygraphrt.watch import watch


def write_source(path, source):
    path.write_text(dedent(source), encoding="utf-8")
    return path


@pytest.mark.parametrize("path_type", [str, lambda path: path], ids=["string", "path"])
def test_loads_imports_globals_helpers_aliases_and_parameters(tmp_path, path_type):
    path = write_source(tmp_path / "operators.py", """\
        import math
        from math import sqrt

        FACTOR = 2

        def helper(value):
            return math.floor(sqrt(value)) * FACTOR

        def result(value: int = 9) -> int:
            return helper(value)

        alias = result
    """)
    module = ImportModuleRT("tools", path_type(path), watch=False)

    assert module.path() == path
    assert module.get_script() == path.read_text(encoding="utf-8")
    assert set(module.operators()) == {"sqrt", "helper", "result", "alias"}
    result = module.get_operator("result")
    assert result() == 6
    assert module.get_operator("alias")(16) == 8
    assert module.get_operator("sqrt")(25) == 5
    assert dict(result.get_parameters()) == {"value": ParameterRT("value", int, 9)}

    exported = module.operators()
    exported.clear()
    assert module.get_operator("result") is result


def test_empty_source_file_is_valid(tmp_path):
    module = ImportModuleRT("empty", write_source(tmp_path / "empty.py", ""), watch=False)
    assert module.get_script() == ""
    assert module.operators() == {}
    assert module.get_operator("missing") is None


def test_edits_save_and_reload_preserve_operator_handles(tmp_path):
    initial = 'def value():\n    return "initial"\n'
    edited = 'def value():\n    return "árvíz"\n'
    external = 'def value():\n    return "external"\n'
    path = write_source(tmp_path / "operators.py", initial)
    module = ImportModuleRT("tools", path, watch=False)
    value = module.get_operator("value")

    module.set_script(edited)
    assert value() == "árvíz"
    assert path.read_text(encoding="utf-8") == initial
    module.save()
    assert path.read_text(encoding="utf-8") == edited

    path.write_text(external, encoding="utf-8")
    module.reload()
    assert module.get_operator("value") is value
    assert module.get_script() == external
    assert value() == "external"


def test_opening_identical_source_at_another_path_updates_file_context(tmp_path):
    source = "def location():\n    return __name__, __file__\n"
    first = write_source(tmp_path / "first.py", source)
    second = write_source(tmp_path / "second.py", source)
    module = ImportModuleRT("tools", first, watch=False)
    location = module.get_operator("location")
    fingerprint = location.fingerprint()

    module.open(str(second))

    assert module.path() == second
    assert module.get_operator("location") is location
    assert location() == ("tools", str(second))
    assert location.fingerprint() != fingerprint
    assert module._get_function(location).__code__.co_filename == str(second)


@pytest.mark.parametrize("action", ["set_script", "reload", "open"])
@pytest.mark.parametrize("bad_source, error", [
    ("def broken(:\n", SyntaxError),
    ("def replacement():\n    return 99\nraise RuntimeError('failed')\n", RuntimeError),
])
def test_failed_updates_keep_the_last_accepted_state(tmp_path, action, bad_source, error):
    source = "def value():\n    return 1\n"
    path = write_source(tmp_path / "operators.py", source)
    module = ImportModuleRT("tools", path, watch=False)
    value = module.get_operator("value")
    fingerprint = value.fingerprint()
    events = []
    module.script_changed.connect(lambda: events.append("script"))
    module.operators_added.connect(lambda names: events.append(("added", names)))
    module.operators_removed.connect(lambda names: events.append(("removed", names)))
    module.operators_changed.connect(lambda names: events.append(("changed", names)))

    with pytest.raises(error):
        if action == "set_script":
            module.set_script(bad_source)
        elif action == "reload":
            write_source(path, bad_source)
            module.reload()
        else:
            module.open(write_source(tmp_path / "broken.py", bad_source))

    assert module.path() == path
    assert module.get_script() == source
    assert module.operators() == {"value": value}
    assert value() == 1
    assert value.fingerprint() == fingerprint
    assert events == []


def test_missing_file_errors_leave_the_module_usable(tmp_path):
    path = write_source(tmp_path / "operators.py", "def value():\n    return 1\n")
    module = ImportModuleRT("tools", path, watch=False)
    with pytest.raises(FileNotFoundError):
        module.open(tmp_path / "missing.py")
    assert module.path() == path
    path.unlink()
    with pytest.raises(FileNotFoundError):
        module.reload()
    assert module.get_operator("value")() == 1


def test_reload_signals_are_batched_and_observe_committed_state(tmp_path):
    path = write_source(tmp_path / "operators.py", """\
        def removed():
            return 1
        def kept():
            return 2
    """)
    module = ImportModuleRT("tools", path, watch=False)
    kept = module.get_operator("kept")
    removed = module.get_operator("removed")
    events = []

    def observe(kind, names=None):
        events.append((kind, names, sorted(module.operators()), kept()))

    module.script_changed.connect(lambda: observe("script"))
    module.operators_removed.connect(lambda names: observe("removed", names))
    module.operators_added.connect(lambda names: observe("added", names))
    module.operators_changed.connect(lambda names: observe("changed", names))
    module.set_script("""\
def kept():
    return 20
def z_added():
    return 30
def a_added():
    return 40
""")

    assert module.get_operator("kept") is kept
    assert [(kind, names) for kind, names, _, _ in events] == [
        ("script", None), ("removed", ["removed"]),
        ("added", ["a_added", "z_added"]), ("changed", ["kept"]),
    ]
    assert all(names == ["a_added", "kept", "z_added"] and value == 20
               for _, _, names, value in events)
    assert not removed.isValid()
    assert dict(removed.get_parameters()) == {}
    with pytest.raises(ValueError):
        removed()
    with pytest.raises(ValueError):
        removed.fingerprint()


def test_exports_follow_executed_bindings_on_load_and_reload(tmp_path):
    source = """\
from math import sqrt
def outer():
    def inner():
        return 3
    return inner()
alias = outer
class Callable:
    def __call__(self):
        return 4
instance = Callable()
"""
    path = write_source(tmp_path / "operators.py", "")
    module = ImportModuleRT("tools", path, watch=False)
    write_source(path, source)
    module.reload()
    fresh = ImportModuleRT("fresh", path, watch=False)
    assert set(module.operators()) == set(fresh.operators()) == {
        "sqrt", "outer", "alias", "Callable", "instance",
    }
    assert module.get_operator("alias")() == 3
    assert module.get_operator("instance")() == 4
    outer = module.get_operator("outer")
    module.set_script("def outer():\n    return 5\n")
    assert module.operators() == {"outer": outer}
    assert outer() == 5


def test_unchanged_source_does_not_emit_signals_or_invalidate_cache(tmp_path):
    source = "def value():\n    return 1\n"
    module = ImportModuleRT("tools", write_source(tmp_path / "operators.py", source), watch=False)
    value = module.get_operator("value")
    fingerprint = value.fingerprint()
    events = []
    module.script_changed.connect(lambda: events.append("script"))
    module.operators_changed.connect(events.append)
    module.reload()
    module._reload()
    module.set_script(source)
    assert events == []
    assert module.get_operator("value") is value
    assert value.fingerprint() == fingerprint


def test_global_changes_refresh_graph_cache_and_notify_watchers(tmp_path):
    source = "FACTOR = 2\ndef value():\n    return FACTOR\n"
    path = write_source(tmp_path / "operators.py", source)
    module = ImportModuleRT("tools", path, watch=False)
    graph = GraphRT()
    graph.add_modules([module])
    value = graph.node()(module.get_operator("value"))

    @graph.node(value)
    def result(number):
        return number * 10

    assert graph.execute(result) == 20
    results = []
    watcher = watch(graph, result, lambda: results.append(graph.execute(result)))
    try:
        write_source(path, source.replace("FACTOR = 2", "FACTOR = 3"))
        module.reload()
        assert results == [30]
        assert graph.execute(result) == 30
    finally:
        watcher.stop()


def test_removed_globals_do_not_survive_reload(tmp_path):
    source = "FLAG = 1\ndef value():\n    return globals().get('FLAG', 0)\n"
    path = write_source(tmp_path / "operators.py", source)
    module = ImportModuleRT("tools", path, watch=False)
    value = module.get_operator("value")
    assert value() == 1
    module.set_script("def value():\n    return globals().get('FLAG', 0)\n")
    assert value() == 0


def test_operator_ownership_and_fingerprints_are_module_specific(tmp_path):
    path = write_source(tmp_path / "operators.py", "from math import sqrt\n")
    first = ImportModuleRT("first", path, watch=False)
    second = ImportModuleRT("second", path, watch=False)
    sqrt = first.get_operator("sqrt")
    fingerprint = sqrt.fingerprint()
    assert fingerprint != second.get_operator("sqrt").fingerprint()
    assert not second.isValid(sqrt)
    assert dict(second.get_parameters(sqrt)) == {}
    with pytest.raises(ValueError):
        second.call(sqrt, 4)
    with pytest.raises(ValueError):
        second.fingerprint(sqrt)

    first.set_script("from math import sqrt\nFACTOR = 2\n")
    assert first.get_operator("sqrt") is sqrt
    assert sqrt.fingerprint() != fingerprint
