"""Transfer built-in display objects using JSON and shared-memory arrays."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from math import prod
from multiprocessing import shared_memory
from typing import Any

import numpy as np

from .data import HTML, Image, ImageCompare, Markdown


MAX_ARRAY_BYTES = 1024 * 1024 * 1024
DISPLAY_TYPES = {
    "image": Image,
    "html": HTML,
    "markdown": Markdown,
    "compare": ImageCompare,
}
DISPLAY_KINDS = {datatype: kind for kind, datatype in DISPLAY_TYPES.items()}
Payload = dict[str, Any]


@contextmanager
def encode_payload(data: object) -> Iterator[Payload]:
    """Keep all shared-memory blocks alive until the viewer acknowledges them."""
    blocks: list[shared_memory.SharedMemory] = []
    try:
        yield _encode(data, blocks)
    finally:
        for block in blocks:
            block.close()
            block.unlink()


def _encode(data: object, blocks: list[shared_memory.SharedMemory]) -> Payload:
    if data is None or type(data) in (str, bool, int, float):
        return {"kind": "value", "data": data}
    if isinstance(data, np.ndarray):
        return _encode_array(data, blocks)
    if type(data) in DISPLAY_KINDS:
        return {
            "kind": DISPLAY_KINDS[type(data)],
            "fields": {
                field.name: _encode(getattr(data, field.name), blocks)
                for field in fields(data)
            },
        }
    if isinstance(data, (list, tuple)):
        return {
            "kind": "tuple" if isinstance(data, tuple) else "list",
            "items": [_encode(item, blocks) for item in data],
        }
    if isinstance(data, dict):
        return {
            "kind": "dict",
            "items": [
                [_encode(key, blocks), _encode(value, blocks)]
                for key, value in data.items()
            ],
        }
    raise TypeError(f"Stage transport does not support {type(data).__name__}")


def _encode_array(data: np.ndarray, blocks: list[shared_memory.SharedMemory]) -> Payload:
    if data.dtype.kind not in "buifc":
        raise TypeError("Only numeric and boolean arrays can be sent to Stage")
    if data.nbytes > MAX_ARRAY_BYTES:
        raise ValueError("Array exceeds the 1 GiB transport limit")

    block = shared_memory.SharedMemory(create=True, size=max(1, data.nbytes))
    blocks.append(block)
    # Copy directly into shared memory, including non-contiguous source arrays.
    np.copyto(np.ndarray(data.shape, dtype=data.dtype, buffer=block.buf), data)
    return {
        "kind": "array",
        "name": block.name,
        "shape": list(data.shape),
        "dtype": data.dtype.str,
    }


def decode_payload(payload: Payload) -> object:
    """Reconstruct a payload with owned array storage before acknowledging it."""
    kind = payload["kind"]
    if kind == "value":
        value = payload["data"]
        if value is not None and type(value) not in (str, bool, int, float):
            raise ValueError("Invalid scalar payload")
        return value
    if kind == "array":
        return _decode_array(payload)
    if kind in DISPLAY_TYPES:
        values = {name: decode_payload(value) for name, value in payload["fields"].items()}
        return DISPLAY_TYPES[kind](**values)
    if kind in ("list", "tuple"):
        items = [decode_payload(item) for item in payload["items"]]
        return tuple(items) if kind == "tuple" else items
    if kind == "dict":
        return {decode_payload(key): decode_payload(value) for key, value in payload["items"]}
    raise ValueError(f"Unknown display payload: {kind!r}")


def _decode_array(payload: Payload) -> np.ndarray:
    shape = payload["shape"]
    if not isinstance(shape, list) or len(shape) > 32:
        raise ValueError("Invalid array shape")
    if any(type(size) is not int or size < 0 for size in shape):
        raise ValueError("Invalid array dimensions")
    dtype = np.dtype(payload["dtype"])
    if dtype.kind not in "buifc":
        raise ValueError("Invalid array dtype")
    size = prod(shape) * dtype.itemsize
    if size > MAX_ARRAY_BYTES:
        raise ValueError("Array exceeds the 1 GiB transport limit")

    # Only the sender owns/unlinks the block. Python 3.13 added track=False;
    # on Windows, shared-memory lifetime is determined by open handles.
    if sys.version_info >= (3, 13):
        block = shared_memory.SharedMemory(name=payload["name"], create=False, track=False)
    else:
        block = shared_memory.SharedMemory(name=payload["name"], create=False)
    try:
        if size > block.size:
            raise ValueError("Shared-memory block is too small")
        return np.ndarray(tuple(shape), dtype=dtype, buffer=block.buf).copy()
    finally:
        block.close()
