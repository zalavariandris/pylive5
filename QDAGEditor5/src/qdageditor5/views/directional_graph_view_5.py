
from __future__ import annotations
from argparse import Action
from re import match
from re import match
import warnings
from collections import defaultdict
from functools import reduce
from typing import *
from enum import Enum
from dataclasses import dataclass

from qdageditor5.utils.graph_layouts.graph_layout_with_grandalf import layout_graph_model_with_grandalf
from qdageditor5.models.abstract_dag_model import AbstractDAGModel, InletName, NodeName, OutletName, DirectionalLinkId

from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qtpy.QtCore import (
    QObject,
    QRect, 
    Qt, 
    Signal, 
    Slot, 
    QPoint,
    QEvent,
    QRectF,
    QPointF,
    QLineF,
    QSize
)

from qtpy.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QMouseEvent,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap, 
    QTransform,
    QWheelEvent, 
    QKeyEvent,
    QAction
)

from qtpy.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QStyle,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
    QAction
)

from qdageditor5.utils import geo


NodeId = NodeName
InletId = tuple[NodeName, InletName]
OutletId = tuple[NodeName, OutletName]

class _GraphItemId(NamedTuple):
    kind: Literal['node', 'inlet', 'outlet', 'tail', 'head']
    item: NodeId | InletId | OutletId | DirectionalLinkId


from dataclasses import dataclass


@dataclass
class DraggingNodeToolData:
    _dragged_nodes: list[NodeName]
    _original_positions: dict[NodeName, QPointF]
    _mouse_start_pos: QPointF

@dataclass
class LinkingToolData:
    _source: _GraphItemId
    _target: _GraphItemId | QPointF

@dataclass
class RectSelectionToolData:
    _start_pos: QPointF
    _end_pos: QPointF

@dataclass
class PanAndZoomToolData:
    _mouse_begin_pos: QPointF
    _pan_begin: QPointF
    _zoom_begin: float

def bounding_rect(rects: list[QRectF]) -> QRectF:
    if not rects:
        return QRectF()
    united_rect = rects[0]
    for rect in rects[1:]:
        united_rect = united_rect.united(rect)
    return united_rect


