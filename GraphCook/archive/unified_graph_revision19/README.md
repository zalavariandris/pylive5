# PyGraph architecture sketch

Python 3.11+. Run `python example.py` or `python -m unittest discover -s tests -v` from this directory.

- `graph.py`: generic node/link storage and observable `GraphChange` with three independent fields: `nodes: SetChanges[NodeT]`, `links: SetChanges[Link[NodeT]]`, and `attributes: Mapping[NodeT, MappingChanges[str, object]]`. `MappingChanges` tracks `added`, `removed`, and `changed` keys; `ValueChange` records old/new values. No missing-value sentinel is needed for graph attributes. Nodes added/removed carry membership notifications only; their entire attribute dictionaries are not repeated in the delta. The outer and inner change mappings are read-only snapshots.
- `graph_index.py`: generic `GraphAttributeIndex` keeps a `ManyToOneRelation` in sync with one typed graph attribute; the owner calls `update(change)` explicitly after each graph change.
- `base_engine.py`: shared `__operator__` convention, provider snapshots, graph-attribute index ownership, cache coordination, invalidation, job/engine events, stale-result protection. A provider instance is fixed per engine; the provider can refresh its own implementations and emit `ProviderChange`.
- `cache.py`: `CacheProtocol` and `MemoryCache` (storage abstraction and default in-memory implementation).
- `eager_engine.py`: dependency-first eager execution of callables.
- `hybrid_engine.py`: request/compute two-phase execution with nested on-demand pulls and contextual value merge/select.
- `myutils/relations.py`: a self-contained copy of `ManyToOneRelation`; replace with your existing `myutils` package if preferred.
- `tests/test_engines.py`, `tests/test_graph_events_and_index.py`: executable regression tests for both strategies, graph events and derived indexing.
- `example.py`: runnable examples of both strategies.

Deliberate limits: synchronous jobs; graph/provider/cache snapshots copy mappings but not their values; in-place mutation of attribute values is not observable; graph does not enforce acyclicity; no static-Python-authoring-to-dynamic-graph reconciliation; no provider AST/interface descriptions yet. `HybridEngine` expects context objects implementing `merge`, and value objects implementing `merge` and `select` (`select` raises `KeyError` for missing coverage). It conservatively recomputes requested contexts when partial cache coverage is insufficient. `GraphAttributeIndex` only indexes non-`None`, hashable values matching its `value_type`.
