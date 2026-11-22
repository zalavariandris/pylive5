from typing import TypeVar
from graphcook.core import (
    Graph, 
    NodeId, 
    OPERATOR_ATTRIBUTE, 
    OperatorHandle, 
    Link, 
    _execute_provider, 
    _execute_graph
)

from graphcook.core.cache import MemoryCache


class DAG(Graph[NodeId]):
    def create_node(self, operator, **inputs) -> NodeId:
        node_id = NodeId(operator)
        self.add_node(node_id, {OPERATOR_ATTRIBUTE: OperatorHandle(operator), **inputs})
        return node_id

    def set(self, node_id: NodeId, **inputs) -> None:
        # also add links for any inputs that are NodeIds
        for key, value in inputs.items():
            if isinstance(value, NodeId):
                super().add_link(Link(value, "", node_id, key))  # Example link, adjust as needed
        super().set(node_id, **inputs)

    def unset(self, node_id: NodeId, inlet) -> None:
        # also remove any links associated with this inlet before unsetting it
        for link in self.in_links(node_id):
            if link.inlet == inlet:
                super().remove_link(link)
        super().unset(node_id, inlet)

    def add_link(self, link: Link[NodeId]) -> None:
        super().add_link(link)
        # also set inputs
        self.set(link.target, **{link.inlet: link.source})

    def remove_link(self, link: Link[NodeId]) -> None:
        super().remove_link(link)
        # also unset inputs
        self.unset(link.target, link.inlet)


from threading import Thread
from queue import Queue
class Worker(Thread):
    def __init__(self):
        super().__init__()
        self._cache = MemoryCache()
        self._tasks = Queue()

    def run(self):
        # init

        # process tasks
        try:
            while True:
                # wait for the next task
                task = self._tasks.get()

                if task is None:
                    break

                operation, future = task

                if not future.set_running_or_notify_cancel():
                    continue

                try:
                    future.set_result(operation(self._cache, None))
                except BaseException as exc:
                    future.set_exception(exc)
        finally:
            self.close()

    def submit(self, func):
        from concurrent.futures import Future
        future = Future()
        self._tasks.put((func, future))
        return future

    def execute_provider(self, script):
        future = self.submit(lambda cache: 
            _execute_provider(script)
        )
        return future

    def execute_graph(self, graph):
        future = self.submit(lambda cached_operators, cached_results, cache=None: 
            _execute_graph(graph, cached_operators, cache=cached_results)
        )
        return future

    def close(self):
        # signal the thread to exit
        self._tasks.put(None)
        self.join()

    def __del__(self):
        self.close()

if __name__ == "__main__":
    from textwrap import dedent
    script = dedent("""
    def the_name():
        pass
        
    def the_greeting():
        pass
        
    def hello_world(name:str, greeting:str='Hello'):
        return f"{greeting}, {name}!"
    """)
    graph = DAG()
    operators = _execute_provider(script)
    the_name = graph.create_node(OperatorHandle("the_name"))
    the_greeting = graph.create_node(OperatorHandle("the_greeting"))
    graph.create_node(OperatorHandle("hello_world"), name=the_name, greeting=the_greeting)

    results = _execute_graph(graph, operators, cache=None, callback=None)
    revision = 0
    def update_worker(change):
        if 'script' in change:
            revision += 1
            future = worker.execute_provider(change['script'], revision=revision)
            # we might want to copy the graph here to avoid race conditions
            future.add_done_callback(lambda _: worker.execute_graph(graph, revision=revision))

        if 'graph' in change:
            # we might want to copy the graph here to avoid race conditions
            worker.execute_graph(graph, revision=revision+1)
            revision += 1
            worker.execute_graph(graph, revision=revision)

    graph.listen(update_worker)

    worker = Worker()
    worker.start()

    def update_ui(change):

        if 'provider_status' in change:
            ...

        if 'operators' in change:
            ...

        if 'nodes_status' in change:
            match change['nodes_status']:
                case SuccessStatus():
                    ...
                case ProgressStatus():
                    ...
                case DirtyStatus():
                    ...
                case FailedStatus():
                    ...

    worker.listen(update_ui)
    worker.execute_provider(script)
    worker.execute_graph(graph)
