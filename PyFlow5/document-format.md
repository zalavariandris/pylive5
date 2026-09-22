# Document format, version 1

`PyFlowDocument.todict()` and `fromdict()` use the same JSON-compatible format:

```json
{
  "version": 1,
  "modules": {
    "module_0": {
      "type": "script",
      "name": "tools",
      "source": "def identity(value): return value"
    }
  },
  "nodes": {
    "first": {
      "operator": {"module": "module_0", "name": "identity"},
      "args": [42],
      "kwargs": {},
      "position": [0, 0]
    },
    "second": {
      "operator": {"module": "module_0", "name": "identity"},
      "args": [{"type": "node", "name": "first"}],
      "kwargs": {},
      "position": [200, 0]
    }
  }
}
```

Module IDs identify records independently of their editable names. Duplicate
module names and operator names are allowed. Module order is preserved.

Imported modules use `"type": "import"` and add a `"path"`. Their saved source
includes unsaved edits and is restored without reading the external file.
An explicit reload reads that file. Relative paths retain their existing meaning:
relative to the application's working directory.

Inputs support null, booleans, integers, floats, strings, lists, tuples,
dictionaries, paths, and node references. Tuples use
`{"type": "tuple", "items": [...]}`. Dictionaries use
`{"type": "dict", "items": [[key, value], ...]}` so literal dictionaries cannot
be confused with reference records. Container contents are encoded recursively.
Paths use `{"type": "path", "value": "..."}`. Non-finite floats use
`{"type": "float", "value": "inf"}` (or `"-inf"` / `"nan"`).

Opaque Python objects, including custom class instances, and operators from local
Python functions cannot be saved. Saving raises an error rather than converting
them to strings. Move local functions into a script module to make them portable.

Loading builds modules, then all nodes, then their inputs. Malformed data is
rejected before replacing the document's runtime. Invalid script source and
unavailable operators remain editable, as they do during live editing. Loading
retains the document and models, resets their contents and selection, stops the
output watcher, and restores node positions. Selection and output locks are not
saved.

Unversioned files from the previous writer are rejected: their stringified values
and unqualified operator names cannot be restored unambiguously.
