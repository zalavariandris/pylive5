"""Engine-owned cache policies preserve execution-local results and demand."""

import pytest
from qtpy.QtCore import QCoreApplication

from pygraphrt2 import Engine, Graph, NodeRef, Requestable
from pygraphrt2.engine import _CacheEntry
from pygraphrt2.execution_plan import ExecutionResult
from pygraphrt2.memory_cache import MemoryCache
from pygraphrt2.no_cache import NoCache
from PyGraphRT2.tests_ai.test_engine_subscriptions import RecordingBackend


@pytest.mark.parametrize("retain_nodes", [False, True])
@pytest.mark.parametrize("retain_requests", [False, True])
def test_cache_policies_preserve_execution_local_reuse(
    qapp: object, retain_nodes: bool, retain_requests: bool,
) -> None:
    graph = Graph()
    backend = RecordingBackend(graph)
    node_cache = MemoryCache() if retain_nodes else NoCache()
    request_cache = MemoryCache() if retain_requests else NoCache()
    engine = Engine(
        graph=graph, backend=backend,
        node_cache=node_cache, request_cache=request_cache,
    )
    engine.set_auto_execute(False)
    factories: list[int] = []
    computations: list[int] = []
    published: list[dict[NodeRef, object]] = []
    engine.nodes_executed.connect(published.append)

    class Source(Requestable):
        def __init__(self, base: int) -> None:
            factories.append(base)
            self.base = base

        def __call__(self, frame: int, *, scale: int) -> int:
            computations.append(frame)
            return self.base + frame * scale

    def render(video: Source, frame: int) -> tuple[int, int]:
        return video(frame, scale=2), video(frame, scale=2)

    source_node = engine.add_node(Source, args=(10,), name="source")
    left = engine.add_node(render, args=(source_node, 1), name="left")
    right = engine.add_node(render, args=(source_node, 1), name="right")
    try:
        assert engine._node_cache is node_cache
        assert engine._request_cache is request_cache
        engine.execute_nodes(left, right)
        backend.finish()
        assert factories == [10]
        assert computations == [1]
        assert published[-1][left] == published[-1][right] == (12, 12)

        engine.execute_nodes(left, right)
        backend.finish()
        assert factories == ([10] if retain_nodes else [10, 10])
        assert computations == ([1] if retain_nodes or retain_requests else [1, 1])
        assert published[-1][left] == published[-1][right] == (12, 12)

        # A changed consumer uses a new request on the same source.
        engine._graph._update_node(left, render, args=(source_node, 2))
        engine.execute_nodes(left)
        backend.finish()
        assert published[-1][left] == (14, 14)
        assert computations[-1] == 2

        # Revisiting a request reuses it only when request storage retains it.
        before = len(computations)
        engine._graph._update_node(left, render, args=(source_node, 1))
        engine.execute_nodes(left)
        backend.finish()
        assert len(computations) == before + (0 if retain_requests else 1)

        # Changing the factory invalidates its requests and both consumers.
        before = len(computations)
        engine._graph._update_node(source_node, Source, args=(20,))
        engine.execute_nodes(left, right)
        backend.finish()
        assert len(computations) == before + 1
        assert published[-1][left] == published[-1][right] == (22, 22)
    finally:
        engine.close()


def test_invalidation_removes_descendant_entries_and_requests(qapp: object) -> None:
    graph = Graph()
    engine = Engine(graph=graph, backend=RecordingBackend(graph))
    engine.set_auto_execute(False)
    source = engine.add_node(lambda: None, name="source")
    child = engine.add_node(lambda value: value, args=(source,), name="child")
    other = engine.add_node(lambda: 30, name="other")
    request = ((1,), (("scale", 2),))
    try:
        for node in (source, child, other):
            engine._node_cache.save(node, _CacheEntry(None, 0.5))
            engine._request_cache.save((node, request), _CacheEntry(None, 0.25))
            engine._request_cache.save((node, ()), _CacheEntry(20))
        snapshot = engine._request_cache.snapshot()

        engine._graph._update_node(source, lambda: 10)

        assert set(engine._node_cache) == {other}
        assert set(engine._request_cache) == {(other, request), (other, ())}
        assert engine._node_cache[other].value is None
        assert engine._node_cache[other].duration_seconds == 0.5
        assert engine._request_cache[other, request].duration_seconds == 0.25
        assert (source, request) in snapshot

        # Deletion also removes request entries when there is no node entry.
        engine._node_cache.remove(other)
        engine.remove_node(other)
        assert not engine._node_cache
        assert not engine._request_cache
    finally:
        engine.close()


def test_no_cache_subscriptions_only_run_when_requested(qapp: object) -> None:
    graph = Graph()
    backend = RecordingBackend(graph)
    engine = Engine(
        graph=graph, backend=backend, node_cache=NoCache(), request_cache=NoCache(),
    )
    received: list[object] = []
    node = engine.add_node(lambda: None, name="watched")
    try:
        engine.subscribe(node, received.append)
        QCoreApplication.processEvents()
        backend.finish()
        assert received == [None]
        assert not engine.pending_nodes()
        assert not engine._subscription_targets()

        unrelated = engine.add_node(lambda: 3, name="unrelated")
        QCoreApplication.processEvents()
        assert len(backend.executions) == 1

        engine.subscribe(unrelated, lambda _: None)
        QCoreApplication.processEvents()
        assert set(backend.plans[-1]) == {"unrelated"}
        backend.finish()
        assert received == [None]

        engine._graph._update_node(node, lambda: 2)
        QCoreApplication.processEvents()
        assert set(backend.plans[-1]) == {"watched"}
        backend.finish()
        QCoreApplication.processEvents()
        assert received == [None, 2]
        assert len(backend.executions) == 3
        assert not engine.pending_nodes()
        assert not engine._node_cache
        assert not engine._request_cache
    finally:
        engine.close()


def test_stale_results_do_not_repopulate_either_cache(qapp: object) -> None:
    graph = Graph()
    backend = RecordingBackend(graph)
    engine = Engine(graph=graph, backend=backend)
    engine.set_auto_execute(False)
    node = engine.add_node(lambda: 1, name="source")
    request = ((1,), ())
    try:
        engine.execute_nodes(node)
        stale = backend.executions[-1]
        stale.set_running_or_notify_cancel()
        engine._graph._update_node(node, lambda: 2)
        engine.execute_nodes(node)
        backend.finish()

        stale.set_result(ExecutionResult({"source": -1}, {("source", request): -1}))
        QCoreApplication.processEvents()

        assert engine._node_cache[node].value == 2
        assert not engine._request_cache
    finally:
        engine.close()
