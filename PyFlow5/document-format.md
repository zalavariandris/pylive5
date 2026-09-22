# Graph and document format

`GraphRT.todict()` writes runtime data. `GraphRT.fromdict(data)` is a class method
that reconstructs a new graph. `PyFlowDocument` calls these methods and adds or
restores each node's `position`; positions are not part of the runtime.

```json
{
  "version": 1,
  "imports": {
    "tools": "./tools.py"
  },
  "definitions": "def identity(value): return value",
  "graph": {
    "nodes": {
      "first": {
        "operator": {"module": "definitions", "name": "identity"},
        "args": [42],
        "position": [0, 0]
      },
      "second": {
        "operator": {"module": "tools", "name": "identity"},
        "args": [{"type": "node", "name": "first"}],
        "position": [200, 0]
      }
    }
  }
}
```

`definitions` is the graph's single embedded Python script. `imports` maps unique
module names to file paths. The name `definitions` is reserved for the embedded
script. Operator references include their module so equally named functions in
different modules are unambiguous. Unused imports are retained.

Imported source is read from its file when loading. Editor changes write through
to that Python file immediately, including incomplete code while typing. Saving a
graph stores only the import paths. Reloading reads without rewriting the file;
failed writes leave the runtime unchanged and are reported in the editor's status
bar. Source files use UTF-8. Relative paths remain relative to the working directory.
The module list observes `GraphRT.modules()` and import changes through the
runtime's `modules_changed` signal.

Inputs preserve null, booleans, integers, floats, strings, lists, tuples,
dictionaries, paths, and node references. Container contents are encoded
recursively:

- Node reference: `{"type": "node", "name": "first"}`.
- Tuple: `{"type": "tuple", "items": [1, 2]}`.
- Dictionary: `{"type": "dict", "items": [["key", "value"]]}`.
- Path: `{"type": "path", "value": "images/example.png"}`.
- Non-finite float: `{"type": "float", "value": "inf"}` (also `-inf` and `nan`).

Literal dictionaries are tagged, so they cannot be mistaken for node references.
Empty `args` and `kwargs` are omitted unless `todict(explicit=True)` is used.
Opaque Python values and operators created by inline decorators cannot be saved;
use the definitions script or an imported module for portable operators.

Loading creates all nodes before connecting inputs, so forward references work.
Invalid definition source and unavailable operators remain editable. Invalid data
or positions are rejected before changing the document. The existing document and
models are retained; their contents and selections reset, the output watcher stops,
and positions are restored. Selection and output locks are not saved.

The older `modules` format and unversioned stringified input format are rejected.
