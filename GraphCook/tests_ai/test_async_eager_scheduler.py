"""Exercise the async editor scheduler with Qt's event loop and its worker."""

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event

import pytest
from pytestqt.qtbot import QtBot
from qasync import QEventLoop
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication

from GraphCook.examples.qt_integration import async_eager_qdageditor2 as editor
from graphcook.core.execution_status import DirtyStatus, SucceededStatus
from graphcook.core.graph import Graph
from graphcook.eager_observable_engine import NodeId, NodeStatus, OperatorHandle
from qdageditor5.models.abstract_dag_model import NodeName


SCRIPT = 'def hello(greeting: str = "Hello"):\n    return f"{greeting} boom!"\n'


@pytest.fixture
def qt_loop(qapp: QApplication) -> Iterator[QEventLoop]:
    loop = QEventLoop(qapp)
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@pytest.fixture
def model(qt_loop: QEventLoop) -> Iterator[editor.EngineModel]:
    model = editor.EngineModel()
    model._execution_timer.setInterval(10)
    try:
        yield model
    finally:
        try:
            qt_loop.run_until_complete(wait_idle(model))
        finally:
            model.close()


async def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = asyncio.get_running_loop().time() + 3
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Scheduler did not reach the expected state")
        await asyncio.sleep(0.005)


async def wait_idle(model: editor.EngineModel) -> None:
    await wait_until(lambda: not (
        model._executing
        or model._draining
        or model._script_pending
        or model._graph_pending
        or model._execution_timer.isActive()
    ))


async def create_hello(model: editor.EngineModel) -> NodeName:
    model.script.setPlainText(SCRIPT)
    await wait_idle(model)
    node = model.create_node(OperatorHandle("hello"))
    await wait_idle(model)
    assert result(model, node) == "Hello boom!"
    return node


def result(model: editor.EngineModel, node: NodeName) -> object:
    status = model.graph._local_graph.attributes(node)["status"]
    assert isinstance(status, SucceededStatus)
    return status.value


@contextmanager
def pause_next_graph(
    monkeypatch: pytest.MonkeyPatch, *, fail: bool = False,
) -> Iterator[tuple[Event, Event]]:
    entered, release = Event(), Event()
    original = editor.Executor.execute_subgraph

    def execute(
        executor: editor.Executor, graph: Graph[NodeId],
    ) -> dict[NodeId, NodeStatus]:
        if not entered.is_set():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release the worker")
            if fail:
                raise ValueError("obsolete graph error")
        return original(executor, graph)

    with monkeypatch.context() as patch:
        patch.setattr(editor.Executor, "execute_subgraph", execute)
        try:
            yield entered, release
        finally:
            release.set()


def test_only_explicit_operator_columns_schedule_execution(
    model: editor.EngineModel, qt_loop: QEventLoop,
) -> None:
    async def scenario() -> None:
        node = await create_hello(model)
        messages: list[str] = []
        model.graphStatusChanged.connect(lambda message, error: messages.append(message))

        model.graph.nodesDataChanged.emit([node], [], [])
        model.graph.updateNodeStatus(node, DirtyStatus())
        assert not model._graph_pending
        assert not model._execution_timer.isActive()

        model.graph.nodesDataChanged.emit([node], [0], [])
        assert model._graph_pending
        await wait_idle(model)
        assert result(model, node) == "Hello boom!"
        assert messages.count("Executing graph...") == 1

    qt_loop.run_until_complete(scenario())


def test_inputs_and_topology_automatically_recompute(
    model: editor.EngineModel, qt_loop: QEventLoop,
) -> None:
    async def scenario() -> None:
        node = await create_hello(model)
        model.script.setPlainText(SCRIPT + '\ndef source(): return "Linked"\n')
        await wait_idle(model)
        source = model.create_node(OperatorHandle("source"))
        await wait_idle(model)
        assert result(model, source) == "Linked"

        messages: list[str] = []
        model.graphStatusChanged.connect(lambda message, error: messages.append(message))
        model.graph.setInletData(node, "greeting", "First", Qt.ItemDataRole.EditRole)
        model.graph.setInletData(node, "greeting", "Latest", Qt.ItemDataRole.EditRole)
        await wait_idle(model)
        assert result(model, node) == "Latest boom!"
        assert messages.count("Executing graph...") == 1

        link = (source, "out", node, "greeting")
        model.graph.addLinks([link])
        await wait_idle(model)
        assert result(model, node) == "Linked boom!"
        model.graph.removeLinks([link])
        await wait_idle(model)
        assert result(model, node) == "Latest boom!"

        model.graph.removeNodes([source])
        await wait_idle(model)
        assert list(model.graph.nodes()) == [node]
        assert messages.count("Executing graph...") == 4

    qt_loop.run_until_complete(scenario())


