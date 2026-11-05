"""Optional PySide6 UI for graph_cook_engine.py.

Install: pip install PySide6 numpy
Run:     python graph_cook_qt_demo.py
"""

import time

import numpy as np
from qtpy.QtCore import QTimer
from qtpy.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from graphcook.cookengine import Engine, EventBus, Graph, cook


@cook(size=5)
def animated_cube(size, ctx):
    time.sleep(0.08)  # Only to make status changes visible.
    return np.array([
        [0.0, 0.0, 0.0],
        [size, 0.0, 0.0],
        [0.0, size, 0.0],
    ]) + ctx.frame * 0.1


@cook(size=20)
def alternate_cube(size, ctx):
    time.sleep(0.08)
    return np.array([
        [0.0, 0.0, 0.0],
        [size, 0.0, 0.0],
        [0.0, size, 0.0],
    ]) + ctx.frame * 0.1


@cook(source=animated_cube)
def blend(source, ctx):
    frame = ctx.frame
    return (
        0.25 * ctx.cook(source, frame - 1)
        + 0.50 * ctx.cook(source, frame)
        + 0.25 * ctx.cook(source, frame + 1)
    )


class GraphWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Editable graph: worker cooks + UI events")
        self.resize(900, 600)

        self.bus = EventBus()
        self.graph = Graph(self.bus)
        self.graph.add(blend)
        self.engine = Engine(self.graph, max_workers=2)
        self.jobs = []
        self.items = {}  # node_id -> QTreeWidgetItem
        self.ui_bindings = {}  # UI-owned state, updated only from graph events.

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)

        self.frame = QSpinBox()
        self.frame.setRange(-1_000_000, 1_000_000)
        self.frame.setValue(100)
        toolbar.addWidget(QLabel("Frame"))
        toolbar.addWidget(self.frame)

        cook_button = QPushButton("Cook in worker")
        cook_button.clicked.connect(self.start_cook)
        toolbar.addWidget(cook_button)

        self.size = QSpinBox()
        self.size.setRange(1, 100)
        self.size.setValue(5)
        toolbar.addWidget(QLabel("Cube size"))
        toolbar.addWidget(self.size)

        change_button = QPushButton("Edit parameter")
        change_button.clicked.connect(self.change_size)
        toolbar.addWidget(change_button)

        reconnect_button = QPushButton("Use alternate input")
        reconnect_button.clicked.connect(self.change_connection)
        toolbar.addWidget(reconnect_button)

        reset_button = QPushButton("Restore original input")
        reset_button.clicked.connect(
            lambda: self.graph.connect(blend, "source", animated_cube)
        )
        toolbar.addWidget(reset_button)

        self.nodes = QTreeWidget()
        self.nodes.setHeaderLabels(["Node", "Settings / inputs", "Cook status"])
        layout.addWidget(self.nodes)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        # The QTimer runs on the GUI thread. Worker threads only enqueue events.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flush_events)
        self.timer.start(25)
        self.flush_events()

    def start_cook(self):
        self.jobs.append(self.engine.submit(blend, self.frame.value()))

    def change_size(self):
        self.graph.set_param(animated_cube, "size", self.size.value())

    def change_connection(self):
        self.graph.connect(blend, "source", alternate_cube)

    def flush_events(self):
        for ev in self.bus.drain(limit=1000):
            self.log.appendPlainText(
                f"rev {ev.revision} | {ev.kind} | "
                f"{ev.node_name or '-'} f={ev.frame} | "
                f"eval={ev.evaluation_id[:8] if ev.evaluation_id else '-'} "
                f"{ev.details}"
            )

            if ev.kind == "node_added":
                item = QTreeWidgetItem([ev.node_name, "", "idle"])
                self.nodes.addTopLevelItem(item)
                self.items[ev.node_id] = item
                self.ui_bindings[ev.node_id] = {
                    "parameters": dict(ev.details["parameters"]),
                    "inputs": dict(ev.details["inputs"]),
                }
                item.setText(1, str(self.ui_bindings[ev.node_id]))
            elif ev.kind == "node_removed":
                self.ui_bindings.pop(ev.node_id, None)
                item = self.items.pop(ev.node_id, None)
                if item is not None:
                    idx = self.nodes.indexOfTopLevelItem(item)
                    self.nodes.takeTopLevelItem(idx)
            elif ev.kind in {"parameter_changed", "connection_changed"}:
                item = self.items.get(ev.node_id)
                if item is not None:
                    model = self.ui_bindings[ev.node_id]
                    if ev.kind == "parameter_changed":
                        model["parameters"][ev.details["parameter"]] = ev.details["new"]
                    else:
                        model["inputs"][ev.details["input"]] = ev.details["new_source_id"]
                    item.setText(1, str(model))
                    item.setText(2, "edited")
            elif ev.kind in {"node_started", "node_finished", "node_cache_hit"}:
                # Older revisions must not overwrite current graph node states.
                if ev.revision != self.graph.revision:
                    continue
                item = self.items.get(ev.node_id)
                if item is not None:
                    if ev.kind == "node_started":
                        status = f"Cooking frame {ev.frame}"
                    elif ev.kind == "node_cache_hit":
                        status = f"Cache hit frame {ev.frame}"
                    else:
                        status = "Done" if ev.details.get("status") == "ok" else "Error"
                    item.setText(2, status)

        pending = []
        for future in self.jobs:
            if not future.done():
                pending.append(future)
                continue
            try:
                result = future.result()
                if result.revision == self.graph.revision:
                    self.log.appendPlainText(
                        f"DISPLAY RESULT [{result.evaluation_id[:8]}] "
                        f"x={result.value[1, 0]:.2f}"
                    )
                else:
                    self.log.appendPlainText(
                        f"IGNORED STALE RESULT [{result.evaluation_id[:8]}] "
                        f"from revision {result.revision}"
                    )
            except Exception as exc:
                self.log.appendPlainText(f"ERROR: {exc}")
        self.jobs = pending

    def closeEvent(self, event):
        self.timer.stop()
        self.engine.shutdown()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])
    window = GraphWindow()
    window.show()
    app.exec()
