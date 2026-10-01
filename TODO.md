# TODO

## Inspector dev
- [ ] 

## fix open and save
- [ ] open the lates graph, on launch
- [ ] Recents
- [x] Fix saving opening in the GUI

## GraphView
- a delegate, to draw custom nodes. with potentially custom roles in a custom GraphModel.

## Inspector
- register InspectorInputs

## Execution lifecycle and future async support
**Prepare for Async GraphExecutor** (ptobalby after refactoring the even system)
Keep execution synchronous for now, but let the UI consume signals so it can support background execution later.
- [ ] Add a `GraphExecution` report containing an evaluation ID, the requested root, and each relevant node's final state. Publish a fresh snapshot for every evaluation and return the same report from `execute()`.
- [ ] Assign an evaluation ID before publishing any state updates. Use it to associate notifications with a run and reject obsolete results after graph edits.
- [ ] Add `evaluation_started(evaluation_id, root)`, `node_execution_changed(evaluation_id, state)`, and `graph_executed(report)` signals. Replace the existing `executed` signal and update its consumers.
- [ ] Publish pending states before evaluation, running states immediately before operator calls, and terminal states as nodes finish. Cache hits go directly to success; unavailable dependencies produce blocked states while independent branches continue.
- [ ] Expose the complete `NodeExecution` through `PyFlowRTModel.ExecutionRole`. Export `ExecutionBlocked` from the runtime package and update the viewer and node appearance to distinguish all states.
- [ ] Include optional `duration_seconds` on success and failure states. Define cache-hit metadata separately; use `None` for unmeasured durations and make `profile=False` actually disable measurement.
- [ ] Add optional queue/start timestamps when pending and running states become visible. Use a monotonic clock for elapsed time; compute a running duration in the UI rather than repeatedly replacing the state.
- [ ] Add a future `submit(root) -> UUID` entry point that schedules background execution and returns immediately, using the same notifications and report contract as synchronous execution.
- [ ] Deliver worker notifications to the model on the UI thread through queued connections so views remain responsive during operator execution.
- [ ] Evaluate a stable graph/operator snapshot or coordinate edits with active execution. Define cache synchronization and an overlap policy before allowing concurrent evaluations.
- [ ] Define completion reporting for preparation errors, unexpected executor errors, and future cancellation so the UI cannot remain stuck in a running state. Preserve the distinction between operator failure and an executor/API error.
- [ ] Test notification order, evaluation IDs, exactly one completion report, cached and blocked states, independent branches, profiling, and rejection of obsolete updates. Add UI-thread delivery tests when background execution is introduced.

## ExampleApps
- [ ] Image Grade
  - [ ] node graph, with image operators: 
    - [ ] read, write
    - [ ] exposure
    - [ ] colorgrade
    - [ ] cornerpin
    - [ ] temperature, tint
    - [ ] blur

- [ ] Image CornerPin

## DEV
- [x] smoke test covering basic functionality *2026/09/30*
  - [x] importint module from files, and executing the graph
  - [x] serialization
  - [x] memory cache

- [ ] we somehow need to indicate, when an ImportModule has a path, but the file does not exist.

- [ ] consider addin a rename method to the node_ref. it would probaly change the NodeRef hash. so it might not be a good idea. Unless NodeRefs are used by their objectid under the hood, and not its hash.

**The Book Keeping problem**
I think the current architecture has a deply routed problem. We call it the *book keeping problem*.
Collection items, like a node, a link, or an operator and especialy their relationships are sometimes kept in seperate places. we must decide who is the owner not just the object, but the relationshsip as well. Basically we wanna make sure, that there are only on book, the source of truth.
Also, the signals emitted from the Graph, or Modules must be enough, to keep that in sync for example with QAbstractItemModels. So the proxy model does not need bookkeping, to notify the views. This is a deep architectural question. Probably structural changes, like removeing nodes adding links, or deleting operators have to emit pre and post signals. An alternative to redesign the signal emitting architecture, to include change data eg: what was removed, or on value change, prev and next values. The goal is to be able to keep another object in sync by using the signals without storing the previous value on this side.


- [x] use two way .relations for node-to-operators in GrahpRT. A relation must be stored in one place.!
      This is a  architectural role. Currently the GraphDefinition responsibility to store node-operator relations.
- [x] NodeRef should not have acces to the nodeData directly. nodeData is internal to the graph. noderef should interact strictly with the owner graph
      - this ould open up implementation optimizations inside the graph. for example to use a node_to_operator relationship table instead of storing the operator in the NodeData. also to store links in a table. seperate node properties and links. (we can keep the public api [eg update_node...] the same, but the internal would be a lot easier to optimize.)
- [ ] use pre post change handler in GraphDefinition for addition, and removal. 
- [ ] consider using pre/post data_change signals as well?


