from contextlib import contextmanager
from pathlib import Path
import av
import numpy as np
from tqdm import tqdm

from kgb_workflows.utils import FileSequence, transform_colorspace


@contextmanager
def read_video(path_or_sequence: FileSequence|Path, fps=24):
    """
    Opens either a normal video file or a FileSequence of DPX/EXR/etc.
    Yields frames as float32 RGBA in the range [0, 1].
    """
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
        container = av.open(path_or_sequence)
        total = container.streams.video[0].frames  # may be 0 if unknown

    try:
        class Source:
            def __init__(self):
                self.frames = self._frames()
                self.total = total
                self.width = container.streams.video[0].width
                self.height = container.streams.video[0].height

            def _frames(self):
                for frame in container.decode(video=0):
                    # DPX / high-bit-depth → float32 [0,1]
                    rgb = frame.to_ndarray(format="rgb48le").astype(np.float32) / 65535.0
                    rgba = np.ones((*rgb.shape[:2], 4), dtype=np.float32)
                    rgba[..., :3] = rgb
                    yield rgba

        yield Source()
    finally:
        container.close()


@contextmanager
def write_video(path, width, height, fps=24, codec="libx264"):
    """
    Creates an H.264 MP4 writer.
    Call .write(rgba_float32) for every frame.
    """
    path = Path(path)
    container = av.open(str(path), mode="w")
    stream = container.add_stream(codec, rate=fps)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"

    class Writer:
        def write(self, img):
            # Expect float32 RGB(A) in [0,1]
            rgb8 = (np.clip(img[..., :3], 0, 1) * 255).astype(np.uint8)
            frame = av.VideoFrame.from_ndarray(rgb8, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)

        def close(self):
            # flush encoder
            for packet in stream.encode():
                container.mux(packet)
            container.close()

    writer = Writer()
    try:
        yield writer
    finally:
        writer.close()