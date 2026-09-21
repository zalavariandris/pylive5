- [ ] consider adding Roles (same as QT uses for models) to the Graphmodel.
      NodeTitleRole
      NodeMessageRole
      NodeInletsRole?
      ... NodeBody Role

- [ ] add option, to show broken links. links are broken, when points to nodes that are not in the model.
      a link can be broken in multiple ways:
      - link has source, but no target, or has target node but no source
      - link has no source neither target. how to show that?
      - link has source and target, but points to missing ports? it should be pointing to the node direclty
    when the show broken links is off, skip broken links!
    
- [ ] consider adding addLinks and removeLinks abstract methods for the AnstractDagmodel. With this move, consider making the DirectionalLink a concrete class. 

   if soo, we need to think about multiple links between the same ports? not really, since the same port will not be connected multiple time. multiple links make sense only, when the links are connected directly to the nodes. specifying source outlet and target inlet is enough for now. If we decide to make the Link a concrete class, then 'linkSource' and 'linkTarget' would become obsolete.
   think about this carefully, how 'abstract' this model should be.