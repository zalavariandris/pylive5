from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from logging import warning
from pathlib import Path
from typing import Annotated, Iterable, override, Any, get_args, get_origin
import warnings

from pygraphrt.graph_definition_rt import NodeRef
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

import pygraphrt as rt

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
    if previous is EmptyInletValue or previous is rt.ParameterData.EMPTY:
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
    inlets: dict[InletName, _InletShadow]
    links: frozenset[DirectionalLinkId]


class PyGraphRTGraphModel(AbstractDAGModel):
    ExecutionRole = Qt.ItemDataRole.UserRole+1
    ResolutionRole = Qt.ItemDataRole.UserRole+2

    EmptyInputValue = EmptyInletValue

    def __init__(self, 
        engine: rt.GraphEngine
    ) -> None:
        super().__init__()
        self._engine = engine
        self._closed = False
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

        self._executions: dict[NodeName, rt.NodeExecution] = {}
        self._operator_parameters_cache: dict[rt.AbstractOperator, Mapping[str, rt.ParameterData]] = {}
        self._nodes: dict[NodeName, _NodeShadow] = {
            node.get_name(): self._make_node_shadow(node)
            for node in self._engine._graph.nodes()
        }

        # Adapters observe this model, including changes made directly to the RT.
        self._engine._graph.nodes_added.connect(self._on_rt_nodes_added)
        self._engine._graph.nodes_removed.connect(self._on_rt_nodes_removed)
        self._engine._graph.nodes_changed.connect(self._on_rt_nodes_changed)
        for signal in (
            self._engine._registry.modules_added,
            self._engine._registry.modules_removed,
            self._engine._registry.operators_added,
            self._engine._registry.operators_removed,
            self._engine._registry.operators_changed,
        ):
            signal.connect(self._on_registry_changed)


        self._engine.evaluated.connect(self._on_evaluated)

    def _make_node_shadow(self, node: rt.NodeRef) -> _NodeShadow:
        operator = node.get_operator()
        parameters = self._get_operator_parameters(operator) if operator is not None else {}
        inlet_names, bindings = self.__node_inlets(node)
        args, kwargs = node.get_inputs()
        inlets: dict[InletName, _InletShadow] = {}
        for position, inlet in enumerate(inlet_names):
            parameter = parameters.get(str(inlet))
            location, value = self._input_binding(inlet, position, args, kwargs)
            inlets[inlet] = _InletShadow(
                location=location,
                parameter_name=parameter.name if parameter is not None else None,
                annotation=parameter.annotation if parameter is not None else rt.ParameterData.EMPTY,
                default=parameter.default if parameter is not None else rt.ParameterData.EMPTY,
                input=self.EmptyInputValue if isinstance(value, NodeRef) else value,
                connection=value.get_name() if isinstance(value, NodeRef) else None,
            )
        return _NodeShadow(
            operator_name=operator.get_name() if operator is not None else None,
            inlets=inlets,
            links=frozenset(
                (value.get_name(), 'out', node.get_name(), inlet)
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

    def _on_rt_nodes_added(self, nodes: list[rt.NodeRef]) -> None:
        if self._closed:
            return
        for node in nodes:
            self._nodes[node.get_name()] = self._make_node_shadow(node)
        if any(isinstance(msg, AddNodeMessage) for msg in self._message_queue):
            return  # addNode already owns the source notification pair.
        names = tuple(node.get_name() for node in nodes)
        self.nodesAboutToBeAdded.emit(names)
        self.nodesAdded.emit(names)

    def _on_rt_nodes_removed(self, nodes: list[rt.NodeRef]) -> None:
        if self._closed:
            return
        names = tuple(node.get_name() for node in nodes)
        for name in names:
            self._nodes.pop(name, None)
            self._positions.pop(name, None)
            self._executions.pop(name, None)
        if any(isinstance(msg, RemoveNodeMessage) for msg in self._message_queue):
            return  # removeNodes already owns the source notification pair.
        self.nodesAboutToBeRemoved.emit(names)
        self.nodesRemoved.emit(names)

    def _on_rt_nodes_changed(self, nodes: list[rt.NodeRef]) -> None:
        if self._closed:
            return
        # Update the whole batch before notifying synchronous observers.
        changes: list[tuple[NodeName, _NodeShadow, _NodeShadow]] = []
        for node in nodes:
            name = node.get_name()
            previous = self._nodes[name]
            current = self._make_node_shadow(node)
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
            if previous.operator_name != current.operator_name:
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
    def _on_evaluated(self, executions: dict[rt.NodeRef, rt.NodeExecution]) -> None:
        if self._closed:
            return

        changed_nodenames: list[NodeName] = []
        for node_ref, execution in executions.items():
            if node_name := self.mapFromSource(node_ref):
                self._executions[node_name] = execution
                changed_nodenames.append(node_name)

        self.nodesDataChanged.emit(
            tuple(changed_nodenames),
            (self.ExecutionRole, NodeDataRole.TrailingRole, Qt.ItemDataRole.ForegroundRole),
        )

    def close(self) -> None:
        """Disconnect evaluation callbacks when the document is closed."""
        if self._closed:
            return
        self._closed = True
        self._operator_parameters_cache.clear()
        self._nodes.clear()
        self._engine.evaluated.disconnect(self._on_evaluated)

    @Slot(list)
    def _on_registry_changed(self, _changes: list[object]) -> None:
        if self._closed:
            return
        # Synchronous UI observers must see the new parameter definitions.
        self._operator_parameters_cache.clear()
        self._on_rt_nodes_changed(self._engine._graph.nodes())

    def _get_operator_parameters(
        self, operator: rt.AbstractOperator
    ) -> Mapping[str, rt.ParameterData]:
        """Reuse parameter metadata across snapshots, UI queries, and input edits."""
        if operator not in self._operator_parameters_cache:
            self._operator_parameters_cache[operator] = operator.get_parameters()
        return self._operator_parameters_cache[operator]

    def reset_graph_from_scratch(self) -> None:
        """Recover presentation state from the current runtime without changing it.

        Call after a failed mutation has unwound, not from a mutation signal handler.
        """
        node_names = {node.get_name() for node in self._engine._graph.nodes()}
        positions = {name: position for name, position in self._positions.items()
                     if name in node_names}
        # Recovery deliberately abandons notifications left open by a failed edit.
        self._message_queue.clear()
        self._beginResetModel()
        self._operator_parameters_cache.clear()
        self._positions = defaultdict(lambda: (0.0, 0.0), positions)
        self._nodes = {
            node.get_name(): self._make_node_shadow(node)
            for node in self._engine._graph.nodes()
        }
        self._endResetModel()

    # = Mapping Source =
    def mapToSource(self, node_name:NodeName)->rt.NodeRef|None:
        # todo: consider caching node references by name for faster lookup
        # find noderef by the name
        for node_ref in self._engine._graph.nodes():
            if node_ref.get_name() == node_name:
                return node_ref
        return None

    def mapFromSource(self, node_ref: rt.NodeRef) -> NodeName | None:
        return node_ref.get_name() if node_ref is not None else None

    # OVERRIDES 
    # - READ
    @override
    def nodes(self)->Iterable[NodeName]:
        return [
            self.mapFromSource(node_ref)
            for node_ref in self._engine._graph.nodes()
        ]

    @override
    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_ref = self.mapToSource(node_name)
        if node_ref is None:
            return None
        
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if op:=node_ref.get_operator():
                    return op.get_name()
                else:
                    return "-NoOp-"

            case Qt.ItemDataRole.BackgroundRole:
                if op:=node_ref.get_operator():
                    return None
                else:
                    return QColor(200,20,20)

            case Qt.ItemDataRole.ForegroundRole:
                execution = self._executions.get(node_name)
                if isinstance(execution, rt.ExecutionFailure):
                    return QColor("red")
                return None

            case NodeDataRole.LeadingRole:
                return f"{node_ref.get_name()}"

            case NodeDataRole.TrailingRole:
                execution = self._executions.get(node_name)
                if isinstance(execution, rt.ExecutionFailure):
                    return str(execution.reason)

                if isinstance(execution, rt.ExecutionSuccess):
                    duration_ms = execution.duration_ms
                    if duration_ms is not None:
                        text = f"{duration_ms:.2f} ms"
                        return f"({text})" if execution.cached else text
                return None

            case self.ExecutionRole:
                if node_name in self._executions:
                    match self._executions.get(node_name):
                        case rt.ExecutionBlocked():
                            return None
                        case rt.ExecutionSuccess() as success:
                            return success.result
                        case rt.ExecutionFailure() as failure:
                            the_exception = failure.reason
                            return failure.reason
                        case _:
                            return None
                else:
                    warnings.warn(f"No execution result for node: '{node_name}'")
                    return None
            
            case _:
                return None

    @override
    def inlets(self, node:NodeName)->Iterable[InletName]:
        if node_ref := self.mapToSource(node):
            inlets, _ = self.__node_inlets(node_ref)
            yield from inlets

    def __node_inlets(self, node_ref: rt.NodeRef):
        """Return declared inlets and actual bindings, including invalid extras."""
        op = node_ref.get_operator()
        parameters = list(self._get_operator_parameters(op)) if op is not None else []
        args, kwargs = node_ref.get_inputs()
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
    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        def get_parameter(node: NodeName, inlet: InletName) -> rt.ParameterData | None:
            node_rt = self.mapToSource(node)
            if node_rt is None:
                return None
            
            operator_rt = node_rt.get_operator()
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
                annotation = param.annotation if param is not None else rt.ParameterData.EMPTY
                if isinstance(annotation, str):
                    return {
                        "int": int, "float": float, "str": str, "bool": bool,
                        "Path": Path, "pathlib.Path": Path,
                    }.get(annotation)
                if annotation is not rt.ParameterData.EMPTY:
                    return annotation

                value = self.inletData(node, inlet, InputDataRole.InputValueRole)
                if value is self.EmptyInputValue:
                    value = self.inletData(node, inlet, InputDataRole.DefaultValueRole)
                if value is self.EmptyInputValue:
                    return None
                return Path if isinstance(value, Path) else type(value)

            case InputDataRole.HasAnnotationRole:
                param = get_parameter(node, inlet)
                return param is not None and param.annotation is not rt.ParameterData.EMPTY

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
                args, kwargs = node_rt.get_inputs()
                position = inlets.index(inlet)
                location, value = self._input_binding(inlet, position, args, kwargs)

                if role == InputDataRole.InputLocationRole:
                    return location
                if role == InputDataRole.InputIsSetRole:
                    return value is not self.EmptyInputValue
                if role == InputDataRole.ConnectionRole:
                    return value.get_name() if isinstance(value, NodeRef) else None
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
                    operator_rt = node_rt.get_operator()
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
            source, outlet, target, inlet = link
            if source == node and outlet == outlet:
                yield link
        return []

    @override
    def links(self)->Iterable[DirectionalLinkId]:
        for node_ref in self._engine._graph.nodes():
            yield from self.__node_input_links(node_ref)

    @override
    def linkSource(self, link:DirectionalLinkId) -> tuple[NodeName|OutletName]|None:
        source, outlet, target, inlet = link
        return source, outlet

    @override
    def linkTarget(self, link:DirectionalLinkId) -> tuple[NodeName|InletName]|None:
        source, outlet, target, inlet = link
        return target, inlet

    def __node_input_links(self, node_ref: rt.NodeRef)->Iterable[DirectionalLinkId]:
        _, bindings = self.__node_inlets(node_ref)
        for inlet, value in bindings:
            if isinstance(value, rt.NodeRef):
                yield value.get_name(), 'out', node_ref.get_name(), inlet

    # - WRITES
    @override
    def setInletData(
        self,
        node: NodeName,
        inlet: InletName,
        value: object,
        role: int,
    ) -> bool:
        if role != InputDataRole.InputValueRole:
            return False
        node_rt = self.mapToSource(node)
        if node_rt is None:
            return False
        location = self.inletData(node, inlet, InputDataRole.InputLocationRole)
        if not isinstance(location, (int, str)):
            return False

        args, kwargs = node_rt.get_inputs()
        args, kwargs = list(args), dict(kwargs)
        if value is rt.ParameterData.EMPTY or value is self.EmptyInputValue:
            if isinstance(location, int):
                args.pop(location)
            elif location in kwargs:
                del kwargs[location]
            else:
                return False
        else:
            if self.inletData(node, inlet, InputDataRole.ConnectionRole) is not None:
                return False
            if isinstance(value, NodeRef):
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
        node_rt.set_inputs(*args, **kwargs)
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
    def removeLinks(self, links:Iterable[DirectionalLinkId])->bool:
        self._beginRemoveLinks(links)
        for link in list(links):
            source, outlet, target, inlet = link
            target_rt:rt.NodeRef = self.mapToSource(target)
            args, kwargs = target_rt.get_inputs()
            op = target_rt.get_operator()
            inlets = self._get_operator_parameters(op).keys()
            if inlet not in inlets:
                continue

            inlet_idx = list(inlets).index(inlet)
            if inlet_idx < len(args):
                new_args = [
                    arg 
                    for arg in args 
                    if not arg.get_name() == source
                ]
                target_rt.set_inputs(*new_args, **kwargs)

            elif inlet in kwargs:
                new_kwargs = {
                    k: v 
                    for k, v in kwargs.items() 
                    if not (k == inlet and isinstance(v, rt.NodeRef) and v.get_name() == source)
                }
                target_rt.set_inputs(*args, **new_kwargs)

        self._endRemoveLinks() # todo: check if QAbstractItemModel return values for these kind of methods
        return True

    def removeNodes(self, nodes:Iterable[NodeName]):
        self._beginRemoveNodes(nodes)
        for node_name in list(nodes):
            node_ref = self.mapToSource(node_name)
            assert node_ref is not None, f"Node '{node_name}' not found"

            self._engine._graph._delete_node(node_ref)
            self._positions.pop(node_name, None)
        self._endRemoveNodes()

    def addLink(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName)->None:
        self._beginAddLinks([(source, outlet, target, inlet)])
        target_ref = self.mapToSource(target)
        source_ref = self.mapToSource(source)
        assert target_ref is not None, f"Target node '{target}' not found"
        assert source_ref is not None, f"Source node '{source}' not found"
        args, kwargs = target_ref.get_inputs()
        op_ref = target_ref.get_operator()

        # if there are already positional arguments for this inlet, replace that otherwise add it to keyword arguments
        inlets = list(self._get_operator_parameters(op_ref))
        if inlet not in inlets:
            print(f"Inlet '{inlet}' not found in operator parameters")
            return
        inlet_idx = inlets.index(inlet)

        new_args = list(args)
        new_kwargs = dict(kwargs)
        if inlet_idx < len(args):
            new_args[inlet_idx] = source_ref
        else:
            new_kwargs[inlet] = source_ref

        target_ref.set_inputs(*new_args, **new_kwargs)
        print(f"Updated inputs for target node '{target}': args={new_args}, kwargs={new_kwargs}")
        self._endAddLinks()

    def addNode(self, operator:rt.AbstractOperator, position:QPointF|None=None)->bool:
        """
        position: QPointF|None, in scene coordinates"""
        assert isinstance(operator, rt.AbstractOperator), f"operator must be an instance of AbstractOperator, got: {operator}"
        new_node_name = operator.get_name()
        node_names = [ref.get_name() for ref in self._engine._graph.nodes()]
        unique_name = UniqueNameGenerator(existing_names=node_names)(new_node_name)
        self._beginAddNodes([unique_name])
        new_node_ref = self._engine._graph._create_node(operator, name=unique_name)
        if position:
            self._positions[new_node_ref.get_name()] = position.x(), position.y()
        self._endAddNodes()
        
        return True
