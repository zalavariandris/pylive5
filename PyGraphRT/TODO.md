# GraphRT
- [x] when a node is removed, the GraphRT.output still holds on to it.
      when a node is removed, and its the actual ouput, set the output to None
- [ ] consider using references inside the GraphRT datastructure.
      eg graph.output, node.inputs, node.operators etc.
- [x] add test for cycle detection.
      just caught a bug where two nodes were connected twice and it detected it as a cycle
- [ ] support callable objects not just functions
- [ ] refactor Cache to be pluggable.