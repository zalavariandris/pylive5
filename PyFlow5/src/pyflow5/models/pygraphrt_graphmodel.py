from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from logging import warning
from pathlib import Path
from typing import Annotated, Iterable, Literal, override, Any, get_args, get_origin
import warnings

from pygraphrt2 import NodeRef
from pytools import UniqueNameGenerator

from qtpy.QtCore import (
    QObject, 
    Qt,
    Signal, Slot,
    QPointF
)
from qtpy.QtGui import QColor

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel,
    AddLinkMessage,
    AddNodeMessage,
    RemoveLinkMessage,
    RemoveNodeMessage,
    CellIdx, 
    DirectionalLinkId, 
    InletName, 
    NodeName, 
    OutletName
)

from ..core.input_roles import InputDataRole


import pygraphrt2 as rt2
from pygraphrt2.inline_executor import ExecutionFailure

from qdageditor5.core.item_data_roles import (
    NodeDataRole, SocketDataRole
)
import inspect

EmptyInletValue = object()


def _same_value(previous: object, current: object) -> bool:
    """Compare supported immutable values, including their types.

    Mutable or unfamiliar values are conservatively considered changed whenever
    the runtime notifies us, since retaining a reference cannot snapshot them.
    """
    if type(previous) is not type(current):
        return False
    
    if previous is EmptyInletValue or previous is rt2.ParameterData.EMPTY:
        return previous is current
    
    if isinstance(previous, tuple) and isinstance(current, tuple):
        return len(previous) == len(current) and all(
            _same_value(old, new) for old, new in zip(previous, current)
        )
    
    if (
        isinstance(previous, (type(None), bool, int, float, str, bytes, Path, Enum, type))
        or get_origin(previous) is not None
    ):
        try:
            equal = previous is current or previous == current
            return isinstance(equal, bool) and equal
        except Exception:
            return False
    return False


@dataclass(frozen=True, eq=False)
class _InletShadow:
    location: int | str
    parameter_name: str | None
    annotation: object
    default: object
    input: object
    connection: NodeName | None

    def same_data(self, other: "_InletShadow") -> bool:
        return (
            self.location == other.location
            and self.parameter_name == other.parameter_name
            and self.connection == other.connection
            and _same_value(self.annotation, other.annotation)
            and _same_value(self.default, other.default)
            and _same_value(self.input, other.input)
        )


@dataclass(frozen=True)
class _NodeShadow:
    operator_name: str | None
    operator_available: bool
    inlets: dict[InletName, _InletShadow]
    links: frozenset[DirectionalLinkId]


