# Graph evaluation draft

This package is an isolated alternative. Import it explicitly; the original
executors, execution plan, cache, and top-level exports are unchanged.

## Responsibilities

- `GraphCache` stores the latest valid outputs and their original execution
  durations without fingerprints or signals.
- `prepare()` stops traversal at cached nodes and copies required cached values
  into `ExecutionPlan.initial_outputs`. Only missing computations go in `nodes`.
- `execute()` runs a plan without the live graph or persistent cache. Its results
  contain newly computed outputs, failures, and blocked nodes.
- `GraphEvaluator` handles requests, invalidation, plan preparation, stale
  results, cache writes, and accepted result notifications.
- `ExecutionBackend` defines `submit(plan) -> Future[ExecutionResults]` and
  nonblocking `close()`. It has no graph or cache lifecycle responsibilities.
- `InlineExecutionBackend` executes a plan immediately on the caller's thread.
- `QtThreadPoolExecutionBackend` runs a plan on a Qt worker and completes its
  future. The evaluator delivers completion to its own thread before touching
  graph state or the cache.

The evaluator uses composition. Add or replace a backend without subclassing
the evaluator or implementing caching again. The old draft inheritance classes
have been replaced; the public result signal is now `evaluated`.

The existing `GraphDefinitionRT`, `GraphInvalidator`, and `NodeExecution` outcome
types are reused, so existing result consumers can recognize draft outcomes.

## Usage

Create these objects on the graph's owning thread, with a running Qt event loop.
Pass the same invalidator used by the application so script/module edits reach
the cache as well as graph edits. The registry must watch all relevant modules.

```python
from pygraphrt import GraphDefinitionRT, GraphInvalidator, ModuleRegistry, NodeRef
from pygraphrt.graph_executor_3_draft import (
    GraphCache,
    GraphEvaluator,
    NodeExecution,
    QtThreadPoolExecutionBackend,
)

graph = GraphDefinitionRT()

@graph.node(21)
def double(value: int) -> int:
    return value * 2

registry = ModuleRegistry()
registry.add_module(graph.local())
invalidator = GraphInvalidator(graph, registry)
cache = GraphCache()
backend = QtThreadPoolExecutionBackend()
evaluator = GraphEvaluator(graph, backend, cache=cache, invalidator=invalidator)

def show_results(results: dict[NodeRef, NodeExecution]) -> None:
    for node, outcome in results.items():
        print(node.get_name(), outcome)

evaluator.evaluated.connect(show_results)

# Optional: reevaluate affected nodes automatically after invalidation.
def request_changed(nodes: list[NodeRef]) -> None:
    evaluator.request(*nodes)

invalidator.nodes_invalidated.connect(request_changed)
evaluator.request(double)
```

For an existing document, pass its existing graph and invalidator, route requests
to the evaluator, and connect result consumers to `evaluator.evaluated`. Avoid
connecting the same invalidation-to-request callback twice. If no invalidator is
supplied, the evaluator creates one that observes graph edits only. Register
module edits through an injected invalidator or invalidate explicitly when an
external dependency changes.

`evaluator.request(*targets)` is always queued and coalesced. It may return cached
values and does not invalidate running work. A fully cached request publishes
results without submitting to the backend. `evaluated` contains accepted
outcomes, including cached successes; it does not imply every reported operator
ran. The evaluator still uses Qt signals and requires a Qt event loop even with
the inline backend. The backend protocol itself has no Qt signal requirement.

Successful operator calls are measured with `myutils.profiler.Profiler`.
`ExecutionSuccess.duration_seconds` stores the elapsed time and `duration_ms`
exposes it in milliseconds. Cached successes retain the duration of the
computation that produced the cached value and set `cached=True`. Fresh results
set `cached=False` and replace the saved value and duration together. Unmeasured
results have no duration. Timing excludes plan preparation, input resolution,
and time waiting for a worker. PyFlow5 displays cached durations in parentheses.

`evaluator.invalidate(*roots)` evicts roots and their descendants and advances
the revision even without a new request. `evaluator.clear_cache()` evicts all
outputs. Neither starts new work by itself, but pending requests retry if their
running plan becomes obsolete. The revision is a stale-job guard, not a cache
fingerprint. Failed and blocked results are never cached.

`evaluator.close()` is idempotent and closes its dedicated backend. It stops new
work and publication without waiting for already submitted work. Late completion
is ignored. Backend instances belong to one evaluator, but Qt backends may share
the same thread pool. Closing a backend never clears or shuts down that pool;
the pool may still wait for jobs at application shutdown. Disconnect application
callbacks such as `request_changed` when disposing the caller. The retained cache
stops receiving invalidation after close.

## Adding an execution backend

Implement the `ExecutionBackend` protocol. Subclassing is optional; any object
with the following methods can be injected:

```python
def submit(self, plan: ExecutionPlan) -> Future[ExecutionResults]: ...
def close(self) -> None: ...
```

For execution without a worker, use the included implementation:

```python
from pygraphrt.graph_executor_3_draft import GraphEvaluator, InlineExecutionBackend

evaluator = GraphEvaluator(graph, InlineExecutionBackend(), invalidator=invalidator)
```

This runs computations inline when the queued request is processed. `request()`
remains asynchronous. A future may be complete when returned or finish on another
thread. The evaluator owns the callback and marshals completion through a queued
Qt signal, so backends do not need to know how the evaluator receives results.

Call backend `submit()` and `close()` on the owning thread. Node failures belong
in `ExecutionResults`. Infrastructure failures may raise from `submit()` or set
the future's exception; the evaluator reports them as failed plan computations.
A cancelled future is also reported as a failure. Backend `close()` must reject
new submissions without blocking; submitted futures still need to finish or be
cancelled. No backend implements cache access, invalidation, or stale-result
acceptance. `execution_backend.py` and `qt_threadpool_backend.py` provide complete
examples of the contract.

## Value and operator contract

Dedicate a cache to one evaluator and graph. Do not evict or overwrite entries
directly while evaluation is active; use the evaluator's invalidation methods.
Cache entries and published result objects are borrowed and must be treated as
read-only. Plan preparation deep-copies needed cached values and literal inputs
with a shared memo to isolate the worker while preserving aliases. Values must
support `deepcopy`; this may cost time and memory for large outputs. Operators
must treat input values as read-only and be safe to reuse through caching.
Unobserved changes to files, globals, or other external state need explicit
invalidation.

Callables are captured before dispatch, but Python globals and closures are not
isolated. Custom operators need `get_callable()`. The existing `FunctionOperator`
has no such method, so the draft includes a small adapter that captures `_func`
without changing that original class. Plans are currently intended for threads;
process serialization is outside this draft.
