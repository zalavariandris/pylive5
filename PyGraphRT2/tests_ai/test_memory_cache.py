"""Storage isolation and explicit writes for in-memory caches."""

import pytest

from pygraphrt2.memory_cache import MemoryCache


def test_snapshots_copy_keys_but_borrow_values() -> None:
    value = [1]
    initial = {"value": value}
    cache = MemoryCache(initial)
    initial.clear()
    snapshot = cache.snapshot()
    cache.remove("value")

    assert snapshot["value"] is value
    assert "value" not in cache
    cache.save("replacement", value)
    snapshot.clear()
    assert cache["replacement"] is value


def test_none_is_a_cached_value_and_removal_is_idempotent() -> None:
    cache: MemoryCache[str, int | None] = MemoryCache()
    cache.save("answer", 42)
    cache.save("answer", None)

    assert "answer" in cache
    assert cache["answer"] is None
    assert dict(cache) == {"answer": None}
    cache.remove("answer")
    cache.remove("answer")
    with pytest.raises(KeyError):
        cache["answer"]
    cache.save("other", 7)
    cache.clear()
    assert len(cache) == 0


