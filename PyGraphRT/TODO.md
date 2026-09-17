# GraphRT
- [ ] consider making operators first class citizens.
- [ ] investigate, signals, that sends a batch of object that changed, and signals, that send change iformation about a single object. Consider, the signals to be more consistent, moving in either direction, eg allwazs use a batch, or alwazs use sngle objects. Batch feels more performant. This also related to, if operators become first class citizens.
- [x] when a node is removed, the GraphRT.output still holds on to it.
      when a node is removed, and its the actual ouput, set the output to None
- [ ] consider using references inside the GraphRT datastructure.
      eg graph.output, node.inputs, node.operators etc.
- [x] add test for cycle detection.
      just caught a bug where two nodes were connected twice and it detected it as a cycle
- [ ] support callable objects not just functions
- [ ] refactor Cache to be pluggable.