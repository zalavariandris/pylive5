import pytest
from graphcook.eager_engine import EagerEngine
from typing import Callable
from textwrap import dedent

class EagerScriptProvider:
    ...

def test_eager_engine():
    from graphcook.observable_graph import ObservableGraph
    G = ObservableGraph()
    script = dedent("""
    def _the_name
    """)
    provider = EagerScriptProvider(script)
    engine = EagerEngine[Callable]()

if __name__ == "__main__":
    pytest.main([__file__])
