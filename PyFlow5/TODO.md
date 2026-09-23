- [x] add open/save .pgraph
- [ ] Resolve graph imports and asset paths relative to the .pgraph file’s directory
- [ ] fix json fileformat:
      - `local` should be the local python script.
      - import are the ImportModuleRT (relative to the graph)
      - nodes: nodes with args and kwargs defining the links and parameters
- [ ] consider other graph formats:
      - yaml
      - markdown
        with frontmatter for the imports
        a python code block for the `local` definitions
        a mermaid code block for the graph itself.