
## Features
- [ ] try to use the execution_plan in the inline_backend.
      execution_plan probably need to be renamed. it contains utilitiy functions, to evaluate,prepare and execute the engine(registry+graph)
- [...] run engine execution in a background process
- [x] ScriptEditAdvanced should support .setDocument(document.script_document)
- [ ] consider creating a special ScriptDocument sublcassing QTextDocument
- [x] indicate file and document modifications
- [x] session now restore opened file, as well as unsaved modifications
- [x] Run ScriptModuleEvaluation in the background
      -> now it uses a QRunnable. scheduling is nothing fancy, might need a review later.
- [ ] Tasks manager.
- [ ] Task progressbar
- [ ] create a method that compiles the graph into a native python script so its runnable without the app.
      also think about if we could compile it to a python app without using the PyGraphRT module.
      in case the graph processing library brakes, the graph will be still runnable.
- [ ] Push+Pull node evaluation. pushing callables, than request image region or movie frame for example
- [ ] allow hotreloading python modules
- [ ] node Execution progress (possibly as simply as using tqdl inside the operator code)
- [ ] Console, to interact with the nodegraph

## Tests
- [ ] document open save saveAs, fileHandling
- [ ] create a smoke test for the inspector. setting values, clear values, connect inputs, unconnect inputs, and the editor model binding. default values, empty values etc.
- ...

## Architecture
- [ ] consolidate ExecutionPlan items and GraphDefinition states
- [x] now document is bound to a file.
- [x] _Refactor documentwindow, document, and the appwindow_
      responsibilities:
      - AppWindow: document lifecycle and application/session state.
      - DocumentWindow: presentation, selection, and user interaction.
      - Document: content, runtime, file binding, and explicit editing operations.

      steps:
      1. Move Selection from document to Window
      1. ✓ move selection from document to the documentwindow
      2.   refactor selection based editing methods in document, 
      and move the selection based edits to the window
      2. Move the filebinding to the document
      1. _document_path into PyFlowDocument as _file_path

      note: factor out the session and probably settings from the current Window.
            window should be a document window. this will allow testing empty GUI (withoutloading the last session)
            as well as opening multiple documents. The problem is, that the Window acstions arecontrolled by the document window for now.
            probably we should have a DocumentsList model as well.
            I like it when projectfiles open in another instance of the whole application, butalso the session, and recent files in the menu
            has a wider responsibility than a single document. So... maybe we could have tabs aswell as opening document in multiple window, 
            but in a single app.

- [ ] Rename the ScriptModule to embedded modules!
- [ ] Names become pretty problematic. 
      - `PyGraphRtDagModel`
      - `NodesListModelAdapter`
      - `NodesListModelSelecitonAdapter`
      - etc...
      I think PyGraphRt could become PyGraphEngine
- [ ] find a better name for graph modules, o distinguishe from standard python modules

- [ ] Consider using AnyIO for async tasks, like
      graph execution. it support cancelling jobs.

- [ ] we have to solve the mutability problem in the graph processing

- [ ] consider implementing structural change notifications for inlets in DirectionalGraphView5
- [x] GraphView now uses lazy caching with (signal driven) explicit invalidation


- [ ] review NodeRTInputRole. I think (most of) it could be moved to QDAGEditor5
      also, the QDAGEditor5 NodeDataRole and SocketDataRole needs a UserRoel to allow extension.
- [x] consider *@vfxops* ImageRGBA using _Planar(CHW)_ channels layout instead of _Interleaved (HWC)_ layout
     interleaved: RGBA RGBA RGBA …
     Planar: RRR… GGG… BBB… AAA…
     it is possible a lot faster.

- [x] When linking, dropping an inlet right onto a node, should create a popup where all the possible inlets (invisibles especially) can be selected to link to.

- [ ] I think we need a single helper function to consolidate node args, kwargs and the operator parameters.
      figure out if an input locator is int or str, and how it maps onto the operator parameters.
      

- [x] add visibility Role(orFlag) to inlets.
      in pyflow hide an inlet if it has no Literal Input or has a default value.
      # todo: missing implementation to determine if the inlet represents a positional arg

- [x] optimize graphview by using cached local node bounding rects
- [x] add Annotated[float, Range(-1,1)] editor support for the node inspector
- [ ] review how string and non string annotation is received by the editors.py. also vfxops forexample uses `from __future__ import annotations` that might turn annotations into strings.
- [x] add execute duration and show it in the graphview
- [ ] checkout https://pypi.org/project/Fileseq/ for file sequences instead inventing the wheel, as we do it now in vfxops
- [x] graph cache revision
      -> added a new graph evaluator suite. it should be reviewed.

- [ ] Implement flags for GraphModel use it in the NodesList adapter. !!!!!!!!!!!!!!!!
      fésüld össze és gondold át, a GraphModel és a Az adapterek Roles-ait



- [x] We also Need a NodeInletTree(+selection?)ModelAdapter for the inspector to work with standard qt models




