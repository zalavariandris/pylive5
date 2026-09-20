# PyFlow refactor plan

## Objective

Make graph editing reliable, establish one owner for the active runtime, and keep the window focused on presentation. Preserve the reusable DAG editor API and the separation between runtime execution and graph rendering.

This is a staged plan, not authorization to implement every stage at once. Complete and validate each stage before proceeding to its dependents. Recheck the current code before implementation because the workspace is actively changing.

## Intended responsibilities

| Component | Responsibility |
| --- | --- |
| `GraphRT` | Nodes, operators, input bindings, execution, cache, and runtime change events. |
| `PyFlowRTModel` | Adapt runtime state to `AbstractDAGModel`; provide graph editing commands, positions, and consistent view notifications. |
| `PyFlowSession(QObject)` | Own the active runtime and script modules; manage output selection, watchers, execution results/errors, and reset. |
| `PyFlow5Window` | Construct widgets and actions; show dialogs; connect selection to session output; display results. |
| `DirectionalGraphView5` | Render the model, navigate the graph, and emit interaction requests. |
| `GraphSelectionModel` | Maintain selection and reconcile it with model changes. |

The session owns the graph lifecycle. The adapter holds a reference to the session's active graph. The window must not keep a second independently replaceable graph reference. Keep the adapter in PyFlow5 because it connects the runtime to the DAG editor.

## 1. Establish behavior and a test baseline

- [ ] Run the existing model, runtime mutation, watcher, and DAG selection tests. Record unrelated failures separately.
- [ ] Add focused regression tests alongside the fixes in later stages; current model tests primarily exercise inlet/link queries.
- [ ] Specify link replacement and disconnection behavior before implementing them. Disconnecting one inlet must preserve the identities and bindings of all other parameters, including literals and repeated references to the same source.
- [ ] Decide how to represent an unbound positional input. If the runtime cannot express a hole, implement the necessary binding representation/API first, or explicitly reject unsupported disconnections without changing state. Do not silently shift later arguments.
- [ ] Define node deletion: handle incoming/outgoing references, positions, selection, and active output consistently. Choose whether referenced nodes can be deleted and how downstream inputs become unbound.
- [ ] Define what "Restart Kernel" means: cache invalidation, module re-execution, or graph replacement. Specify which graph bindings, positions, selection, and output should survive. Do not rebuild a graph from an operator-only script by assumption.

**Completion gate:** editing and restart behavior have explicit expected outcomes that can be tested without constructing the main window.

## 2. Establish the change-notification contract

Do this before adding new UI editing paths or extracting session ownership.

- [ ] Make the adapter observe runtime changes, including changes initiated outside the adapter. Inspect runtime and module events needed for node additions/removals, input changes, and operator signature changes.
- [ ] Choose one implementation for correct notification timing:
  - Add runtime before/after events and translate them in the adapter; or
  - Maintain an adapter presentation snapshot and bracket snapshot updates with DAG-model notifications.
- [ ] Do not emit an "about to change" signal after the state visible through the model has already changed.
- [ ] Use one notification path for adapter commands and external runtime mutations. Avoid manual begin/end calls that duplicate translated runtime events.
- [ ] Validate commands before beginning a change. Specify failure behavior so failed mutations leave state consistent and never leave `_message_queue` unfinished. A `finally` block that announces success is not a rollback strategy.
- [ ] Materialize iterable command arguments once. Treat empty edits as no-ops.
- [ ] Add explicit subscription/disconnection handling for graph replacement and teardown.
- [ ] Check the view and selection model's subscriptions against this contract. Removal repainting must not require querying a node or link that has already disappeared; capture affected geometry before removal or invalidate an appropriate larger region.

**Completion gate:** tests demonstrate correct old/new state during notifications, exactly one notification sequence per edit, external edits reaching observers, and no callbacks from a detached runtime.

## 3. Repair model commands and API contracts

Build on the behavior from stage 1 and notification mechanism from stage 2.

- [x] Replace `removeNodes()` calls to nonexistent `GraphRT.get_node()` with a supported lookup. Avoid adding a lookup cache until needed.
- [ ] Fix `addLink()` to handle immutable positional arguments and commit both positional and keyword updates through `set_inputs()`.
- [ ] Validate node existence, inlet/outlet validity, and link replacement before mutation. Emit removal/replacement notifications for any displaced link.
- [ ] Fix `removeLinks()` to target the requested inlet only, support literal arguments, and preserve other bindings according to stage 1.
- [ ] Fix `outLinks()` variable shadowing and filter by the requested outlet.
- [x] Implement `addNode(operator, position)` as the public UI command. Arrange initialization so observers can read a valid position when the node becomes visible.
- [ ] Make `setNodePosition()` honor its base-class return contract, use `position is not None`, safely clear missing positions, and emit movement notifications only for actual changes.
- [ ] Clean up positions when nodes are removed. Apply an explicit preservation/clearing policy when the runtime changes.
- [ ] Reconcile base and implementation annotations: iterable versus tuple returns, two-element endpoint tuples, optional node lookup results, and mutation return types. Update affected implementations together.
- [ ] Ensure operator signature changes refresh ports and affected links in the view.

