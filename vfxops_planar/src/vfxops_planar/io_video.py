from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import av
import numpy as np

from .core import Image, ImageRGBA, validate_image_data
from .file_sequence import FileSequence
from .io import _frame_to_rgba


class _VideoSource:
    def __init__(self, container: av.container.InputContainer, total: int) -> None:
        self._container = container
        self.total = total
        self.width = container.streams.video[0].width
        self.height = container.streams.video[0].height
        self.frames = self._frames()

    def _frames(self) -> Iterator[ImageRGBA]:
        for frame in self._container.decode(video=0):
            yield _frame_to_rgba(frame)


@contextmanager
def read_video(path_or_sequence: FileSequence | Path, fps: int = 24) -> Iterator[_VideoSource]:
    """Yield a source whose frames are planar float32 RGBA, preserving float HDR."""
    if isinstance(path_or_sequence, FileSequence):
        container = av.open(
            path_or_sequence.pattern,
            format="image2",
            options={
                "start_number": str(path_or_sequence.first),
                "framerate": str(fps),
            },
        )
        total = path_or_sequence.last - path_or_sequence.first + 1
    else:
        container = av.open(str(path_or_sequence))
        total = container.streams.video[0].frames

    try:
        yield _VideoSource(container, total)
    finally:
        container.close()


class _VideoWriter:
    def __init__(
        self,
        container: av.container.OutputContainer,
        stream: av.video.stream.VideoStream,
    ) -> None:
        self._container = container
        self._stream = stream

    def write(self, img: Image) -> None:
        """Write a planar float32 RGB or RGBA frame, discarding alpha."""
        validate_image_data(img, channels=(3, 4))
        if img.shape[1:] != (self._stream.height, self._stream.width):
            raise ValueError("Frame dimensions must match the video writer")
        rgb = np.clip(img[:3], 0.0, 1.0)
        rgb *= np.float32(255.0)
        rgb8 = np.ascontiguousarray(np.moveaxis(rgb.astype(np.uint8), 0, -1))
        frame = av.VideoFrame.from_ndarray(rgb8, format="rgb24")
        for packet in self._stream.encode(frame):
            self._container.mux(packet)

    def close(self) -> None:
        try:
            for packet in self._stream.encode():
                self._container.mux(packet)
        finally:
            self._container.close()


@contextmanager
def write_video(
    path: Path,
    width: int,
    height: int,
    fps: int = 24,
    codec: str = "libx264",
) -> Iterator[_VideoWriter]:
    """Create a video writer accepting planar float32 RGB(A) frames."""
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream(codec, rate=fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
    except Exception:
        container.close()
        raise

    writer = _VideoWriter(container, stream)
    try:
        yield writer
    finally:
        writer.close()
