import pytest
import pygraphrt as rt
from textwrap import dedent

def test_operator_getsource():
    G = rt.GraphRT()

    @G.module().op()
    def add(a:int, b:int) -> int:
        return a + b
    print(add.get_source())

    assert add.get_source() == dedent("""\
    def add(a:int, b:int) -> int:
        return a + b
    """), "Operator get_source should return the source code of the function"

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