- [x] cleanup myqtx file structure and class names.

- [?] FormView does not update when data changes.
      added a todo in the on_datachanged hook.

- [ ] ImportModule should support importing from a file without specifying a name

- [x] BUG: when deleting a node with no inputs, the FormView raise an exception, and the app crash

- [x] The `Viewer` should connect to the standard NodesList(+Selection)Model instead of the GraphModel.
- [x] Now use the NodeList(+selection)Model adapters to drive the UI instead of directly connecting to the GraphModel.
      if necessary introduce NodeRoles, for roles apply generally, and PyGraphRT Roles to acces data from the specialized PyGraphRT graph model.
- [x] BUG: The current NodeInputDelegate wil update the model on everry stroke, that triggers to update the widget, wich resets its state. For example QLineEdit cursor jumps, ant this will potentially raise other issues with other InputEditors as well.

- [x] Implement NodeListmodel Adapter and NodeListSelectionAdapter, to convert a Graphmodel (and its selection model)
      to standard QItemModels that standard QT view understand.

- [x] distinguishe the current and selected nodes in the graphivew. 
- [x] indicate cursor linenumber on the code editor even when its not active.
      for example highlight the numbers on the left. the cursor is not visible, when the code editor is not active.
- [x] go to the operator line in the module script when a node is selected.
- [x] Update data on each keystroke, when setting values for inputs.
      this probably needs a nodeTreeModel refactor,
      so it wont reset the model all the time, and recreate the whole view each time it receives an update.
- [x] How to use input signal instead of finished editing in the NodeInputDelegate?
- [x] Why its not able to use standard QLayouts?
      Turns out using layout would overcomplicate things
- [x] fix saving and loading broken graphs
      `create_placeholder_operator`
      when saving and opening a broken graph, the node operators loose binding to the broken operator
      so when i fix the script, it will note bind back, instead, the node seem to hold None as teh operator.
      his is broken on open, and probably on save as well.
- [ ] Consider Support discovering and reloading editor providers after startup, synchronizing
      provider instances across existing delegates and refreshing visible editors.
      this could be a nice development feature.


## Known Limitations and BUGS
- [ ] TODO: Investigate PyQt Python-object property conversion failure.
      - Create a minimal QObject with Property(object, ...) returning a pathlib.Path.
      - Compare direct property access with QMetaProperty.read() / write().
      - Repeat with a plain custom Python object and a str control.
      - Record Python, PyQt6, Qt, and PyQt6-sip versions; reproduce in a clean environment.
      - Check upstream reports and report a minimal reproduction if needed.
      Observed locally with PyQt 6.11.0: meta-property reads fail for both Path and custom objects with unable to convert ... to a C++ 'PyQt_PyObject' instance. Cause remains unknown.
      Current workaround: call QPathEdit.getPath() / setPath() directly through the provider.

## Inspector dev

- [x] expose the inlets, based on the operator, and the actual inputs. 
- [x] create a TreeView using the rt.GraphDefinition and rt.moduleRegistry directly.
      (note: we are dliberatelly bypassing the current GraphModel. 
      exposing these data might not makes sense for the graph.
      also the GraphModel interface is not yet finalized. eg using NodeNames instead of 'ModelKey' analoge to the QModelIndex. see other todos.)


## Restore Session

- [x] Two details in the current code also need fixing for restoration: fromfile() ignores saved node positions, and _connectDocument() always rearranges the nodes. Imported modules with relative paths also need a stable base directory when the snapshot lives in AppData.  


## fix open and save

- [x] open the lates session, on launch
- [x] Recents
- [x] Fix saving opening in the GUI


## GraphView

- [ ] a delegate, to draw custom nodes. with potentially custom roles in a custom GraphModel.


## Inspector

- [x] register InspectorInputs eidtors
      -> Now node_inspector_view uses Delegates to
         create a formview with appropriate editors
         implemented a data editor plugin system


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

- [ ] consider adding a rename method to the node_ref. it would probaly change the NodeRef hash. so it might not be a good idea. Unless NodeRefs are used by their objectid under the hood, and not its hash.

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
      what does this mean?
      -> does that mean, that the Graph is responsoble to store relations between 
      nodes<->operators? this is true now. and Nodes are holding the funcionts.

- [x] Consider GraphRT responsibility to be nodes and links only. and factor out, the python script-like additions: operators, modules etc. \#pygraph
      -> Now Nodes hold callables. GraphRT is no more responsible for modules, but
      responsible for node<->operator relation
- [x] consider using references inside the GraphRT datastructure.
      eg graph.output, node.inputs, node.operators etc. \#pygraph
- [x] when a node is removed, the GraphRT.output still holds on to it.
      when a node is removed, and its the actual ouput, set the output to None \#pygraph
- [x] add test for cycle detection.
      just caught a bug where two nodes were connected twice and it detected it as a cycle \#pygraph



