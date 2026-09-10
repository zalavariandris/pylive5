# TODO

- [ ] allow adding and updating operator in GraphRT.
  GraphRT should be allowed to load and reaload(!) 
  operators from a python script!
  carefully figure out an interface for graphrt, to load operators from a script, and add it to the runtime.
  maybe graphrt should only be responsible for managing nodes and links, and keep a reference to OperatorCollections?
  pretty much like python does with imports, except this must update while the app is running.
  a GraphRT runtime that is changed live should behave exactly as one that was first started(except cache)
  GraphRT executuin must be deterministic. ALmost like a pure function, where subfunctino are change on the fly

    


## ExampleApps
- [ ] Image Grade
  - [ ] node graph, with image operators: 
    - [ ] read, write
    - [ ] exposure
    - [ ] colorgrade
    - [ ] cornerpin
    - [ ] temperature, tint
    - [ ] blur