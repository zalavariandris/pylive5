from typing import Iterable, Tuple, Any, TYPE_CHECKING

from .graph import Graph, NodeRef

from typing import Iterable, Tuple, Any


class AsyncExecutor:
    def __init__(self, graph:'Graph'):
        self.graph = graph

    async def execute(self, node_ref:'NodeRef')->dict['NodeRef', Any]:
        sorted_nodes = self.graph.topological_sort()

        outputs: dict['NodeRef', Any] = {}

        for node in sorted_nodes:
            node_state = node.resolve()
            resolved_args = [
                outputs[arg] if isinstance(arg, NodeRef) else arg 
                for loc, arg in enumerate(node_state.args)
            ]
            resolved_kwargs = {
                loc: outputs[arg] if isinstance(arg, NodeRef) else arg
                for loc, arg in node_state.kwargs.items()
            }
            op = node_state.operator
            if op is None:
                raise ValueError(f"Operator for node {node} is not resolved.")
            
            output = op(*resolved_args, **resolved_kwargs)
            outputs[node] = output

        return outputs

if __name__ == "__main__":
    import asyncio
    from pygraphrt2.graph import Graph, NodeRef
    import asyncio
    import time

    async def main():

        graph = Graph()
        @graph.node()
        def some_sleep():
            print("Execute sleep for 1 second...")
            time.sleep(1)
            print("Awake now.")
            return "Hello"

        executor = AsyncExecutor(graph)
        outputs = await executor.execute(some_sleep)
        print(outputs)

    asyncio.run(main())
    