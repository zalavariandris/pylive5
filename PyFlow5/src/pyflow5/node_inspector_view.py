class NodeInspectorView(DetailsView):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._node_tree_view = QTreeView(self)
        self._node_tree_view.setMouseTracking(True)
        node_tree_header = self._node_tree_view.header()
        node_tree_header.setStretchLastSection(True)
        node_tree_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        node_tree_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._node_tree_view.setItemDelegateForColumn(
            1, 
            NodeInputDelegate(self._node_tree_view)
        )
        self._node_tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # self._node_tree_view.hide()

        self._node_tree_view.expandAll()



            # def _refresh_node_tree_view_on_selectionchange() -> None:
            #     assert self._document is not None
            #     current = self._document.graphselection_model.currentNode()
            #     if current is not None:
            #         root = self._document.node_inlet_tree_adapter.mapFromSource(current)
            #     else:
            #         root = QModelIndex()  # show all nodes
            #     self._node_tree_view.setRootIndex(root)
            #     self._node_tree_view.setVisible(bool(current))

            # self._document.graphselection_model.currentNodeChanged.connect(
            #     lambda selected, deselected: _refresh_node_tree_view_on_selectionchange()
            # )
            # _refresh_node_tree_view_on_selectionchange()