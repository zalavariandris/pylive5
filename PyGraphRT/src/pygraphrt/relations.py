from typing import Generic, TypeVar
ParentT = TypeVar("ParentT")
ChildT = TypeVar("ChildT")

class ManyToOneRelation(Generic[ChildT, ParentT]):
    def __init__(self) -> None:
        self._children: dict[ParentT, set[ChildT]] = {}
        self._parent: dict[ChildT, ParentT] = {}

    def set(self, child: ChildT, parent: ParentT) -> None:
        old_parent = self._parent.get(child)

        if old_parent is not None and old_parent != parent:
            self.delete(child, old_parent)

        self._children.setdefault(parent, set()).add(child)
        self._parent[child] = parent

    def delete(self, child: ChildT, parent: ParentT, ) -> None:
        if self._parent.get(child) != parent:
            return

        children = self._children.get(parent)

        if children is not None:
            children.discard(child)

            if not children:
                del self._children[parent]

        del self._parent[child]

    def children_of(self, parent: ParentT) -> frozenset[ChildT]:
        return frozenset(self._children.get(parent, ()))

    def parent_of(self, child: ChildT) -> ParentT | None:
        return self._parent.get(child)


LeftT = TypeVar("LeftT")
RightT = TypeVar("RightT")
class OneToOneRelation(Generic[LeftT, RightT]):
    def __init__(self) -> None:
        self._left_to_right: dict[LeftT, RightT] = {}
        self._right_to_left: dict[RightT, LeftT] = {}

    def add(self, left: LeftT, right: RightT) -> None:
        self._left_to_right[left] = right
        self._right_to_left[right] = left

    def remove(self, left: LeftT, right: RightT) -> None:
        assert self._left_to_right.get(left) == right, "The left and right pair does not match"

        del self._left_to_right[left]
        del self._right_to_left[right]

    def left_of(self, right: RightT) -> LeftT | None:
        return self._right_to_left.get(right)

    def right_of(self, left: LeftT) -> RightT | None:
        return self._left_to_right.get(left)

class ManyToManyRelation(Generic[LeftT, RightT]):
    def __init__(self) -> None:
        ...

    def add(self, left: LeftT, right: RightT) -> None:
        ...

    def remove(self, left: LeftT, right: RightT) -> None:
        ...

    def left_of(self, right: RightT) -> frozenset[LeftT]:
        ...

    def right_of(self, left: LeftT) -> frozenset[RightT]:
        ...