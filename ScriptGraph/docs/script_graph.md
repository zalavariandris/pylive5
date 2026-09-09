# ScriptGraph proposal

Status: specifications and stubs for review, not an implemented converter.
The public API lives in the separate `scriptgraph` package, which depends on
PyGraphRT. GraphRT has no dependency on ScriptGraph.

GraphRT is the source of truth. Live execution and direct graph mutation take
priority. ScriptGraph attaches to an existing graph and translates between its
current state and a supported Python subset. GraphSpec is only a temporary parse
result or detached snapshot. Formatting metadata never overrides graph state.

## First supported script format

```python
def number():
    return 2

def add(a, b):
    return a + b

left = number()
result = add(left, b=3)
__output__ = result
```

Top-level synchronous function definitions become operators. Assignments of
direct calls to these local functions become nodes; assignment targets name the
nodes. Multiple calls to one function produce distinct nodes. Bare references
to previously defined nodes become connections. Scalar literals (strings,
integers, floats, booleans, None, and negative numbers) become raw inputs.
Positional and keyword arguments are supported. `__output__ = node_name` selects
the output; omitting it leaves output unset. Empty scripts are valid.

Imports are recorded without loading dependencies. Multiple names and multiline
imports map to individual ImportRT entries while retaining the original source
statement. Functions may use imported names inside their bodies. Bodies are
preserved as Python, rather than translated into graph operations.

Initially reject top-level control flow, classes, async functions, decorators,
arbitrary expression statements, constant assignments, duplicate bindings,
forward references, attribute calls, nested calls in node arguments, unpacking,
and container/expression inputs. Also reject function defaults and annotations
in the first version to avoid implicit definition-time evaluation during graph
construction. These restrictions concern graph-level syntax; ordinary control
flow inside a function body is allowed. Imported callables are not direct node
operators yet. Users can wrap them in local functions.

## Source preservation

After successful `update_source(text)`, `to_source()` must return exactly `text`
if the graph has not changed, including comments,
blank lines, import grouping, line endings, and final newline presence.
GraphSpec stores meaning; it does not store parentheses or formatting choices.
The document privately associates statements and their source spans with graph
bindings. Spans must be refreshed after every accepted edit, not treated as IDs.

`to_source()` compares the current graph with its last exported/imported snapshot.
Unchanged statements retain their original text. Changed statements are replaced
as a whole using deterministic Python formatting. A changed multiline import may
become one import per line. Comments inside replaced statements may be lost in
this first version; separate untouched comment lines remain. New imports precede
functions, new functions precede nodes, and nodes are emitted in dependency order.
Inserted lines use the document's prevailing newline style (LF on an empty file).

GraphSpec dictionaries use binding names as identity in version one. Renaming
is a remove/add operation. Stable internal IDs for preserving runtime identity
across renames are deferred. Any edit to one entry of a grouped import rewrites
that source statement; other import statements remain untouched.

## API and execution boundary

- `ScriptGraph(graph)`: attach to the caller's live GraphRT; never replace it.
- `ScriptGraph.parse(text)`: parse and validate a candidate without execution.
- `adapter.graph`: the authoritative GraphRT instance.
- `adapter.spec`: detached snapshot of the current graph with imports, function source,
  NodeSpec entries, and optional output name.
- `adapter.to_source()`: export current graph state, preserving compatible source text.
- `adapter.update_source(text)`: validate and apply source changes to the existing graph.
- `adapter.apply_spec(spec)`: validate and apply a candidate to the existing graph.

Editor actions mutate GraphRT directly. Applying source edits may load imports
and create function definitions in a shared namespace; node calls stay deferred.
Apply accepted changes between executions, preserving unaffected node identities
and invalidating affected caches. No background scheduling is provided by this adapter.

Syntax errors raise SyntaxError. Unsupported constructs and invalid references
raise UnsupportedScriptError with a useful location/message. Failed edits leave
the previous source and live graph intact. The editor keeps incomplete
buffer text separately and can continue using the last valid runtime.

Applying source is trusted-code execution, not sandboxing. This API must not
reuse the existing whole-script exec converter: node assignments in the source
describe connections and must not execute functions during conversion.

## Live editing roadmap and review decisions

Implement graph -> Python export first, including export after direct graph
mutations. Next implement parsing and validated changes to that same live graph.
Source preservation follows as optional metadata. Unsupported runtime values must
produce a clear export error rather than silently changing the graph.

GraphRT currently needs a reviewed ownership API for imports and retained operator
source. Add that capability to GraphRT before supporting imported dependencies in
this adapter; do not make ScriptGraph a second authority for runtime dependencies.
Atomic application/rollback and cache invalidation also require runtime integration
work. These are implementation requirements, not capabilities of the current stubs.

Review the reserved `__output__` name, supported syntax, whole-statement comment
policy, and whether name-based identity is enough before implementing conversion.
The tests describe the proposed contract. Tests requiring the stubs are marked
strict xfail only for NotImplementedError; remove those marks as implemented.
