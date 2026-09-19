import pytest
import traceback
from textwrap import dedent
from pygraphrt2.script_module import ScriptModule
from pygraphrt2.graph_rt2 import GraphRT, ParameterData

def test_initializatino():
    sm = ScriptModule("mathy", dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))
    assert sm is not None

    assert sm.operators().keys() == {"one", "pow", "mult"}

    mult_op = sm.operators()['mult']
    actual_parameters = list(mult_op.get_parameters().values())
    expected_parameters = [
        ParameterData("a"), 
        ParameterData("b")
    ]
    assert actual_parameters == expected_parameters


def test_updating_script():
    sm = ScriptModule("mathy", dedent("""\
        def one():
            return 1

        def pow(x):
            return x ** 2

        def mult(a, b):
            return a * b
        """))

    # Update the script
    sm.set_script(dedent("""\
        def two():
            return 2

        def pow(x, y):
            return x ** y

        def mult(a, b):
            return a * b
        """))

    assert set(sm.operators().keys()) == {"two", "pow", "mult"}

def test_updating_script_with_syntaxerror():
    """Script module should be deterministic.
    therefore a script with a syntax error should return the 
    same operators as a newly initialized script with syntax errors."""
    source_without_syntaxerror = dedent("""\
        def one():
            return 1

        def pow(x):
            return x ** 2

        def mult(a, b):
            return a * b
        """)
    source_with_syntaxerror = dedent("""\
        def one():
            return 1

        def pow(x):
            return x ** 2

        def mult(a, 
            return a * b
        """)
    
    sm = ScriptModule("mathy", source_without_syntaxerror)
    sm.set_script(source_with_syntaxerror)

    assert sm.operators().keys() == ScriptModule("mathy", source_with_syntaxerror).operators().keys()


from qtpy.QtTest import QSignalSpy
def test_updating_script_signals():
    sm = ScriptModule("mathy", dedent("""\
        def one():
            return 1

        def pow(x):
            return x ** 2

        def mult(a, b):
            return a * b
        """))

    removed = []
    added = []
    changed = []

    def on_removed(names):
        nonlocal removed
        removed = names

    def on_added(names):
        nonlocal added
        added = names

    def on_changed(names):
        nonlocal changed
        changed = names

    sm.operators_removed.connect(on_removed)
    sm.operators_added.connect(on_added)
    sm.operators_changed.connect(on_changed)

    sm.set_script(dedent("""\
        def two():
            return 2

        def pow(x, y):
            return x ** y

        def mult(a, b):
            return a * b
        """))

    assert added == ["two"]
    assert removed == ["one"]
    assert changed == ["pow"]


@pytest.mark.parametrize("name", ["tools", "mathy"])
def test_module_name_is_used_in_tracebacks_and_retained_for_edits(name):
    source = dedent("""\
        def location():
            return __name__, "__file__" in globals()

        def fail():
            raise ValueError("original")
        """)
    module = ScriptModule(name, source)

    for message in ("original", "edited"):
        module.set_script(source.replace("original", message))
        assert module.get_operator("location")() == (name, False)
        with pytest.raises(ValueError, match=message) as error:
            module.get_operator("fail")()
        frame = traceback.extract_tb(error.value.__traceback__)[-1]
        assert frame.filename == f"<script:{name}>"
        assert frame.name == "fail"


def test_syntax_errors_use_module_name_and_invalid_script_clears_operators():
    source = dedent("""\
        def location():
            return __name__
        """)
    invalid_source = "def broken(:\n"
    invalid_module = ScriptModule("tools", invalid_source)
    assert invalid_module.get_script() == invalid_source
    assert invalid_module.operators() == {}
    assert isinstance(invalid_module.get_state(), SyntaxError)
    assert invalid_module.get_state().filename == "<script:tools>"

    module = ScriptModule("tools", source)
    failures = []
    removed = []
    added = []
    script_changes = []
    module.script_changed.connect(lambda: script_changes.append(module.get_script()))
    module.script_failed.connect(failures.append)
    module.operators_removed.connect(removed.append)
    module.operators_added.connect(added.append)

    module.set_script(invalid_source)

    assert failures == []
    assert module.get_script() == invalid_source
    assert module.operators() == {}
    assert module.get_operator("location") is None
    assert removed == [["location"]]
    assert isinstance(module.get_state(), SyntaxError)
    assert module.get_state().filename == "<script:tools>"
    assert script_changes == [invalid_source]

    module.set_script(invalid_source)
    assert script_changes == [invalid_source]
    assert removed == [["location"]]

    module.set_script(source)

    assert module.get_script() == source
    assert module.operators().keys() == {"location"}
    assert module.get_operator("location")() == "tools"
    assert added == [["location"]]

    assert module.get_state() == "VALID"
    assert script_changes == [invalid_source, source]


@pytest.mark.parametrize("source, expected_state", [
    ("", "VALID"),
    ("value = 1", "VALID"),
    ("def one(): return 1", "VALID")
])
def test_initial_module_state(source, expected_state):
    module = ScriptModule("tools", source)
    assert module.get_state() == expected_state, f"Expected state {expected_state}, but got {module.get_state()}"

def test_initial_module_state_with_error(source, expected_state):
    module = ScriptModule("tools", "broken(:")
    assert isinstance(module.get_state(), SyntaxError)

def test_state_changed_reports_committed_state_only_on_transitions():
    source = "def one(): return 1"
    module = ScriptModule("tools", source)
    observed = []
    module.state_changed.connect(
        lambda state: observed.append(
            (state, module.get_state(), module.get_script(), set(module.operators()))
        )
    )

    module.set_script(source + "\n# valid edit")
    assert observed == []

    invalid_source = "def broken(:"
    module.set_script(invalid_source)
    assert observed == [("syntax_error", "syntax_error", invalid_source, set())]

    module.set_script(invalid_source)
    module.set_script("def still_broken(:")
    assert module.get_state() == "syntax_error"
    assert len(observed) == 1

    module.set_script(source)
    assert observed[-1] == ("valid", "valid", source, {"one"})
    assert len(observed) == 2

    module.set_script("")
    assert module.get_state() == "valid"
    assert module.operators() == {}
    assert len(observed) == 2


def test_execution_error_preserves_stored_script_state():
    source = "def one(): return 1"
    module = ScriptModule("tools", source)
    states = []
    module.state_changed.connect(states.append)

    with pytest.raises(ValueError, match="execution failed"):
        module.set_script('raise ValueError("execution failed")')

    assert module.get_state() == "VALID"
    assert module.get_script() == source
    assert module.get_operator("one")() == 1
    assert states == []


if __name__ == "__main__":
    pytest.main([__file__])