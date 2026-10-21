# Graph documents and sessions

## Ownership

- `PyFlowDocument` owns content, file binding, file stamp, and modified state.
  It reads and writes graph files without showing dialogs.
- `PyFlow5DocumentWindow` owns New, Open, Save, Save As, and user prompts.
  It reconnects views and closes the old evaluator after successful replacement.
- `AppWindow` owns menus, recent files, settings, and session serialization.
  Its file commands delegate to the document window.

## Document API

- `serialize()` returns JSON without changing the binding or modified state.
- `deserialize(text)` creates an unbound document, restores node positions, and
  starts clean. Versions other than integer version 3 are rejected.
- `open(path)` reads UTF-8 JSON and binds the result to the resolved path and
  the file stamp captured while reading.
- `save(override=False)` writes to the bound path. A changed or deleted file
  raises `FileChangedError`; the document window offers an overwrite prompt.
- `saveAs(path, override=True)` writes to a new destination. The save dialog
  confirms replacement of an existing destination.

Both save operations update the binding and file stamp and clear modified state
only after a successful atomic replacement. Failed writes preserve the previous
destination contents and binding.

`fileStat()` returns a `FileStamp` with `st_mtime_ns` and `st_size`, or
None for an unknown baseline. `restoreFileBinding(path, stamp)` restores session
metadata without treating today's disk contents as a new baseline.

Graph definitions, embedded source, module membership, and node positions mark
the document modified. Evaluation results do not. Opening fits the viewport
without rearranging nodes. New/Open prompt to save or discard modified content;
cancelling or a failed save keeps the current document.

## Graph JSON, version 3

`GraphSerializer` writes runtime definitions. `PyFlowDocument` adds node
positions, which must contain two finite numbers.

~~~json
{
  "version": 3,
  "modules": {
    "local": {
      "type": "embedded",
      "source": "def identity(value): return value"
    },
    "tools": {"type": "import", "path": "./tools.py"}
  },
  "graph": {
    "nodes": {
      "first": {
        "operator": {"module": "local", "name": "identity"},
        "args": [{"type": "literal", "value": 42}],
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
~~~

Module keys identify the module referenced by each operator. Embedded modules
store source; imported modules store paths and reload source from disk. Imported
source is read-only in the editor. Relative import paths currently resolve
against the process working directory.

Each positional or keyword input is either a node reference or a literal
wrapper. Literals support null, booleans, integers, finite floats, strings, and
recursive lists, plus these tags:

- Tuple: `{"type": "tuple", "items": [1, 2]}`.
- Dictionary: `{"type": "dict", "items": [["key", "value"]]}`.
- Path: `{"type": "path", "value": "images/example.png"}`.
- Non-finite float: `{"type": "float", "value": "inf"}` (also -inf and nan).

Empty modules, nodes, args, and kwargs may be omitted. Loading creates nodes
before connecting inputs, allowing forward references. Evaluation results,
selections, output locks, and panel layout are not stored.

## Session JSON, version 1

With sessions enabled, normal shutdown atomically writes `session.json` beside
the settings file. This is a shutdown snapshot, not periodic autosave. It does
not write the original graph file.

The session is one JSON object containing:

- `session_version`: integer 1.
- `document`: the complete version 3 graph document.
- `file_path`: the original absolute graph path, or null for an untitled graph.
- `file_stat`: `{"mtime_ns": ..., "size": ...}`, or null for an unknown baseline.
- `modified`: the document's modified flag.

Restoration uses the stored baseline, so external edits made while the app was
closed are detected by the next Save. The original destination and modified
state are restored for saved and unsaved work.

Legacy content-only sessions use `sessionDocumentPath` from QSettings during
migration. Their modified state is conservatively set to true and their file
baseline remains unknown. Saving over an existing file requires confirmation.
The next successful session save writes the new envelope.

If session saving fails, the document window lets the user cancel closing.
With sessions disabled, closing uses the ordinary Save/Discard/Cancel prompt.
An invalid session falls back to a clean, unbound document.
