- [ ] update node paint method, to reflect ExecutionGraph and GraphResolution results. Also include the resolution and execution graph to change the PyGraphRTModel Data. Probably the GraphModel should use these. \#QDAGEditor5 \#PyFlow
- [ ] ADD ModuleRegistry to the open, save in Document \#PyFlow
- [ ] UPDATE serialization to use the ModuleRegistry \#PyGraphRT
- [ ] OperatorRef is an AbstractOperator, not something that point to and AbstractOperator. Modules should implement the methods instead, and the ref should call the owning module methods instead. \#PyGraphRT
- [ ] Replace the NodeName in GraphModel to a QModelIndex-like object. namei `ModelKey` \#QDAGEditor5

- [x] add open/save .pgraph
- [ ] Resolve graph imports and asset paths relative to the .pgraph file’s directory
- [x] fix json fileformat:
      - `local` should be the local python script.
      - import are the ImportModuleRT (relative to the graph)
      - nodes: nodes with args and kwargs defining the links and parameters
- [ ] consider other graph formats:
      - yaml
      - markdown
        with frontmatter for the imports
        a python code block for the `local` definitions
        a mermaid code block for the graph itself.