# ScriptGraph

Python subset import/export and optional source preservation for PyGraphRT.
GraphRT is the source of truth; running and mutating the graph live takes priority.
This package depends on PyGraphRT. PyGraphRT does not depend on ScriptGraph.

The conversion API is currently a review scaffold with explicit stubs.
See [the specification](docs/script_graph.md).

```python
from pygraphrt import GraphRT
from scriptgraph import ScriptGraph

graph = GraphRT()
adapter = ScriptGraph(graph)
# Mutate graph directly through GraphRT's API.
# Planned: adapter.to_source() exports its current state.
# Planned: adapter.update_source(text) applies supported Python edits to graph.
```

Run tests from the workspace root:

```text
.venv/Scripts/python.exe -m pytest -c ScriptGraph/pyproject.toml ScriptGraph/tests
```

Conversion tests are strict expected failures for NotImplementedError until the
stubs are implemented. Graph attachment is implemented and tested normally.