class PyGraphRTGraphModel(AbstractDAGModel):
    OutputRole = Qt.ItemDataRole.UserRole+1
    ResolutionRole = Qt.ItemDataRole.UserRole+2

    EmptyInputValue = EmptyInletValue

    def __init__(self, 
        engine: rt2.Engine
    ) -> None:
        super().__init__()
        self._engine = engine
        self._closed = False
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

        self._outputs: dict[NodeName, object|None] = {}
        self._errors: dict[NodeName, object|None] = {}
        self._operator_parameters_cache: dict[Callable[..., Any], Mapping[str, rt2.ParameterData]] = {}
        self._nodes: dict[NodeName, _NodeShadow] = {
            node.name(): self._make_node_shadow(node)
            for node in self._engine.graph.nodes()
        }

        self._connections = [
            (self._engine.graph.nodes_added, self._on_rt_nodes_added),
            (self._engine.graph.nodes_removed, self._on_rt_nodes_removed),
            (self._engine.graph.nodes_changed, self._on_rt_nodes_changed),
            (self._engine.registry.operators_added, self._on_registry_changed),
            (self._engine.registry.operators_removed, self._on_registry_changed),
            (self._engine.registry.operators_changed, self._on_registry_changed),
            (self._engine.nodes_invalidated, self._on_invalidated),
            (self._engine.nodes_executed, self._on_executed),
            (self._engine.execution_failed, self._on_failed),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)

    def _on_registry_changed(self, operators: list[rt2.ScriptOperatorRef]) -> None:
        if self._closed:
            return
        self._operator_parameters_cache.clear()
        self._on_rt_nodes_changed(self._engine.graph.nodes())

    @staticmethod
    def _operator_name(operator: Callable[..., Any] | None) -> str | None:
        if isinstance(operator, rt2.ScriptOperatorRef):
            return operator.name()
        return getattr(operator, "__name__", type(operator).__name__) if operator is not None else None

    @staticmethod
    def _operator_available(operator: Callable[..., Any] | None) -> bool:
        return operator.is_available() if isinstance(operator, rt2.ScriptOperatorRef) else operator is not None

    def _make_node_shadow(self, node_ref: rt2.NodeRef) -> _NodeShadow:
        node_state = node_ref.resolve()
        parameters = self._get_operator_parameters(node_state.operator) if node_state.operator is not None else {}
        inlet_names, bindings = self.__node_inlets(node_ref)
        inlets: dict[InletName, _InletShadow] = {}
        for position, inlet in enumerate(inlet_names):
            parameter = parameters.get(str(inlet))
            location, value = self._input_binding(inlet, position, node_state.args, node_state.kwargs)
            inlets[inlet] = _InletShadow(
                location=location,
                parameter_name=parameter.name if parameter is not None else None,
                annotation=parameter.annotation if parameter is not None else rt2.ParameterData.EMPTY,
                default=parameter.default if parameter is not None else rt2.ParameterData.EMPTY,
                input=self.EmptyInputValue if isinstance(value, NodeRef) else value,
                connection=value.name() if isinstance(value, NodeRef) else None,
            )

        return _NodeShadow(
            operator_name=self._operator_name(node_state.operator),
            operator_available=self._operator_available(node_state.operator),
            inlets=inlets,
            links=frozenset(
                (value.name(), 'out', node_ref.name(), inlet)
                for inlet, value in bindings if isinstance(value, NodeRef)
            ),
        )

    def _input_binding(
        self,
        inlet: InletName,
        position: int,
        args: tuple[object, ...],
        kwargs: Mapping[str, object],
    ) -> tuple[int | str, object]:
        if str(inlet) in kwargs:
            return str(inlet), kwargs[str(inlet)]
        if position < len(args):
            return position, args[position]
        return str(inlet), self.EmptyInputValue

    def _on_rt_nodes_added(self, nodes: list[rt2.NodeRef]) -> None:
        if self._closed:
            return
        if any(isinstance(msg, AddNodeMessage) for msg in self._message_queue):
            return  # addNode already owns the source notification pair.
        
        names = tuple(node_ref.name() for node_ref in nodes)
        self.nodesAboutToBeAdded.emit(names)
        for node_ref in nodes:
            self._nodes[node_ref.name()] = self._make_node_shadow(node_ref)
        self.nodesAdded.emit(names)

    def _on_rt_nodes_removed(self, nodes: list[rt2.NodeRef]) -> None:
        if self._closed:
            return
        if any(isinstance(msg, RemoveNodeMessage) for msg in self._message_queue):
            return  # removeNodes already owns the source notification pair.
        names = tuple(node.name() for node in nodes)
        
        self.nodesAboutToBeRemoved.emit(names)
        for name in names:
            self._nodes.pop(name, None)
            self._positions.pop(name, None)
            self._outputs.pop(name, None)
            self._errors.pop(name, None)
        self.nodesRemoved.emit(names)

    def _on_rt_nodes_changed(self, nodes: list[rt2.NodeRef]) -> None:
        if self._closed:
            return
        # Update the whole batch before notifying synchronous observers.
        changes: list[tuple[NodeName, _NodeShadow, _NodeShadow]] = []
        for node_ref in nodes:
            name = node_ref.name()
            previous = self._nodes[name]
            current = self._make_node_shadow(node_ref)
            self._nodes[name] = current
            changes.append((name, previous, current))

        changed_headers: list[NodeName] = []
        added_links: set[DirectionalLinkId] = set()
        removed_links: set[DirectionalLinkId] = set()
        for name, previous, current in changes:
            added_links.update(current.links - previous.links)
            removed_links.update(previous.links - current.links)
            if tuple(previous.inlets) != tuple(current.inlets):
                self.inletsReset.emit(name)
            else:
                changed_inlets = tuple(
                    inlet for inlet in current.inlets
                    if not previous.inlets[inlet].same_data(current.inlets[inlet])
                )
                if changed_inlets:
                    self.inletDataChanged.emit(name, changed_inlets, [])
            if (previous.operator_name, previous.operator_available) != (current.operator_name, current.operator_available):
                changed_headers.append(name)

        # Model commands already own their link notification pairs. Runtime
        # edits have committed, so use a reset for any remaining link changes
        # rather than issuing about-to notifications against the new graph.
        for message in self._message_queue:
            if isinstance(message, AddLinkMessage):
                added_links.difference_update(message.links)
            elif isinstance(message, RemoveLinkMessage):
                removed_links.difference_update(message.links)
        if added_links or removed_links:
            self.linksReset.emit()
        if changed_headers:
            self.nodesDataChanged.emit(
                tuple(changed_headers),
                (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole),
            )

    @Slot(dict)
    def _on_executed(self, outputs: dict[rt2.NodeRef, object|None]) -> None:
        if self._closed:
            return

        changed_nodenames: list[NodeName] = []
        for node_ref, execution in outputs.items():
            if node_name := self.mapFromSource(node_ref):
                self._errors.pop(node_name, None)
                self._outputs[node_name] = execution
                changed_nodenames.append(node_name)

        self.nodesDataChanged.emit(
            tuple(changed_nodenames),
            (self.OutputRole, NodeDataRole.TrailingRole, Qt.ItemDataRole.ForegroundRole),
        )

    def _notify_outputs_changed(self, names: list[NodeName]) -> None:
        if names:
            self.nodesDataChanged.emit(
                tuple(names),
                (self.OutputRole, NodeDataRole.TrailingRole, Qt.ItemDataRole.ForegroundRole),
            )

    def _on_invalidated(self, nodes: list[rt2.NodeRef]) -> None:
        if self._closed:
            return
        changed: list[NodeName] = []
        for node in nodes:
            name = node.name()
            if name in self._outputs or name in self._errors:
                self._outputs.pop(name, None)
                self._errors.pop(name, None)
                changed.append(name)
        self._notify_outputs_changed(changed)

    def _on_failed(self, error: Exception) -> None:
        if self._closed:
            return
        existing = set(self._engine.graph.nodes())
        if isinstance(error, ExecutionFailure):
            roots = set(error.targets)
            if error.node is not None:
                roots.add(error.node)
            failure = error.error
        else:
            roots = existing
            failure = error
        affected: set[rt2.NodeRef] = set()
        for node in roots & existing:
            affected.update(self._engine.graph.descendants(node))
        names = [node.name() for node in self._engine.graph.nodes() if node in affected]
        for name in names:
            self._outputs.pop(name, None)
            self._errors[name] = failure
        self._notify_outputs_changed(names)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self._operator_parameters_cache.clear()
        self._nodes.clear()
        self._outputs.clear()
        self._errors.clear()

    def _get_operator_parameters(
        self, operator: Callable[..., Any],
    ) -> Mapping[str, rt2.ParameterData]:
        if operator not in self._operator_parameters_cache:
            if isinstance(operator, rt2.ScriptOperatorRef):
                parameters = operator.get_parameters()
            else:
                parameters = {
                    name: rt2.ParameterData(name, parameter.annotation, parameter.default)
                    for name, parameter in inspect.signature(operator).parameters.items()
                }
            self._operator_parameters_cache[operator] = parameters
        return self._operator_parameters_cache[operator]

    def reset_graph_from_scratch(self) -> None:
        """Recover presentation state from the current runtime without changing it.

        Call after a failed mutation has unwound, not from a mutation signal handler.
        """
        node_names = {node.name() for node in self._engine.graph.nodes()}
        positions = {name: position for name, position in self._positions.items()
                     if name in node_names}
        # Recovery deliberately abandons notifications left open by a failed edit.
        self._message_queue.clear()
        self._beginResetModel()
        self._operator_parameters_cache.clear()
        self._positions = defaultdict(lambda: (0.0, 0.0), positions)
        self._nodes = {
            node_ref.name(): self._make_node_shadow(node_ref)
            for node_ref in self._engine.graph.nodes()
        }
        self._endResetModel()

    # = Mapping Source =
    def mapToSource(self, node_name:NodeName)->rt2.NodeRef|None:
        # todo: consider caching node references by name for faster lookup
        # find noderef by the name
        for node_ref in self._engine.graph.nodes():
            if node_ref.name() == node_name:
                return node_ref
        return None

    def mapFromSource(self, node_ref: rt2.NodeRef) -> NodeName | None:
        return node_ref.name() if node_ref is not None else None

    # OVERRIDES 
    # - READ
    @override
    def nodes(self)->Iterable[NodeName]: # type: ignore
        return [
            node_ref.name()
            for node_ref in self._engine.graph.nodes()
        ]

    @override
    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any: # type: ignore
        node_ref = self.mapToSource(node_name)
        if node_ref is None:
            return None
        node_state = node_ref.resolve()
        
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if op:=node_state.operator:
                    return self._operator_name(op)
                else:
                    return "-NoOp-"

            case Qt.ItemDataRole.BackgroundRole:
                if self._operator_available(node_state.operator):
                    return None
                else:
                    return QColor(200,20,20)

            case Qt.ItemDataRole.ForegroundRole:
                if node_name in self._errors:
                    return QColor("red")
                else:
                    return None

            case NodeDataRole.LeadingRole:
                return f"{node_ref.name()}"

            case NodeDataRole.TrailingRole:
                error = self._errors.get(node_name)
                if error:=self._errors.get(node_name):
                    return str(error)

                return None

            case self.OutputRole:
                if error:=self._errors.get(node_name):
                    return str(error)
                if node_name in self._outputs:
                    return self._outputs[node_name]
                else:
                    return None
            
            case _:
                return None

    @override
    def inlets(self, node:NodeName)->Iterable[InletName]: # type: ignore
        if node_ref := self.mapToSource(node):
            inlets, _ = self.__node_inlets(node_ref)
            yield from inlets

    def __node_inlets(
        self, node_ref: rt2.NodeRef,
    ) -> tuple[list[InletName], list[tuple[InletName, object]]]:
        """Return declared inlets and actual bindings, including invalid extras."""
        state = node_ref.resolve()
        op = state.operator
        parameters = list(self._get_operator_parameters(op)) if op is not None else []
        args, kwargs = state.args, state.kwargs
        bindings = []
        for i, value in enumerate(args):
            inlet = parameters[i] if i < len(parameters) else str(i + 1)
            # Arbitrary keyword names can also be numeric; keep extras distinct.
            if i >= len(parameters):
                while inlet in kwargs or inlet in parameters:
                    inlet = "#" + inlet
            bindings.append((inlet, value))
        bindings.extend(kwargs.items())
        inlets = list(dict.fromkeys([*parameters, *(name for name, _ in bindings)]))
        return inlets, bindings

    @override
    def outlets(self, node:NodeName)->Iterable[OutletName]:
        return ['out']
    
    @override
    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any: #type: ignore
        def get_parameter(node: NodeName, inlet: InletName) -> rt2.ParameterData | None:
            node_rt = self.mapToSource(node)
            if node_rt is None:
                return None
            
            operator_rt = node_rt.resolve().operator
            if operator_rt is None:
                return None

            param = self._get_operator_parameters(operator_rt).get(str(inlet))
            if param is None:
                return None

            return param

        match role:
            case Qt.ItemDataRole.EditRole:
                # -> str | int
                return inlet

            case Qt.ItemDataRole.DisplayRole:
                # -> str | None
                param = get_parameter(node, inlet)
                if param is None:
                    return f"{inlet}"

                # Display the inlet with its type annotation if available.
                annotation: Any = param.annotation
                if annotation is inspect.Parameter.empty:
                    return param.name
                
                if get_origin(annotation) is Annotated:
                    annotation = get_args(annotation)[0]

                if isinstance(annotation, type):
                    type_name = annotation.__name__
                else:
                    type_name = str(annotation)

                return f"{param.name}: {type_name}"

            case InputDataRole.AnnotationRole:
                param = get_parameter(node, inlet)
                annotation = param.annotation if param is not None else rt2.ParameterData.EMPTY
                if isinstance(annotation, str):
                    return {
                        "int": int, "float": float, "str": str, "bool": bool,
                        "Path": Path, "pathlib.Path": Path,
                    }.get(annotation)
                if annotation is not rt2.ParameterData.EMPTY:
                    return annotation

                value = self.inletData(node, inlet, InputDataRole.InputValueRole)
                if value is self.EmptyInputValue:
                    value = self.inletData(node, inlet, InputDataRole.DefaultValueRole)
                if value is self.EmptyInputValue:
                    return None
                return Path if isinstance(value, Path) else type(value)

            case InputDataRole.HasAnnotationRole:
                param = get_parameter(node, inlet)
                return param is not None and param.annotation is not rt2.ParameterData.EMPTY

            case (
                InputDataRole.InputLocationRole
                | InputDataRole.InputValueRole
                | InputDataRole.InputIsSetRole
                | InputDataRole.ConnectionRole
            ):
                node_rt = self.mapToSource(node)
                if node_rt is None:
                    return None
                inlets = list(self.inlets(node))
                if inlet not in inlets:
                    return None
                node_state = node_rt.resolve()
                position = inlets.index(inlet)
                location, value = self._input_binding(inlet, position, node_state.args, node_state.kwargs)

                if role == InputDataRole.InputLocationRole:
                    return location
                if role == InputDataRole.InputIsSetRole:
                    return value is not self.EmptyInputValue
                if role == InputDataRole.ConnectionRole:
                    return value.name() if isinstance(value, NodeRef) else None
                return self.EmptyInputValue if isinstance(value, NodeRef) else value

            case InputDataRole.IsUsingDefaultRole:
                return (
                    not self.inletData(node, inlet, InputDataRole.InputIsSetRole)
                    and self.inletData(node, inlet, InputDataRole.DefaultValueRole)
                    is not self.EmptyInputValue
                )

            case InputDataRole.DefaultValueRole:
                # -> object | None | self.EmptyInputValue
                param = get_parameter(node, inlet)
                if param is None:
                    return self.EmptyInputValue

                if param.default is inspect.Parameter.empty:
                    return self.EmptyInputValue

                return param.default

            case SocketDataRole.HiddenRole:
                # -> bool
                IsConnected = len(list(self.inLinks(node, inlet))) > 0 # todo: performance?
                if IsConnected:
                    return True
                HasDefaultValue = self.inletData(node, inlet, InputDataRole.DefaultValueRole) is not self.EmptyInputValue
                if HasDefaultValue:
                    return True
                return False
            
            case Qt.ItemDataRole.ToolTipRole: 
                # -> str | None
                node_rt = self.mapToSource(node)
                if node_rt is not None:
                    node_state = node_rt.resolve()
                    operator_rt = node_state.operator
                    if operator_rt is not  None:
                        if param := self._get_operator_parameters(operator_rt).get(str(inlet)):
                            return f"{param.name}: {param.annotation}"
                # fallback
                return f"{inlet}"

            case _:
                return None

    @override
    def outletData(self, node:NodeName, outlet:OutletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    # cells
    @override
    def nodeCellCount(self, node_name: NodeName) -> int:
        return 0

    @override
    def nodeCellData(self, node_name: NodeName, cell: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    @override
    def nodePosition(self, node_name:NodeName)->QPointF:
        if node_name in self._positions:
            x, y = self._positions[node_name]
            return QPointF(x, y)
        else:
            return QPointF(0.0, 0.0)

    @override
    def inLinks(self, node_name:NodeName, inlet_name:InletName)->Iterable[DirectionalLinkId]:
        if node_ref := self.mapToSource(node_name):
            for link in self.__node_input_links(node_ref):
                if link[3] == inlet_name:
                    yield link

    @override
    def outLinks(self, node:NodeName, outlet:OutletName)->Iterable[DirectionalLinkId]:
        # todo: fix performance here
        for link in self.links():
            source, source_outlet, target, inlet = link
            if source == node and source_outlet == outlet:
                yield link
        return []

    @override
    def links(self)->Iterable[DirectionalLinkId]:
        for node_ref in self._engine.graph.nodes():
            yield from self.__node_input_links(node_ref)

    @override
    def linkSource(self, link:DirectionalLinkId) -> tuple[NodeName|OutletName]|None:
        source, outlet, target, inlet = link
        return source, outlet

    @override
    def linkTarget(self, link:DirectionalLinkId) -> tuple[NodeName|InletName]|None:
        source, outlet, target, inlet = link
        return target, inlet

    def __node_input_links(self, node_ref: rt2.NodeRef)->Iterable[DirectionalLinkId]:
        _, bindings = self.__node_inlets(node_ref)
        for inlet, value in bindings:
            if isinstance(value, rt2.NodeRef):
                yield value.name(), 'out', node_ref.name(), inlet

    # - WRITES
    @override
    def setInletData( self, node: NodeName, inlet: InletName, value: object, role: int) -> bool: # type: ignore
        if role != InputDataRole.InputValueRole:
            return False
        node_rt = self.mapToSource(node)
        if node_rt is None:
            return False
        location = self.inletData(node, inlet, InputDataRole.InputLocationRole)
        if not isinstance(location, (int, str)):
            return False

        node_state = node_rt.resolve()
        args, kwargs = node_state.args, node_state.kwargs
        args, kwargs = list(args), dict(kwargs)
        if value is rt2.ParameterData.EMPTY or value is self.EmptyInputValue:
            if isinstance(location, int):
                args.pop(location)
            elif location in kwargs:
                del kwargs[location]
            else:
                return False
        else:
            if self.inletData(node, inlet, InputDataRole.ConnectionRole) is not None:
                return False
            if isinstance(value, rt2.NodeRef):
                return False  # Connections are edited through the graph's link API.

            annotation = self.inletData(node, inlet, InputDataRole.AnnotationRole)
            if get_origin(annotation) is Annotated:
                annotation = get_args(annotation)[0]
            value_type = tuple if get_origin(annotation) is tuple else annotation
            if not isinstance(value_type, type) or value_type is Any:
                return False
            try:
                if value_type is bool and isinstance(value, str):
                    if value.lower() not in ("true", "false"):
                        return False
                    value = value.lower() == "true"
                elif value_type is tuple and get_origin(annotation) is tuple:
                    if not isinstance(value, tuple):
                        return False
                    component_types = get_args(annotation)
                    if component_types and all(t in (int, float) for t in component_types):
                        if len(value) != len(component_types):
                            return False
                        value = tuple(t(item) for t, item in zip(component_types, value))
                elif issubclass(value_type, (int, float, str, Path, Enum)):
                    value = value_type(value)
                elif not isinstance(value, value_type):
                    return False
            except (TypeError, ValueError, OverflowError):
                return False

            if isinstance(location, int):
                args[location] = value
            else:
                kwargs[location] = value

        # Runtime notifications refresh the graph and all its adapters.
        node_state = node_rt.resolve()
        self._engine.graph._update_node(node_rt, node_state.operator, args, kwargs)
        return True

    @override
    def setNodePosition(self, node_name:NodeName, position:QPointF|None):
        self.nodeAboutToMove.emit(node_name)
        if position:
            self._positions[node_name] = (position.x(), position.y())
        else:
            self._positions.pop(node_name, None)
        self.nodeMoved.emit(node_name)

    # - MUTATIONS
    @override
    def removeLinks(self, links: Iterable[DirectionalLinkId]) -> bool:
        requested = tuple(dict.fromkeys(links))
        if not requested:
            return True
        existing = set(self.links())
        if any(link not in existing for link in requested):
            raise ValueError("Cannot remove a link that does not exist")

        # Resolve all locations before deleting any positional input.
        locations: dict[NodeName, set[int | str]] = defaultdict(set)
        for _, _, target, inlet in requested:
            locations[target].add(self.inletData(target, inlet, InputDataRole.InputLocationRole))
        updates = []
        for target, removed in locations.items():
            node = self.mapToSource(target)
            assert node is not None
            state = node.resolve()
            args = tuple(value for index, value in enumerate(state.args) if index not in removed)
            kwargs = {name: value for name, value in state.kwargs.items() if name not in removed}
            updates.append((node, state.operator, args, kwargs))

        self._beginRemoveLinks(requested)
        try:
            for node, operator, args, kwargs in updates:
                self._engine.graph._update_node(node, operator, args, kwargs)
        finally:
            self._endRemoveLinks()
        return True

    def removeNodes(self, nodes: Iterable[NodeName]) -> None:
        names = tuple(dict.fromkeys(nodes))
        if not names:
            return
        refs = [self.mapToSource(name) for name in names]
        if any(node is None for node in refs):
            raise ValueError("Cannot remove a node that does not exist")
        self._beginRemoveNodes(names)
        try:
            for node in refs:
                assert node is not None
                self._engine.graph._delete_node(node)
                name = node.name()
                self._nodes.pop(name, None)
                self._positions.pop(name, None)
                self._outputs.pop(name, None)
                self._errors.pop(name, None)
        finally:
            self._endRemoveNodes()

    def addLink(self, source: NodeName, outlet: OutletName, target: NodeName, inlet: InletName) -> None:
        target_ref = self.mapToSource(target)
        source_ref = self.mapToSource(source)
        if target_ref is None or source_ref is None:
            raise ValueError("Both link nodes must exist")
        if outlet not in self.outlets(source) or inlet not in self.inlets(target):
            raise ValueError("Both link sockets must exist")
        link = (source, outlet, target, inlet)
        if link in set(self.links()):
            return
        if target_ref in self._engine.graph.ancestors(source_ref):
            raise ValueError("A link cannot create a cycle")
        state = target_ref.resolve()
        location = self.inletData(target, inlet, InputDataRole.InputLocationRole)
        args, kwargs = list(state.args), dict(state.kwargs)
        if isinstance(location, int):
            args[location] = source_ref
        else:
            kwargs[location] = source_ref
        self._beginAddLinks([link])
        try:
            self._engine.graph._update_node(target_ref, state.operator, tuple(args), kwargs)
        finally:
            self._endAddLinks()

    def addNode(self, operator:rt2.ScriptOperatorRef, position:QPointF|None=None)->bool:
        """
        position: QPointF|None, in scene coordinates"""
        assert isinstance(operator, rt2.ScriptOperatorRef), f"operator must be an instance of AbstractOperator, got: {operator}"
        new_node_name = operator.name()
        node_names = [ref.name() for ref in self._engine.graph.nodes()]
        unique_name = UniqueNameGenerator(existing_names=node_names)(new_node_name)
        
        self._beginAddNodes([unique_name])
        new_node_ref = self._engine.graph._create_node(operator, name=unique_name)
        self._nodes[new_node_ref.name()] = self._make_node_shadow(new_node_ref)
        if position is not None:
            self._positions[new_node_ref.name()] = position.x(), position.y()
        self._endAddNodes()
        
        return True
