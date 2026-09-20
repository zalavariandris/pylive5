from .graph_rt import GraphRT, NodeRef
from .abstract_module_rt import OperatorRef
from typing import Callable, Iterable
import weakref


class Watcher:
	def __init__(self, graph: GraphRT, node: NodeRef, callback: Callable[[], None]):
		assert isinstance(graph, GraphRT), f"graph must be an instance of GraphRT got {graph}"
		assert isinstance(node, NodeRef), f"node must be an instance of NodeRef got {node}"
		assert callable(callback), f"callback must be callable got {callback}"
		
		if node not in graph._nodes:
			raise ValueError(f"Node {node} is not part of the graph.")
		
		self._graph = weakref.ref(graph)
		self._node = weakref.ref(node)
		self._callback = callback

		self._ancestors = [n for n in graph.ancestors(node)]

		self._graph_connections = [
			(graph.nodes_changed, self._on_nodes_changed),
			(graph.nodes_removed, self._on_nodes_removed),
		]

		operator = self._node().get_operator()
		module = operator.module
		self._module_connections = [
			(module.operators_changed, self._on_operators_changed),
			(module.operators_removed, self._on_operators_removed),
		]

		self._running = False

		self.start()

	def start(self):
		if self._running:
			return
		
		for signal, slot in self._graph_connections:
			signal.connect(slot)

		for signal, slot in self._module_connections:
			signal.connect(slot)

		self._running = True

	def stop(self):
		if not self._running:
			return
		for signal, slot in self._graph_connections:
			signal.disconnect(slot)
		for signal, slot in self._module_connections:
			signal.disconnect(slot)
		self._running = False

	def _on_nodes_changed(self, nodes: Iterable[NodeRef]):
		if set(self._ancestors) & set(nodes):
			self._ancestors = [node for node in self._graph().ancestors(self._node())]
			# Disconnect existing module connections before reconnecting to the updated module.
			for signal, slot in self._module_connections:
				signal.disconnect(slot)

			operator = self._node().get_operator()
			module = operator.module

			self._module_connections = [
				(module.operators_changed, self._on_operators_changed),
				(module.operators_removed, self._on_operators_removed),
			]
			for signal, slot in self._module_connections:
				signal.connect(slot)

			self._callback()

	def _on_nodes_removed(self, node_name: str):
		self.stop()

	def _on_operators_changed(self, changed_operators: list[str | OperatorRef]):
		ancestor_operators = set()

		for node in self._graph().ancestors(self._node()):
			operator = node.get_operator()
			if operator is not None:
				ancestor_operators.add(operator)

		# Local modules emit references; script modules emit names.
		if any(
			operator in changed_operators or operator.name in changed_operators
			for operator in ancestor_operators
		):
			self._callback()

	def _on_operators_removed(self, removed_operators: list[str | OperatorRef]):
		if self._node() is None:
			return
		if self._node().get_operator() is None:
			return

		operator = self._node().get_operator()
		if operator in removed_operators or operator.name in removed_operators:
			self.stop()

	

	def __del__(self):
		try:
			if getattr(self, "_running", False):
				self.stop()
		except (TypeError, RuntimeError):
			# Qt may already have disconnected slots or destroyed their senders.
			pass

def watch(graph:GraphRT, node:NodeRef|None, callback: Callable):
	"""Watches the given graph for changes and calls the callback with the change details."""
	assert isinstance(graph, GraphRT)
	assert isinstance(node, NodeRef), f"node must be an instance of NodeRef got {node}"
	return Watcher(graph, node, callback)
