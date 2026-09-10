import symtable

def build_dependency_graph(source: str) -> dict[str, set[str]]:
    """Return direct lexical dependencies as ``scope -> referenced bindings``.

    Module bindings use plain names; nested bindings use qualified names such
    as ``outer.inner`` or ``outer.value``. Every target has a graph entry, even
    if it has no dependencies. Unresolved globals (including builtins) use the
    ``<external>.`` prefix. The module scope is named ``<module>``.

    Symbol tables parse the source without executing it and resolve locals,
    globals, and closure captures. References to parameters and local variables
    are retained as leaf nodes. Imports remain local bindings; attribute targets,
    runtime aliases, and assignment data flow are not resolved. Defaults and
    decorators belong to the scope evaluating them, not the function body.
    Edges indicate potential dependencies, not proven behavioral changes.
    """
    module = symtable.symtable(source, "<source>", "exec")
    graph: dict[str, set[str]] = {}

    def binding_name(scope_name: str, name: str) -> str:
        return name if scope_name == "<module>" else f"{scope_name}.{name}"

    def bound(table: symtable.SymbolTable, name: str) -> bool:
        try:
            symbol = table.lookup(name)
        except KeyError:
            return False
        return symbol.is_local() or symbol.is_parameter() or symbol.is_imported()

    def visit(
        table: symtable.SymbolTable,
        scope_name: str,
        ancestors: list[tuple[symtable.SymbolTable, str]],
    ) -> None:
        dependencies = graph.setdefault(scope_name, set())
        for symbol in table.get_symbols():
            name = symbol.get_name()
            if bound(table, name):
                graph.setdefault(binding_name(scope_name, name), set())
            if not symbol.is_referenced():
                continue
            if symbol.is_global():
                target = name if bound(module, name) else f"<external>.{name}"
            elif symbol.is_free() or symbol.is_nonlocal():
                target = f"<external>.{name}"
                for parent, parent_name in reversed(ancestors):
                    # Class namespaces do not supply ordinary closure bindings.
                    if parent.get_type() == "class":
                        if name == "__class__":
                            target = parent_name
                            break
                        continue
                    if bound(parent, name):
                        target = binding_name(parent_name, name)
                        break
            else:
                target = binding_name(scope_name, name)
            dependencies.add(target)
            graph.setdefault(target, set())

        for child in table.get_children():
            name = child.get_name()
            if name in {"lambda", "listcomp", "setcomp", "dictcomp", "genexpr"}:
                name = f"<{name}@{child.get_lineno()}>"
            visit(
                child,
                binding_name(scope_name, name),
                [*ancestors, (table, scope_name)],
            )

    visit(module, "<module>", [])
    return graph