@pytest.mark.parametrize("fail", [False, True], ids=["result", "error"])
@pytest.mark.parametrize("change", ["input", "script"])
def test_busy_graph_discards_obsolete_response_and_reruns(
    model: editor.EngineModel, qt_loop: QEventLoop,
    monkeypatch: pytest.MonkeyPatch, fail: bool, change: str,
) -> None:
    async def scenario() -> None:
        node = await create_hello(model)
        published: list[object] = []
        messages: list[tuple[str, bool]] = []

        def record(nodes: list[NodeName], columns: list[int], roles: list[int]) -> None:
            if node in nodes and 1 in columns:
                status = model.graph._local_graph.attributes(node)["status"]
                if isinstance(status, SucceededStatus):
                    published.append(status.value)

        model.graph.nodesDataChanged.connect(record)
        model.graphStatusChanged.connect(lambda message, error: messages.append((message, error)))
        with pause_next_graph(monkeypatch, fail=fail) as (entered, release):
            model.graph.setInletData(node, "greeting", "Old", Qt.ItemDataRole.EditRole)
            await wait_until(entered.is_set)
            if change == "input":
                model.graph.setInletData(node, "greeting", "Latest", Qt.ItemDataRole.EditRole)
                expected = "Latest boom!"
            else:
                model.script.setPlainText(SCRIPT.replace('f"{greeting} boom!"', '"New script"'))
                expected = "New script"

            # Let another timer timeout occur while the first drain is awaiting the worker.
            await asyncio.sleep(0.03)
            release.set()
            await wait_idle(model)

        assert published == [expected]
        assert result(model, node) == expected
        assert not any(error for message, error in messages)
        assert messages.count(("Executing graph...", False)) == 2

    qt_loop.run_until_complete(scenario())


@pytest.mark.parametrize("script", ["def hello(", ""], ids=["invalid", "empty"])
def test_script_changes_clear_signatures_and_recover(
    model: editor.EngineModel, qt_loop: QEventLoop, script: str,
) -> None:
    async def scenario() -> None:
        node = await create_hello(model)
        messages: list[str] = []
        model.graphStatusChanged.connect(lambda message, error: messages.append(message))
        model.script.setPlainText(script)
        await wait_idle(model)
        assert model.operators.stringList() == []
        assert model.graph.nodeData(node, 0) == "-no op-"
        assert list(model.graph.inlets(node)) == []
        if script:
            assert not model._script_valid
            assert messages == []

        model.script.setPlainText(SCRIPT)
        await wait_idle(model)
        assert model._script_valid
        assert model.operators.stringList() == ["hello"]
        assert list(model.graph.inlets(node)) == ["greeting"]
        assert result(model, node) == "Hello boom!"

    qt_loop.run_until_complete(scenario())


@pytest.mark.parametrize("action_name", ["execute script", "execute graph"])
def test_menu_actions_queue_work_while_busy(
    model: editor.EngineModel, qt_loop: QEventLoop,
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, action_name: str,
) -> None:
    # Use the fixture's model in the real window so both share the same event loop.
    def create_model() -> editor.EngineModel:
        return model

    monkeypatch.setattr(editor, "EngineModel", create_model)
    window = editor.Window()
    qtbot.addWidget(window)
    action = next(action for action in window.edit_menu.actions() if action.text() == action_name)

    async def scenario() -> None:
        node = await create_hello(model)
        messages: list[str] = []
        model.graphStatusChanged.connect(lambda message, error: messages.append(message))
        with pause_next_graph(monkeypatch) as (entered, release):
            model.graph.setInletData(node, "greeting", "Busy", Qt.ItemDataRole.EditRole)
            await wait_until(entered.is_set)
            action.trigger()
            assert model._graph_pending
            assert model._script_pending == (action_name == "execute script")
            release.set()
            await wait_idle(model)

        assert result(model, node) == "Busy boom!"
        assert messages.count("Executing graph...") == 2

    qt_loop.run_until_complete(scenario())
