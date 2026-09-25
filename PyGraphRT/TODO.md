# GraphRT
- [x] support untitled ImportModule

- [ ] review PyGraphRT error handling and reporting


- [ ] review parameters and getters semantic. whic one to use where and why.

- [ ] testing. subclasses that share behaviour, should have shared tests.
      share test between local_module and script_module, 
      see: pygraphrt model tests. its uses fixture, and parametrize

## Features
- [x] graph (snapshots) and serialization
- [ ] support callable objects not just functions
- [x] refactor Cache to be pluggable.

- [x] emit signals, when functions actually added, removed changed. dont emit
      add, remove, change signlas, when only the script has changed.

- [x] TEST change signal, when the function itself did not, but due to its scope the behaviour has changed.

- [ ] **ImportModuleRT** how to handle importmodule without a file. <unnamed>
      when there was a real file, but it was deleted? In the UI we should be
      able to create files, that are not yet saved. So it should be valid as
      long as the script is valid.

- [ ] **ImportModule** should save **relative paths**.
      when a graph was not yet saved, importing modules, will have to store the
      abolute path. Now when the graph is saved, the importmodule paths should
      be resolved to be relative to the graph. by default it sohuld be relative,
      we should add an option, to save it as absolute path.

- [ ] **ImportModule** indicate when the script has been __*edited__ with a STAR

- [ ] Fit node size to its content in the **DAGView**

- [ ] **export** a runnable python script.

## Architecture
NOTE: these might be outdated:
- [ ] Investigate operator fingerprints in ScriptModuleRT. Re-executing a script
      recreates unchanged functions and changes their fingerprints despite selective
      change signals. Review stable fingerprints for unaffected operators, module
      ownership, and changes through globals, helpers, and imported callables.
- GraphRT execution should be deterministic. Same inputs result the same outputs.
  make sure, GraphRT after mutated behaves the same as GraphRT jsut initialized.

- [x] allow adding and updating operators in GraphRT.
- [x] GraphRT should be allowed to load and reaload(!) operators from a python script!
      -> ScriptmoduleRT added, that manages operators from a python script.
- [ ] consider making operators first class citizens.
- [ ] investigate, signals, that sends a batch of object that changed, and signals, that send change iformation about a single object. Consider, the signals to be more consistent, moving in either direction, eg allwazs use a batch, or alwazs use sngle objects. Batch feels more performant. This also related to, if operators become first class citizens.
- [ ] Consider GraphRT responsibility to be nodes and links only. and factor out, the python script-like additions: operators, modules etc.
- [x] consider using references inside the GraphRT datastructure.
      eg graph.output, node.inputs, node.operators etc.
- [x] when a node is removed, the GraphRT.output still holds on to it.
      when a node is removed, and its the actual ouput, set the output to None
- [x] add test for cycle detection.
      just caught a bug where two nodes were connected twice and it detected it as a cycle
