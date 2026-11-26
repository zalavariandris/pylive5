"""Script revisions survive repeated edits and drive the model's dirty status."""

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QStringListModel
from qtpy.QtGui import QTextDocument

from GraphCook.examples.qt_integration.async_eager_qdageditor import (
    AsyncEagerGraphModel,
    Window,
    Worker,
)
from graphcook.core.execution_status import DirtyStatus, SucceededStatus
from graphcook.core.graph import Graph
from graphcook.eager_observable_engine import NodeExecutionError, NodeId, OperatorHandle, OperatorSignature
from graphcook.observable_graph import ObservableGraph


@pytest.fixture
def worker() -> Iterator[Worker]:
    instance = Worker()
    instance.start()
    try:
        yield instance
    finally:
        instance.close()


async def load_script(worker: Worker, script: str) -> dict[OperatorHandle, OperatorSignature]:
    result = await asyncio.wait_for(worker.submit("execute_script", script), timeout=2)
    return cast(dict[OperatorHandle, OperatorSignature], result)


@pytest.mark.asyncio
async def test_revisions_increase_only_for_changed_functions(worker: Worker) -> None:
    initial = 'def name():\n    return "Ada"\ndef other():\n    return 1\n'
    formatted = '# A comment\n' + initial.replace('    return', '  return')
    changed = formatted.replace('"Ada"', '"Grace"')
    changed_again = changed.replace('"Grace"', '"Marie"')
    other_changed = changed_again.replace('return 1', 'return 2')
    submissions = [
        (initial, {"name": 0, "other": 0}),
        (initial, {"name": 0, "other": 0}),
        (formatted, {"name": 0, "other": 0}),
        (changed, {"name": 1, "other": 0}),
        (changed_again, {"name": 2, "other": 0}),
        (other_changed, {"name": 2, "other": 1}),
        (other_changed + '\n# Still unchanged\n', {"name": 2, "other": 1}),
        (initial, {"name": 3, "other": 2}),
    ]

    for script, expected in submissions:
        signatures = await load_script(worker, script)
        assert {handle.name: signature.revision for handle, signature in signatures.items()} == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("broken_script", "error"),
    [
        ('def name():\n    return "unfinished', SyntaxError),
        ('def name(): return "Rejected"\nraise RuntimeError("failed")', RuntimeError),
        ('def name() -> MissingType: return "Rejected"', NameError),
    ],
)
async def test_failed_script_preserves_revision_and_worker_recovers(
    worker: Worker, broken_script: str, error: type[Exception],
) -> None:
    handle = OperatorHandle("name")
    await load_script(worker, 'def name(): return "Ada"')
    current_script = 'def name(): return "Grace"'
    current = await load_script(worker, current_script)
    assert current[handle].revision == 1

    with pytest.raises(error):
        await load_script(worker, broken_script)

    assert worker.is_alive()
    assert worker._resolved_functions[handle]() == "Grace"
    assert await load_script(worker, current_script) == current
    recovered = await load_script(worker, 'def name(): return "Marie"')
    assert recovered[handle].revision == 2


@pytest.mark.asyncio
async def test_script_body_edits_mark_only_affected_nodes_dirty(
    qtbot: QtBot, worker: Worker,
) -> None:
    script = 'def name(): return "Ada"\ndef other(): return 1'
    document = QTextDocument(script)
    graph = ObservableGraph[NodeId]()
    window = SimpleNamespace(
        _config_graph=graph,
        _operator_signatures={},
        script_editor=SimpleNamespace(document=lambda: document),
        worker=worker,
        operator_list_model=QStringListModel(),
    )
    model = AsyncEagerGraphModel(graph, lambda handle: Window.operator_signature(window, handle))
    window.model = model
    handle = OperatorHandle("name")
    node = model.addNode(handle)
    other_node = model.addNode(OperatorHandle("other"))

    async def submit() -> None:
        await asyncio.wait_for(Window.submit_execute_script.__wrapped__(window), timeout=2)

    await submit()
    model.updateNodeStatus(other_node, SucceededStatus(value=1))
    for revision, name in enumerate(("Grace", "Marie"), start=1):
        model.updateNodeStatus(node, SucceededStatus(value="previous"))
        document.setPlainText(script.replace("Ada", name))
        await submit()
        assert window._operator_signatures[handle].revision == revision
        assert isinstance(model._node_status[node], DirtyStatus)
        assert isinstance(model._node_status[other_node], SucceededStatus)

    model.updateNodeStatus(node, SucceededStatus(value="Marie"))
    await submit()
    assert window._operator_signatures[handle].revision == 2
    assert isinstance(model._node_status[node], SucceededStatus)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        'def name(): return "Ada"\ndef greet(value): return "Hello " + value',
        'NAME = "Ada"\ndef name(): return NAME\ndef greet(value): return "Hello " + value',
    ],
)
async def test_script_changes_refresh_cached_nodes_and_downstream_results(
    worker: Worker, script: str,
) -> None:
    name = NodeId("name")
    greeting = NodeId("greeting")
    graph = Graph[NodeId]()
    graph.add_node(name, __operator__=OperatorHandle("name"), kwargs={})
    graph.add_node(greeting, __operator__=OperatorHandle("greet"), kwargs={})
    graph.add_link(name, greeting, "value")
    await load_script(worker, script)
    first = await asyncio.wait_for(worker.submit("execute_graph", graph), timeout=2)
    assert first == {name: "Ada", greeting: "Hello Ada"}

    # Execution may already be queued when the worker accepts the new script.
    _, second = await asyncio.wait_for(
        asyncio.gather(
            worker.submit("execute_script", script.replace("Ada", "Grace")),
            worker.submit("execute_graph", graph),
        ),
        timeout=2,
    )
    assert second == {name: "Grace", greeting: "Hello Grace"}


@pytest.mark.asyncio
async def test_unchanged_or_failed_scripts_preserve_cached_results(worker: Worker) -> None:
    script = 'def value(): return object()'
    node = NodeId("value")
    graph = Graph[NodeId]()
    graph.add_node(node, __operator__=OperatorHandle("value"), kwargs={})
    await load_script(worker, script)
    first = await asyncio.wait_for(worker.submit("execute_graph", graph), timeout=2)

    await load_script(worker, script)
    same = await asyncio.wait_for(worker.submit("execute_graph", graph), timeout=2)
    assert same[node] is first[node]

    with pytest.raises(SyntaxError):
        await load_script(worker, 'def value(')
    after_failure = await asyncio.wait_for(worker.submit("execute_graph", graph), timeout=2)
    assert after_failure[node] is first[node]


@pytest.mark.asyncio
async def test_removed_operator_cannot_return_cached_success(worker: Worker) -> None:
    node = NodeId("name")
    graph = Graph[NodeId]()
    graph.add_node(node, __operator__=OperatorHandle("name"), kwargs={})
    await load_script(worker, 'def name(): return "Ada"')
    await asyncio.wait_for(worker.submit("execute_graph", graph), timeout=2)

    await load_script(worker, '')
    with pytest.raises(NodeExecutionError) as failure:
        await asyncio.wait_for(worker.submit("execute_graph", graph), timeout=2)
    assert failure.value.node == node
    assert isinstance(failure.value.reason, KeyError)
