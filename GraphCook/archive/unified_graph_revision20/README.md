# PyGraph — execution strategies with a minimal BaseEngine

Python 3.11+. This is a synchronous reference implementation, designed for
architectural discussion rather than production.

Run tests:

```bash
python -m unittest discover -s tests -v
```

## Components

| Module | Ownership |
| --- | --- |
| `graph.py` | Generic nodes, links, node attributes, and `GraphChange` notifications |
| `graph_index.py` | Derived `GraphAttributeIndex` (explicitly updated after graph changes) |
| `myutils/relations.py` | Reusable `ManyToOneRelation` |
| `base_engine.py` | Operator/provider contracts, graph/provider subscriptions, invalidation, and listener notifications; **no cache, Job, or execution runner** |
| `cache.py` | Reusable `CacheProtocol` and `MemoryCache`; not referenced by `BaseEngine` |
| `eager_engine.py` | Direct synchronous eager evaluation, local cache, and stale-result checking |
| `hybrid_engine.py` | Hybrid request/compute execution, context-aware cache, and `HybridJob` |
| `tests/` | In-memory provider test fixture and regression tests |

## Event semantics

`EngineChange(kind="executed", node=..., result=...)` means that an operator
successfully executed. It is emitted by the execution strategy as soon as the
result is produced; it does **not** mean that a cache stored the result.

Other event kinds: `started`, `failed`, `cache_hit`, `invalidated`. `HybridJob`
reports a compatible `JobEvent` containing a `job_id`, directly to the Engine's
listeners. `BaseEngine` has no knowledge of job IDs.

## Invalidation and caching

`BaseEngine.invalidate(nodes)` walks downstream dependencies in the live Graph.
It calls the protected `_on_invalidated(affected_nodes)` hook **before**
publishing `invalidated` notifications. Concrete engines use that hook to
remove their own cached results and record cache revisions; an engine with no
cache can simply leave the hook empty.

Both concrete engines capture graph/provider/cache snapshots when evaluation
starts. They cache successful results only when affected nodes are still live
and were not invalidated since evaluation began. They can still emit `executed`
for computations based on an earlier graph snapshot.

Provider object identity is fixed per engine. The provider may refresh the
operator implementations and emit `ProviderChange` notifications. The demo
in-memory provider lives only in `tests/test_engines.py`.

## Deliberate limitations

- Synchronous execution only; no universal Job contract.
- Graph snapshots copy the graph tables but do not deepcopy attribute values.
- In-place mutations to attribute values are not automatically observed.
- The graph does not enforce acyclicity (execution strategies detect cycles).
- Hybrid contextual values implement `select(context)` and `merge(other)`;
  `select` must raise `KeyError` when it cannot satisfy a context.
- Cache revision checks are local to the two concrete engines; this deliberately
  leaves a small amount of duplication rather than making the base engine
  responsible for cache policy.