- [ ] update node paint method, to reflect ExecutionGraph and GraphResolution results. Also include the resolution and execution graph to change the PyGraphRTModel Data. Probably the GraphModel should use these. \#QDAGEditor5 \#PyFlow
- [ ] ADD ModuleRegistry to the open, save in Document \#PyFlow
- [ ] UPDATE serialization of the graph definition. GraphDefinition no longer references modules.
- [ ] ADD serialization to the ModuleRegistry \#PyGraphRT
      with relative paths?

- [ ] OperatorRef is an AbstractOperator, not something that point to and AbstractOperator. Modules should implement the methods instead, and the ref should call the owning module methods instead. \#PyGraphRT
- [ ] Replace the NodeName in GraphModel to a QModelIndex-like object. namei `ModelKey` \#QDAGEditor5


- [ ] consider adding Roles (same as QT uses for models) to the Graphmodel.
      NodeTitleRole
      NodeMessageRole
      NodeInletsRole?
      ... NodeBody Role
      \#QDagEditor

- [ ] add option, to show broken links. links are broken, when points to nodes that are not in the model.
      a link can be broken in multiple ways:
      - link has source, but no target, or has target node but no source
      - link has no source neither target. how to show that?
      - link has source and target, but points to missing ports? it should be pointing to the node direclty
    when the show broken links is off, skip broken links!
    \#QDagEditor
    
- [ ] consider adding addLinks and removeLinks abstract methods for the AnstractDagmodel. With this move, consider making the DirectionalLink a concrete class. \#QDagEditor
   if soo, we need to think about multiple links between the same ports? not really, since the same port will not be connected multiple time. multiple links make sense only, when the links are connected directly to the nodes. specifying source outlet and target inlet is enough for now. If we decide to make the Link a concrete class, then 'linkSource' and 'linkTarget' would become obsolete.
   think about this carefully, how 'abstract' this model should be.
   \#QDagEditor5



- [x] add open/save .pgraph

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


- [x] support untitled ImportModule \#pygraph
- [ ] review PyGraphRT error handling and reporting \#pygraph
- [ ] review parameters and getters semantic. whic one to use where and why. \#pygraph
- [ ] testing. subclasses that share behaviour, should have shared tests.
      share test between local_module and script_module, 
      see: pygraphrt model tests. its uses fixture, and parametrize
      \#pygraph
- [x] graph (snapshots) and serialization \#pygraph
- [ ] support callable objects not just functions \#pygraph
- [x] refactor Cache to be pluggable. \#pygraph
- [x] emit signals, when functions actually added, removed changed. dont emit
      add, remove, change signlas, when only the script has changed. \#pygraph
- [x] TEST change signal, when the function itself did not, but due to its scope 
      the behaviour has changed. \#pygraph
- [ ] **ImportModuleRT** how to handle importmodule without a file. <unnamed>
      when there was a real file, but it was deleted? In the UI we should be
      able to create files, that are not yet saved. So it should be valid as
      long as the script is valid. \#pygraph
- [ ] **ImportModule** should save **relative paths**.
      when a graph was not yet saved, importing modules, will have to store the
      abolute path. Now when the graph is saved, the importmodule paths should
      be resolved to be relative to the graph. by default it sohuld be relative,
      we should add an option, to save it as absolute path. \#pygraph
- [ ] **ImportModule** indicate when the script has been __*edited__ 
      with a STAR \#pygraph \#pyflow
- [ ] **export** a runnable python script. \#pygraph
- [ ] investigate, signals, that sends a batch of object that changed, and signals, that send change iformation about a single object. Consider, the signals to be more consistent, moving in either direction, eg allwazs use a batch, or alwazs use sngle objects. Batch feels more performant. This also related to, if operators become first class citizens.

## Architecture
NOTE: these might be outdated:
- [x] Investigate operator fingerprints in ScriptModuleRT. Re-executing a script
      recreates unchanged functions and changes their fingerprints despite selective
      change signals. Review stable fingerprints for unaffected operators, module
      ownership, and changes through globals, helpers, and imported callables.
      \#pygraph **cache**
- GraphRT execution should be deterministic. Same inputs result the same outputs.
  make sure, GraphRT after mutated behaves the same as GraphRT jsut initialized.
  \#pygraph

- [x] allow adding and updating operators in GraphRT.
- [x] GraphRT should be allowed to load and reaload(!) operators from a python script!
      -> ScriptmoduleRT added, that manages operators from a python script.
- [x] consider making operators first class citizens. \#pygraph

- [ ] Consider GraphRT responsibility to be nodes and links only. and factor out, the python script-like additions: operators, modules etc. \#pygraph
- [x] consider using references inside the GraphRT datastructure.
      eg graph.output, node.inputs, node.operators etc. \#pygraph
- [x] when a node is removed, the GraphRT.output still holds on to it.
      when a node is removed, and its the actual ouput, set the output to None \#pygraph
- [x] add test for cycle detection.
      just caught a bug where two nodes were connected twice and it detected it as a cycle \#pygraph



