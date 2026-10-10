import pytest

from pathlib import Path
from textwrap import dedent

from pygraphrt import ImportModuleRT, ScriptModuleRT


def test_function_discovery_from_python_modules():
    sm = ScriptModuleRT("test_module")
    sm.set_script(dedent("""
    from math import sqrt

    def hello():
        return "Hello, world!"

    """))

    assert list([op.get_name() for op in sm.operators()]) == ["hello"]

    sm.set_script(dedent("""
    from math import sqrt
    
    def hello():
        return "Hello, world!"

    __all__ = [
        "hello",
        "sqrt",
    ]
    
    """))
    assert list([op.get_name() for op in sm.operators()]) == ["hello", "sqrt"]

if __name__ == "__main__":
    pytest.main([__file__])