**Completion gate:** model tests cover positional/keyword/mixed bindings, repeated sources, literals, invalid and empty commands, generator inputs, node deletion, movement, external runtime changes, and operator signature updates. Existing query tests still pass.

## 4. Extract session ownership and execution lifecycle

Once model operations and runtime replacement are reliable, introduce `pyflow_session.py`.

- [ ] Create `PyFlowSession(QObject)` to own the runtime, script modules, graph adapter, output node, and watcher lifecycle. Expose the graph read-only where direct access is necessary.
- [ ] Move output selection, watcher start/stop, and evaluation orchestration out of the window. Execution remains implemented by `GraphRT`.
- [ ] Expose output/result/error signals and public commands for script updates and the restart behavior chosen in stage 1. Keep widgets out of the session.
- [ ] Expose available operators using public runtime/module APIs instead of `_G._local_module`.
- [ ] Clear the displayed result when output is cleared or removed; define behavior on execution failure rather than leaving stale success visible.
- [ ] Implement explicit shutdown that stops watchers and disconnects signals. Do not rely only on garbage collection.
- [ ] Implement reset/replacement as one coordinated lifecycle: prepare any replacement, stop old observation, clear or remap output, switch the graph and adapter, reconcile selection/positions, establish new observation, and refresh results.
- [ ] Reject foreign or deleted output references and ensure old runtime events cannot update the new session.

**Completion gate:** tests without a main window cover output changes, clearing/deleting output, failed execution, restart/replacement, old-runtime isolation, and shutdown.

## 5. Rewire and simplify the window

Only remove the old ownership path once the session behavior is tested.

- [ ] Construct/inject one session and bind its adapter to the graph view.
- [ ] Route operator-dialog acceptance through `model.addNode()`. Keep dialog creation and selection in the window.
- [ ] Route link and node removal requests through tested model commands.
- [ ] Keep `GraphSelectionModel` separate. Connect selection to the session's output command and define output selection deterministically.
- [ ] Connect script-editor changes to the session/module API. Keep cursor and scroll preservation in the UI layer; preserve the same-value guard and block feedback signals when appropriate.
- [ ] Connect session results/errors to the display widget; remove window-owned runtime execution and watchers.
- [ ] Route the restart action to the session and remove the obsolete `graph_utils.graph_from_script` path.
- [ ] Stop the session on window shutdown, following the chosen ownership policy.
- [ ] Install the splitter directly with `setCentralWidget()`, or place a layout on a dedicated central widget. Do not install a layout on `QMainWindow` itself.
- [ ] Remove redundant lambdas, unused imports, debug prints, and obsolete output signals after their replacements are connected.
- [ ] Decide whether the `source` argument to node creation should auto-connect the new node; implement and test it or remove the unsupported affordance explicitly.

**Completion gate:** a Qt integration test can create, move, connect, disconnect, select, delete, edit an operator, restart, and close the window with consistent model state and output.

## 6. Validate the result and defer unrelated expansion

- [ ] Run affected runtime, model, selection/view, watcher, and window tests together.
- [ ] Run configured type checking and fix contract errors introduced by the refactor. Distinguish pre-existing typing issues.
- [ ] Manually smoke-test repainting, selection, keyboard actions, operator dialogs, and output clearing.
- [ ] Verify that the window has no private runtime access or independently mutable active-graph field.
- [ ] Document graph ownership, notification timing, reset semantics, and connection teardown near the relevant APIs.

Do not introduce threading, persistence, undo/redo, or a general controller framework as part of this refactor. Synchronous execution currently runs from UI callbacks; background execution needs a separate design for thread affinity, cancellation, and result ownership. Keep the custom DAG model unless a concrete requirement calls for Qt item-view interoperability.

## Suggested commit order

1. Define mutation/reset behavior and add any required runtime binding support.
2. Establish runtime-to-adapter notifications and observer lifecycle tests.
3. Repair graph commands and base-model contracts with regression tests.
4. Introduce the session and test execution/reset/shutdown independently.
5. Rewire the window and add integration coverage.
6. Remove obsolete paths and document the resulting boundaries.

Each commit should leave its supported paths working. Stage implementation may need to migrate existing command notifications together with the event bridge to avoid an intermediate double-notification state.
