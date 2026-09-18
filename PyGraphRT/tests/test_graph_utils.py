import pytest
import pygraphrt as rt

def test_get_links():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    @G.node()
    def three() -> int:
        return 3

    @G.node(a=two, b=three)
    def add(a:int, b:int) -> int:
        return a + b

    assert rt.graph_utils.get_in_links(G, add) == {
        (two, "a", add), 
        (three, "b", add)
    }, "get_in_links should return the correct input links"

    assert rt.graph_utils.get_out_links(G, two) == {
        (two, "a", add)
    }, "get_out_links should return the correct output links for node two"

    assert rt.graph_utils.get_out_links(G, three) == {
        (three, "b", add)
    }, "get_out_links should return the correct output links for node three"

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
