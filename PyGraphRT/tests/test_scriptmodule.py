from pygraphrt.abstract_module_rt import OperatorRef
import pytest
import traceback
from textwrap import dedent
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.abstract_module_rt import ParameterData

def test_initialization():
    sm = ScriptModuleRT("mathy", dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))
    assert sm is not None

    assert [op.name for op in sm.operators()] == ["one", "pow", "mult"]

    mult_op = next(op for op in sm.operators() if op.name == 'mult')
    actual_parameters = list(mult_op.get_parameters().values())
    expected_parameters = [
        ParameterData("a"), 
        ParameterData("b")
    ]
    assert actual_parameters == expected_parameters


def test_updating_script():
    sm = ScriptModuleRT("mathy", dedent("""\
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

    assert set([op.name for op in sm.operators()]) == {"two", "pow", "mult"}

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
    
    sm = ScriptModuleRT("mathy", source_without_syntaxerror)
    sm.set_script(source_with_syntaxerror)

    assert sm.operators() == ScriptModuleRT("mathy", source_with_syntaxerror).operators()


from qtpy.QtTest import QSignalSpy
def test_updating_script_signals():
    sm = ScriptModuleRT("mathy", dedent("""\
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

    assert added == [OperatorRef(sm, "two")]
    assert removed == [OperatorRef(sm, "one")]
    assert changed == [OperatorRef(sm, "pow")]


def test_syntax_errors_use_module_name():
    invalid_source = "def broken(:\n"
    invalid_module = ScriptModuleRT("tools", invalid_source)
    assert invalid_module.get_script() == invalid_source
    assert len(invalid_module.operators()) == 0
    assert isinstance(invalid_module.get_state(), SyntaxError)
    assert invalid_module.get_state().filename == "<script:tools>"


@pytest.mark.parametrize("source, expected_state", [
    ("", "VALID"),
    ("value = 1", "VALID"),
    ("def one(): return 1", "VALID")
])
def test_initial_module_state(source, expected_state):
    module = ScriptModuleRT("tools", source)
    assert module.get_state() == expected_state, f"Expected state {expected_state}, but got {module.get_state()}"

def test_initial_module_state_with_error():
    module = ScriptModuleRT("tools", "broken(:")
    assert isinstance(module.get_state(), SyntaxError)

from collections import Counter
def test_state_changed_reports_committed_state_only_on_transitions():
    valid_source = "def one(): return 1"
    module = ScriptModuleRT("tools", valid_source)
    assert module.get_state() == "VALID"

    counter = 0
    def increment_counter():
        nonlocal counter
        counter += 1
    module.state_changed.connect(increment_counter)

    module.set_script(valid_source + "\n# valid edit")
    assert module.get_state() == "VALID"
    assert counter == 0, f"valid to valid transition should not trigger state_changed"

    module.set_script(valid_source + "\n# another valid edit")
    assert module.get_state() == "VALID"
    assert counter == 0, f"valid to valid transition should not trigger state_changed"

    module.set_script("def broken(:")
    assert isinstance(module.get_state(), SyntaxError)
    assert counter == 1, f"valid to invalid transition should trigger state_changed"

    module.set_script("def broken(hello")
    assert isinstance(module.get_state(), SyntaxError)
    assert counter == 2, f"erros message of state has changed, therefor a state change should have been triggered"

    module.set_script(valid_source)
    assert module.get_state() == "VALID"
    assert counter == 3, f"Expected counter to be 2, but got {counter}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

@pytest.mark.parametrize("invalid_script", ["def broken(:", "raise RuntimeError('broken')"])
def test_failed_script_emits_removed_operator_refs(invalid_script):
    module = ScriptModuleRT("tools", "def one(): return 1")
    removed = []
    module.operators_removed.connect(removed.append)
    module.set_script(invalid_script)
    assert removed == [[OperatorRef(module, "one")]]
    assert removed[0][0].get_value() is None