class DirectionalGraphView5(QFrame):
    requestLink = Signal(str, str, str, str) # source, outlet, target, inlet
    requestNode = Signal(QPointF, object) # scene_pos, tuple[NodeName, OutletName] | None

    def __init__(self, parent=None):
        super().__init__(parent)
        scroll_area_frame_style = QFrame.StyledPanel | QFrame.Sunken # default scrollarea frame style
        self.setFrameStyle(scroll_area_frame_style)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._model: AbstractDAGModel | None = None
        self._model_connections = []
        self._selection_model: GraphSelectionModel | None = None
        self._selection_model_connections = []
        self._hovered_item: _GraphItemId | None = None

        self._tool: DraggingNodeToolData | LinkingToolData | RectSelectionToolData | PanAndZoomToolData | None = None

        self._press_pos: QPointF | None = None
        self._pressed:bool = False



        self.setMouseTracking(True)
        self.setWindowTitle(DirectionalGraphView5.__name__)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) # required for the WidgetWithChildrenShortcut action to trigger

        self._pan = QPointF(0, 0)
        self._zoom = 1.0

        self._center_nodes_action = QAction("Fit Nodes", self)
        self._center_nodes_action.setShortcut("f")
        self._center_nodes_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._center_nodes_action.triggered.connect(lambda: self.fitNodes())
        self.addAction(self._center_nodes_action)

        self._layout_action = QAction("Layout Nodes", self)
        self._layout_action.setShortcut("l")
        self._layout_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._layout_action.triggered.connect(lambda: self.layout_nodes())
        self.addAction(self._layout_action)

    def setModel(self, model: AbstractDAGModel|None):
        if self._model is not None:
            for signal, slot in self._model_connections:
                signal.disconnect(slot)
            self._model_connections.clear()

        if model is not None:
            self._model_connections = [
                (model.modelReset, self.update),
                (model.nodeAboutToMove, lambda node: self.updateScene(self._get_affected_rect(node))),
                (model.nodeMoved, lambda node: self.updateScene(self._get_affected_rect(node))),
                (model.nodesAdded, lambda nodes: self.updateScene(bounding_rect([self._get_affected_rect(node) for node in nodes]))),
                (model.nodesAboutToBeRemoved, lambda nodes: self.updateScene(bounding_rect([self._get_affected_rect(node) for node in nodes]))),
                (model.linksAdded, lambda links: [self.updateScene(bounding_rect([self._linkShape(link).boundingRect() for link in links]))]),
                (model.linksAboutToBeRemoved, lambda links: [self.updateScene(bounding_rect([self._linkShape(link).boundingRect() for link in links]))]),
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)
        self._model = model
        self.update()

    def setSelectionModel(self, selection_model: GraphSelectionModel|None):
        if self._selection_model is not None:
            for signal, slot in self._selection_model_connections:
                signal.disconnect(slot)
            self._selection_model_connections.clear()

        if selection_model is not None:
            self._selection_model_connections = [
                (selection_model.linksSelectionChanged, self.update),
                (selection_model.nodesSelectionChanged, self.update),
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)
        self._selection_model = selection_model
        self.update()

    # nodes delegate
    def _nodeRect(self, node: NodeName)->QRectF:
        """return rectangle of the node in view coordinates (scaled and moved by pan/zoom)"""
        center = self._model.nodePosition(node)
        w, h = 65, 16
        scene_rect = QRectF(center.x() - w/2, center.y() - h/2, w, h)
        return scene_rect

    def _paintNode(self, painter: QPainter, option: QStyleOptionViewItem, node: NodeName|None):
        palette = self.style().standardPalette()
        if option.state & QStyle.StateFlag.State_Selected:
            brush = QColor(0, 120, 215)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            brush = palette.highlight()
        else:
            brush = palette.base()

        scene_rect = self._nodeRect(node)

        painter.setPen(QPen(palette.text().color(), 0)) # cosmetic pen: always 1 device pixel, even when scaled
        painter.setBrush(brush)
        painter.drawRoundedRect(scene_rect, 5, 5)

        painter.setPen(palette.text().color())
        painter.setFont(QFont("Courier", 9))
        painter.drawText(scene_rect, Qt.AlignmentFlag.AlignCenter, f"{node}")

    # inlets delegate
    def _inletPos(self, node: NodeName, inlet: InletName) -> QPointF:
        ports = list(self._model.inlets(node))
        node_rect = self._nodeRect(node)
        
        # outlet may be stale for a frame if the model just changed
        idx = ports.index(inlet) if inlet in ports else 0
        w, h = 7, 7
        spacing = 10
        count = max(len(ports), 1)
        node_scene_rect = node_rect
        port_scene_pos = QPointF(node_scene_rect.x() + (node_scene_rect.width() - (count - 1) * spacing) / 2 + idx * spacing, node_scene_rect.y()-h/2)
        return port_scene_pos

    def _inletShape(self, node: NodeName, inlet: InletName) -> QPainterPath:
        scene_pos = self._inletPos(node, inlet)
        w, h = 7, 7
        scene_rect = QRectF(scene_pos.x() - w/2, scene_pos.y() - h/2, w, h)
        path = QPainterPath()
        path.addEllipse(scene_rect)
        return path
        
    def _inletRect(self, node: NodeName, inlet: InletName):
        scene_pos = self._inletPos(node, inlet)
        w, h = 7, 7
        scene_rect = QRectF(scene_pos.x() - w/2, scene_pos.y() - h/2, w, h)

        fm = QFontMetrics(self.font())
        text_box = QRectF(fm.boundingRect(f"{inlet}"))
        text_box.moveBottomLeft(scene_rect.topRight())
        scene_rect = scene_rect.united(text_box)
        return scene_rect

    def _paintInlet(self, painter: QPainter, option: QStyleOptionViewItem, node, inlet):
        scene_pos = self._inletPos(node, inlet)
        w, h = 7, 7
        scene_rect = QRectF(scene_pos.x() - w/2, scene_pos.y() - h/2, w, h)
        palette = self.style().standardPalette()

        painter.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(palette.highlight())
        else:
            painter.setBrush(palette.text().color())
            s = 1
            scene_rect = scene_rect.adjusted(s, s, -s, -s) # make the port slightly smaller than the original rect
            
        painter.drawRoundedRect(scene_rect, 5, 5)
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(QPen(palette.highlight().color()))
            painter.drawText(scene_rect.topRight(), f"{inlet}")

    # outlets delegate
    def _outletPos(self, node: NodeName, outlet: OutletName) -> QPointF:
        ports = list(self._model.outlets(node))
        node_scene_rect = self._nodeRect(node)
        
        # outlet may be stale for a frame if the model just changed
        idx = ports.index(outlet) if outlet in ports else 0
        w, h = 7, 7
        spacing = 10
        count = max(len(ports), 1)
        port_scene_pos = QPointF(
            node_scene_rect.x() + (node_scene_rect.width() - (count - 1) * spacing) / 2 + idx * spacing, 
            node_scene_rect.bottom()+h/2
        )
        return port_scene_pos

    def _outletShape(self, node: NodeName, outlet: OutletName) -> QPainterPath:
        scene_pos = self._outletPos(node, outlet)
        w, h = 7, 7
        scene_rect = QRectF(scene_pos.x() - w/2, scene_pos.y() - h/2, w, h)
        path = QPainterPath()
        path.addEllipse(scene_rect)
        return path

    def _outletRect(self, node: NodeName, outlet: OutletName):
        scene_pos = self._outletPos(node, outlet)
        w, h = 7, 7
        scene_rect = QRectF(scene_pos.x() - w/2, scene_pos.y() - h/2, w, h)

        fm = QFontMetrics(self.font())
        text_box = QRectF(fm.boundingRect(f"{outlet}"))
        text_box.moveTopRight(scene_rect.bottomLeft())
        scene_rect = scene_rect.united(text_box)
        return scene_rect

    def _paintOutlet(self, painter: QPainter, option: QStyleOptionViewItem, node, outlet):
        scene_pos = self._outletPos(node, outlet)
        w, h = 7, 7
        scene_rect = QRectF(scene_pos.x() - w/2, scene_pos.y() - h/2, w, h)
        palette = self.style().standardPalette()

        painter.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(palette.highlight())
        else:
            painter.setBrush(palette.text().color())
            s = 1
            scene_rect = scene_rect.adjusted(s, s, -s, -s) # make the port slightly smaller than the original recWt
            
        painter.drawRoundedRect(scene_rect, 5, 5)
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(QPen(palette.highlight().color()))
            text_rect = QFontMetrics(self.font()).boundingRect(f"{outlet}")
            painter.drawText(scene_rect.bottomLeft()-QPointF(text_rect.topRight()), f"{outlet}")

    # links delegate
    def _linkShape(self, link: DirectionalLinkId) -> QPainterPath:
        assert link is not None, "Link cannot be None"
        source, outlet = self._model.linkSource(link)
        target, inlet = self._model.linkTarget(link)
        source_view_pos = self._outletPos(source, outlet)
        target_view_pos = self._inletPos(target, inlet)

        start_view_pos = source_view_pos
        end_view_pos = target_view_pos
        link_path = geo.makeVerticalRoundedPath(QLineF(start_view_pos, end_view_pos), 1)
        return link_path

    def _draftLinkShape(self) -> QPainterPath|None:
        if isinstance(self._tool, LinkingToolData):
            line = self.__draft_link_line()
            draft_link_path = geo.makeVerticalRoundedPath(QLineF(line.p1(), line.p2()), 1)
            return draft_link_path
        else:
            return None

    def _paintLink(self, painter: QPainter, option: QStyleOptionViewItem, link:DirectionalLinkId|None):
        palette = self.style().standardPalette()
        
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(QPen(palette.highlight().color(), 3))
        else:
            painter.setPen(QPen(palette.text().color(), 2))
        painter.setBrush(Qt.NoBrush)

        link_path:QPainterPath = self._linkShape(link)
        painter.drawPath(link_path)

    def _paintDraftLink(self, painter: QPainter):
        if draft_link_shape := self._draftLinkShape():
            palette = self.style().standardPalette()
            painter.setPen(QPen(palette.text().color(), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(draft_link_shape)

    def __draft_link_line(self)->QLineF:
        if not isinstance(self._tool, LinkingToolData):
            raise ValueError("Invalid tool for drafting link line")

        start_pos = None
        match self._tool._source:
            case ('inlet', _):
                node, inlet = self._tool._source[1]
                start_pos = self._inletPos(node, inlet)
            case ('outlet', _):
                node, outlet = self._tool._source[1]
                start_pos = self._outletPos(node, outlet)

            case ('head', _):
                _, link = self._tool._source
                source, outlet = self._model.linkSource(link)
                start_pos = self._outletPos(source, outlet)

            case ('tail', _):
                _, link = self._tool._source
                target, inlet = self._model.linkTarget(link)
                start_pos = self._inletPos(target, inlet)

            case _:
                raise ValueError("Invalid linking start item")

        end_pos = None
        match self._tool._target:
            case ('inlet', _):
                node, inlet = self._tool._target[1]
                end_pos = self._inletPos(node, inlet)

            case ('outlet', _):
                node, outlet = self._tool._target[1]
                end_pos = self._outletPos(node, outlet)

            case QPointF():
                end_pos = self._tool._target

            case _:
                raise ValueError("Invalid linking end item")

        if start_pos is None or end_pos is None:
            raise ValueError("Invalid start or end position for link line")

        if self._tool._source.kind in ('inlet', 'tail'):
            return QLineF(end_pos, start_pos)

        return QLineF(start_pos, end_pos)

    # methods
    def _get_affected_rect(self, node: NodeName) -> QRectF:
        # get the node rectangle
        node_rect = self._nodeRect(node).adjusted(-2, -2, 2, 2)

        # get the ports rectangle
        ports_rect = QRectF()
        for inlet in self._model.inlets(node):
            ports_rect = ports_rect.united(self._inletRect(node, inlet))
        for outlet in self._model.outlets(node):
            ports_rect = ports_rect.united(self._outletRect(node, outlet))

        # get the links rectangle
        links_rect = QRectF()
        for inlet in self._model.inlets(node):
            for link in self._model.inLinks(node, inlet):
                links_rect = links_rect.united(self._linkShape(link).boundingRect())
        for outlet in self._model.outlets(node):
            for link in self._model.outLinks(node, outlet):
                links_rect = links_rect.united(self._linkShape(link).boundingRect())

        return node_rect.united(ports_rect).united(links_rect).adjusted(-2, -2, 2, 2)

    def updateScene(self, scene_rect: QRectF):
        self.update(self.mapFromScene(scene_rect).toAlignedRect())
        # self.update()

    def itemAt(self, pos: QPoint) -> _GraphItemId | None:
        """Return the graph item at the given view position, or None if no item is found."""
        # rects returned by _nodeRect/_inletRect/_outletRect are already in view coordinates
        scene_pos = self.mapToScene(QPointF(pos))
        for node in self._model.nodes():
            for inlet in self._model.inlets(node):
                if self._inletRect(node, inlet).contains(scene_pos):
                    if self._inletShape(node, inlet).contains(scene_pos):
                        return _GraphItemId('inlet', (node, inlet))
                
            for outlet in self._model.outlets(node):
                if self._outletRect(node, outlet).contains(scene_pos):
                    if self._outletShape(node, outlet).contains(scene_pos):
                        return _GraphItemId('outlet', (node, outlet))
                
            if self._nodeRect(node).contains(scene_pos):
                return _GraphItemId('node', node)
            
        for link in self._model.links():
            source, outlet = self._model.linkSource(link)
            source_pos = self._outletRect(source, outlet).center()
            target, inlet = self._model.linkTarget(link)
            target_pos = self._inletRect(target, inlet).center()
            
            if self._linkShape(link).contains(scene_pos):
                # find out if the mouse is closer to the start or end of the link
                dist_to_start = (scene_pos - source_pos).manhattanLength()
                dist_to_end = (scene_pos - target_pos).manhattanLength()
                if dist_to_start < dist_to_end:
                    # closer to the start
                    return _GraphItemId('tail', link)
                else:
                    # closer to the end
                    return _GraphItemId('head', link)
                    
        return None

    def _sceneTransform(self) -> QTransform:
        """single source of truth for the pan/zoom transform: view = scene * zoom + pan"""
        transform = QTransform()
        transform.translate(self._pan.x(), self._pan.y())
        transform.scale(self._zoom, self._zoom)
        return transform

    def mapFromScene(self, pos: QPointF|QRectF) -> QPointF|QRectF:
        """map a point/rect from scene (model) coordinates to view (widget) coordinates"""
        match pos:
            case QRectF()|QRect():
                return self._sceneTransform().mapRect(QRectF(pos))
            case QPointF()|QPoint():
                return self._sceneTransform().map(QPointF(pos))
            case QPainterPath():
                return self._sceneTransform().map(pos)
            case _:
                raise TypeError(f"Unsupported type: {type(pos)}")

    def mapToScene(self, pos: QPointF|QRectF) -> QPointF|QRectF:
        """map a point/rect from view (widget) coordinates to scene (model) coordinates"""
        inverse, invertible = self._sceneTransform().inverted()
        if not invertible:
            raise ValueError("scene transform is not invertible")
        match pos:
            case QRectF()|QRect():
                return inverse.mapRect(QRectF(pos))
            case QPointF()|QPoint():
                return inverse.map(QPointF(pos))
            case QPainterPath():
                return inverse.map(pos)
            case _:
                raise TypeError(f"Unsupported type: {type(pos)}")

    def sizeHint(self):
        return QSize(800, 800)

    # events
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        scene_pos = self.mapToScene(event.pos())
        self.requestNode.emit(scene_pos, None)

    def paintEvent(self, event:QEvent):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.save()
        painter.setWorldTransform(self._sceneTransform(), False)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._model is None:
            return

        dirty_scene_rect = self.mapToScene(QRectF(event.rect()))

        # draw links
        for link in self._model.links():
            if isinstance(self._tool, LinkingToolData) and link == self._tool._source[1]:
                continue # skip drawing the link if is being dragged by the tool
            link_option = QStyleOptionViewItem()
            link_option.state = QStyle.State_Enabled
            if ('head', link) == self._hovered_item or ('tail', link) == self._hovered_item:
                link_option.state |= QStyle.State_MouseOver
            
            self._paintLink(painter, link_option, link)

        # draw nodes and ports
        for node in self._model.nodes():
            node_rect = self._nodeRect(node)
            if dirty_scene_rect.intersects(node_rect):
                node_option = QStyleOptionViewItem()
                node_option.state = QStyle.State_Enabled
                if ('node', node) == self._hovered_item:
                    node_option.state |= QStyle.State_MouseOver
                if self._selection_model is not None:
                    if node in self._selection_model.selectedNodes():
                        node_option.state |= QStyle.State_Selected

                painter.save()
                self._paintNode(painter, option=node_option, node=node)
                painter.restore()

            for inlet in self._model.inlets(node):
                inlet_rect = self._inletRect(node, inlet)
                if dirty_scene_rect.intersects(inlet_rect):                
                    inlet_option = QStyleOptionViewItem()
                    inlet_option.state = QStyle.State_Enabled
                    if ('inlet', (node, inlet)) == self._hovered_item:
                        inlet_option.state |= QStyle.State_MouseOver

                    # highlight ports involved in linking
                    if isinstance(self._tool, LinkingToolData):
                        if self._tool._source == ('inlet', (node, inlet)) or self._tool._target == ('inlet', (node, inlet)):
                            inlet_option.state |= QStyle.State_MouseOver
                            
                    
                    painter.save()
                    self._paintInlet(painter, inlet_option, node, inlet)
                    painter.restore()

            for outlet in self._model.outlets(node):
                outlet_rect = self._outletRect(node, outlet)
                if dirty_scene_rect.intersects(outlet_rect):
                    outlet_option = QStyleOptionViewItem()
                    outlet_option.state = QStyle.State_Enabled
                    if ('outlet', (node, outlet)) == self._hovered_item:
                        outlet_option.state |= QStyle.State_MouseOver

                    # highlight ports involved in linking
                    if isinstance(self._tool, LinkingToolData):
                        if self._tool._source == ('outlet', (node, outlet)) or self._tool._target == ('outlet', (node, outlet)):
                            outlet_option.state |= QStyle.State_MouseOver

                    
                    painter.save()
                    self._paintOutlet(painter, outlet_option, node, outlet)
                    painter.restore()

        # paint tools
        match self._tool:
            case RectSelectionToolData():
                selection_rect = QRectF(self._tool._start_pos, self._tool._end_pos).normalized()
                painter.save()
                painter.setPen(QPen(Qt.DashLine))
                painter.drawRect(selection_rect)
                painter.restore()

            case LinkingToolData():
                painter.save()
                self._paintDraftLink(painter)
                painter.restore()

        painter.restore()

    def mousePressEvent(self, event: QMouseEvent):
        # handle mouseClick events
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._pressed = True

        if self._model is None:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        mouse_pos = QPointF(event.pos())

        item = self.itemAt(mouse_pos)
        match item:
            case ('node', _):
                _, node = item
                dragged_nodes = list(self._selection_model.selectedNodes()) if self._selection_model is not None else []
                if node not in dragged_nodes:
                    dragged_nodes = [node]

                original_positions = {
                    dragged_node: QPointF(self._model.nodePosition(dragged_node))
                    for dragged_node in dragged_nodes
                }
                self._tool = DraggingNodeToolData(
                    dragged_nodes,
                    original_positions,
                    self.mapToScene(mouse_pos),
                )

            case ('inlet', _):
                self._tool = LinkingToolData(item, mouse_pos)

            case ('outlet', _):
                self._tool = LinkingToolData(item, mouse_pos)

            case ('head', _):
                _, current_link = item
                self._tool = LinkingToolData(item, mouse_pos)
                self.updateScene(self._linkShape(current_link).boundingRect())

            case ('tail', _):
                _, current_link = item
                self._tool = LinkingToolData(item, mouse_pos)
                self.updateScene(self._linkShape(current_link).boundingRect())

            case _:
                match event.button():
                    case Qt.LeftButton:
                        self._tool = RectSelectionToolData(
                            _start_pos=self.mapToScene(mouse_pos), 
                            _end_pos=self.mapToScene(mouse_pos)
                        )
                    case Qt.MiddleButton:
                        self._tool = PanAndZoomToolData(mouse_pos, self._pan, self._zoom)
                    case Qt.RightButton:
                        pass
                
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._model is None:
            return
        mouse_view_pos = QPointF(event.pos())

        match self._tool:
            case DraggingNodeToolData():
                dragged_nodes = self._tool._dragged_nodes
                prev_rect = reduce(
                    QRectF.united,
                    (self._get_affected_rect(node) for node in dragged_nodes),
                )

                # mouse delta is in scene coordinates
                delta = self.mapToScene(mouse_view_pos) - self._tool._mouse_start_pos
                for node in dragged_nodes:
                    original_position = self._tool._original_positions[node]
                    self._model.setNodePosition(node, original_position + delta)

                next_rect = reduce(
                    QRectF.united,
                    (self._get_affected_rect(node) for node in dragged_nodes),
                )

                united_rect = prev_rect.united(next_rect).adjusted(-2, -2, 2, 2)
                self.updateScene(united_rect)

            case LinkingToolData():
                old_line = self.__draft_link_line()
                old_rect = geo.makeVerticalRoundedPath(old_line).boundingRect() # DRY: makeVerticalRounded path should be used only in one place. That means, we need to get the draft link boundingrect from the same source as an 'existin' link.

                item_under_mouse = self.itemAt(mouse_view_pos)
                match self._tool._source.kind, item_under_mouse:
                    case 'inlet', ('outlet', _):
                        self._tool._target = item_under_mouse

                    case 'outlet', ('inlet', _):
                        self._tool._target = item_under_mouse

                    case 'head', ('inlet', _):
                        self._tool._target = item_under_mouse

                    case 'tail', ('outlet', _):
                        self._tool._target = item_under_mouse

                    case _:
                        self._tool._target = self.mapToScene(mouse_view_pos)

                new_line = self.__draft_link_line()

                new_rect = geo.makeVerticalRoundedPath(new_line).boundingRect()
                if old_rect is not None:
                    self.updateScene(new_rect.united(old_rect).adjusted(-2, -2, 2, 2))
                else:
                    self.updateScene(new_rect.adjusted(-2, -2, 2, 2))

            case RectSelectionToolData():
                old_rect = QRectF(self._tool._start_pos, self._tool._end_pos).normalized()
                self._tool._end_pos = self.mapToScene(mouse_view_pos)
                new_rect = QRectF(self._tool._start_pos, self._tool._end_pos).normalized()
                new_rect = QRectF(self._tool._start_pos, self._tool._end_pos).normalized()
                self.updateScene(new_rect.united(old_rect).adjusted(-2, -2, 2, 2))  
                # find and select nodes inside the selection rectangle
                
                nodes_intersecting = []
                for node in self._model.nodes():
                    if self._nodeRect(node).intersects(new_rect):
                        nodes_intersecting.append(node)

                if self._selection_model is not None:   
                    self._selection_model.selectNodes(nodes_intersecting)

            case PanAndZoomToolData():
                # pan is expressed in view coordinates, so the mouse delta can be applied directly
                delta = mouse_view_pos - self._tool._mouse_begin_pos
                self._pan = self._tool._pan_begin + delta
                self.update()

            case _:
                # update hovered items
                prev_rect:QRectF|None = None
                if self._hovered_item is not None:
                    match self._hovered_item:
                        case ('node', _):
                            new_rect = self._nodeRect(self._hovered_item[1]).adjusted(-2, -2, 2, 2)
                            prev_rect = new_rect
                        case ('inlet', _):
                            node, inlet = self._hovered_item[1]
                            prev_rect = self._inletRect(node, inlet).adjusted(-2, -2, 2, 2)
                        case ('outlet', _):
                            node, outlet = self._hovered_item[1]
                            prev_rect = self._outletRect(node, outlet).adjusted(-2, -2, 2, 2)
                        case ('tail', _) | ('head', _):
                            link = self._hovered_item[1]
                            prev_rect = self._linkShape(link).boundingRect().adjusted(-2, -2, 2, 2)
                    self._hovered_item = None

                new_rect:QRectF|None = None
                item_under_mouse:_GraphItemId|None = self.itemAt(mouse_view_pos)
                match item_under_mouse:
                    case ('inlet', _):
                        inlet_under_mouse:tuple[NodeName, InletName] = item_under_mouse[1]
                        new_rect = self._inletRect(*inlet_under_mouse).adjusted(-2, -2, 2, 2)
                        self._hovered_item = ('inlet', inlet_under_mouse)

                    case ('outlet', _):
                        outlet_under_mouse:tuple[NodeName, OutletName] = item_under_mouse[1]
                        new_rect = self._outletRect(*outlet_under_mouse).adjusted(-2, -2, 2, 2)
                        self._hovered_item = ('outlet', outlet_under_mouse)

                    case ('node', _):
                        node_under_mouse:NodeName = item_under_mouse[1]
                        new_rect = self._nodeRect(node_under_mouse).adjusted(-2, -2, 2, 2)
                        self._hovered_item = ('node', node_under_mouse)

                    case ('head', _):
                        link_under_mouse:DirectionalLinkId = item_under_mouse[1]
                        new_rect = self._linkShape(link_under_mouse).boundingRect().adjusted(-2, -2, 2, 2)
                        self._hovered_item = ('head', link_under_mouse)

                    case ('tail', _):
                        link_under_mouse:DirectionalLinkId = item_under_mouse[1]
                        new_rect = self._linkShape(link_under_mouse).boundingRect().adjusted(-2, -2, 2, 2)
                        self._hovered_item = ('tail', link_under_mouse)

                    case None:
                        new_rect = None
                        self._hovered_item = None

                if prev_rect is not None:
                    self.updateScene(prev_rect)

                if new_rect is not None:
                    self.updateScene(new_rect)

    def _mouse_click_event(self, event: QMouseEvent):
        # Handle mouse click event here
        item_under_mouse:_GraphItemId | None = self.itemAt(event.pos())
        print(item_under_mouse)
        if self._selection_model:
            
            match item_under_mouse:
                case ('node', _):
                    kind, node_name = item_under_mouse
                    self._selection_model.selectNode(node_name)

                
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._pressed:
            # Check that release is still inside the widget
            # and that the mouse didn't move too far
            threshold = 5  # pixels
            if (self.rect().contains(event.pos()) and
                    (event.pos() - self._press_pos).manhattanLength() < threshold):
                print("Click detected at", event.pos())
                self._mouse_click_event(event)

            self._pressed = False

        match self._tool:
            case RectSelectionToolData():
                selection_rect = QRectF(self._tool._start_pos, self._tool._end_pos).normalized()
                self._tool = None
                self.updateScene(selection_rect.adjusted(-2, -2, 2, 2))

                nodes_intersecting = []
                for node in self._model.nodes():
                    if self._nodeRect(node).intersects(selection_rect):
                        nodes_intersecting.append(node)

                if self._selection_model is not None:   
                    self._selection_model.selectNodes(nodes_intersecting)

            case PanAndZoomToolData():
                self._tool = None

            case DraggingNodeToolData():
                self._tool = None

            case LinkingToolData():
                if draft_link_shape := self._draftLinkShape():
                    self.updateScene(draft_link_shape.boundingRect())

                item_under_mouse = self.itemAt(event.pos())
                match self._tool._source, item_under_mouse:
                    case ('outlet', _), ('inlet', _):
                        target, inlet = item_under_mouse[1]
                        source, outlet = self._tool._source[1]
                        self.requestLink.emit(source, outlet, target, inlet)

                    case ('inlet', _), ('outlet', _):
                        target, inlet = self._tool._source[1]
                        source, outlet = item_under_mouse[1]
                        self.requestLink.emit(source, outlet, target, inlet)

                    case ('outlet', _), None:
                        print("outlet dropped on none")
                        # remove the link
                        _, current_link = self._tool._source
                        
                        self._hovered_item = None # todo: removing this line will result in an error. Investigate. I dont like this solution. Maybe Hovering Should be a tool as well.
                        source, outlet = self._tool._source[1]
                        scene_pos = self.mapToScene(event.pos())
                        self.requestNode.emit(scene_pos, ('outlet', (source, outlet)))
                        self._tool = None

                    case ('inlet', _), None:
                        print("inlet dropped on none")
                        # remove the link
                        _, current_link = self._tool._source
                        
                        self._hovered_item = None # todo: removing this line will result in an error. Investigate. I dont like this solution. Maybe Hovering Should be a tool as well.
                        target, inlet = self._tool._source[1]
                        scene_pos = self.mapToScene(event.pos())
                        self.requestNode.emit(scene_pos, ('inlet', (target, inlet)))
                        self._tool = None

                    case ('head', _), None:
                        print("head dropped on none")
                        # remove the link
                        _, current_link = self._tool._source
                        self._tool = None
                        self._hovered_item = None # todo: removing this line will result in an error. Investigate. I dont like this solution. Maybe Hovering Should be a tool as well.
                        self._model.removeLinks([current_link]) # todo: consider adding this to the abstract class, or handle it with a request signal

                    case ('tail', _), None:
                        print("tail dropped on none")
                        # remove the link
                        _, current_link = self._tool._source
                        self._tool = None
                        self._hovered_item = None # todo: removing this line will result in an error. Investigate. I dont like this solution. Maybe Hovering Should be a tool as well.
                        self._model.removeLinks([current_link]) # todo: consider adding this to the abstract class, or handle it with a request signal

                    case ('head', _), ('inlet', _):
                        print("head dropped on inlet")
                        # remove the link
                        _, current_link = self._tool._source
                        self._tool = None
                        
                        self._hovered_item = None # todo: removing this line will result in an error. Investigate. I dont like this solution. Maybe Hovering Should be a tool as well.
                        source, outlet = self._model.linkSource(current_link)
                        target, inlet = item_under_mouse[1]
                        self._model.removeLinks([current_link]) # todo: consider adding this to the abstract class, or handle it with a request signal
                        self.requestLink.emit(source, outlet, target, inlet)

                    case ('tail', _), ('outlet', _):
                        print("tail dropped on outlet")
                        # remove the link
                        _, current_link = self._tool._source
                        self._tool = None
                        self._hovered_item = None # todo: removing this line will result in an error. Investigate. I dont like this solution. Maybe Hovering Should be a tool as well.
                        source, outlet = item_under_mouse[1]
                        target, inlet = self._model.linkTarget(current_link)
                        self._model.removeLinks([current_link]) # todo: consider adding this to the abstract class, or handle it with a request signal
                        self.requestLink.emit(source, outlet, target, inlet)

                    case _:
                        pass

                self._tool = None

            case None:
                pass

    def wheelEvent(self, event: QWheelEvent):
        if self._model is None:
            return
        mouse_pos = QPointF(event.position())
        zoom_factor = 1.0015 ** event.angleDelta().y()
        new_zoom = max(0.1, min(10.0, self._zoom * zoom_factor)) # can zoom out, but never in past 1.0

        # keep the scene point under the cursor fixed while zooming
        scene_pos = self.mapToScene(mouse_pos)
        self._zoom = new_zoom
        self._pan = mouse_pos - scene_pos * new_zoom
        self.update()

    def leaveEvent(self, event: QEvent):
        if self._hovered_item is not None:
            match self._hovered_item:
                case ('node', _):
                    self.updateScene(self._nodeRect(self._hovered_item[1]).adjusted(-2, -2, 2, 2))
                case ('inlet', _):
                    node, inlet = self._hovered_item[1]
                    self.updateScene(self._inletRect(node, inlet).adjusted(-2, -2, 2, 2))
                case ('outlet', _):
                    node, outlet = self._hovered_item[1]
                    self.updateScene(self._outletRect(node, outlet).adjusted(-2, -2, 2, 2))
            self._hovered_item = None

    # actions
    def resetZoom(self):
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self.update()

    def fitNodes(self, limit_zoom=True):
        print("Fitting nodes to view")
        if self._model is None:
            return
        if self._selection_model.hasNodesSelection():
            nodes = self._selection_model.selectedNodes()
        else:
            nodes = self._model.nodes()
        scene_bounding_rect = reduce(lambda r, n: r.united(self._nodeRect(n)), nodes, QRectF())
        if scene_bounding_rect.isNull():
            return
        view_rect = self.rect()
        if view_rect.isNull():
            return
        # _nodeRect is already in scene coordinates, so the new zoom is just pixels-per-scene-unit
        scale_x = view_rect.width() / scene_bounding_rect.width()
        scale_y = view_rect.height() / scene_bounding_rect.height()

        self._zoom = min(scale_x, scale_y)
        print(f"Calculated zoom: {self._zoom}", f"Limit zoom: {limit_zoom}")
        if limit_zoom and self._zoom > 1.0:
            self._zoom = 1.0
        self._pan = QPointF(view_rect.center()) - scene_bounding_rect.center() * self._zoom
        self.update()

    def centerNodes(self):
        print("Centering nodes in view")
        if self._model is None:
            return
        bounding_rect = reduce(lambda r, n: r.united(self._nodeRect(n)), self._model.nodes(), QRectF())
        if bounding_rect.isNull():
            return
        view_rect = self.rect()
        if view_rect.isNull():
            return
        # _nodeRect is already in scene coordinates
        scene_bounding_rect = bounding_rect
        self._pan = QPointF(view_rect.center()) - scene_bounding_rect.center() * self._zoom
        self.update()

    def layout_nodes(self):
        # dot honors inlet ordering (ordering="in"); grandalf only nudges it, so prefer dot when available
        positions = layout_graph_model_with_grandalf(self._model)
        for node_name, (x, y) in positions.items():
            self._model.setNodePosition(node_name, QPointF(x, y))
        self.update()

if __name__ == "__main__":
    import sys
    from qtpy.QtWidgets import QApplication
    from qdageditor5.models.standard_dag_model import StandardDAGModel
    model = StandardDAGModel()
    selection = GraphSelectionModel(model)
    nodes = model.addNodes(5)
    for n in nodes:
        model.setInlets(n, ["in1", "in2"])  # Example inlets, replace with actual inlet names
        model.setOutlets(n, ["out"])  # Example outlets, replace with actual outlet names

    model.addLinks([(nodes[0], "out", nodes[1], "in1")])  # Example link, replace with actual links

    for idx, n in enumerate(nodes):
        model.setNodePosition(n, QPointF(150, 150 + 50 * idx))

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Directional Graph View 5 Example")
    delete_action = QAction("Delete", window)
    window.addAction(delete_action)
    delete_action.setShortcut("Delete")
    def delete_selected_nodes():
        selected_nodes = selection.selectedNodes()
        model.removeNodes(selected_nodes)

    delete_action.triggered.connect(delete_selected_nodes)
    layout = QHBoxLayout(window)
    
    
    def link_nodes(source:NodeName, outlet:OutletName, target:NodeName, inlet:OutletName):
        new_link = (source, outlet, target, inlet)
        model.addLinks([new_link])
    
    def add_node(scene_pos: QPointF, dragsource: _GraphItemId|None):
        new_nodes = model.addNodes(1)
        if new_nodes:
            for new_node in new_nodes:
                model.setInlets(new_node, ["in1", "in2"])  # Example inlets, replace with actual inlet names
                model.setOutlets(new_node, ["out"])  # Example outlets, replace with actual outlet names
                model.setNodePosition(new_node, scene_pos)
                print(f"Adding new node from source: {dragsource}")
                match dragsource:
                    case ('outlet', _):
                        print("Adding link from dragsource to new node")
                        _, (node, outlet) = dragsource
                        model.addLinks([(node, outlet, new_node, "in1")])  # Example inlet, replace with actual inlet name
                    case ('inlet', _):
                        print("Adding link from new node to dragsource")
                        _, (node, inlet) = dragsource
                        model.addLinks([(new_node, "out", node, inlet)])  # Example outlet, replace with actual outlet name
                    case _:
                        pass

    for i in range(2):
        view = DirectionalGraphView5()
        view.requestLink.connect(link_nodes)
        view.requestNode.connect(add_node)
        view.setModel(model)
        view.setSelectionModel(selection)
        layout.addWidget(view)

    window.show()
    sys.exit(app.exec_())


