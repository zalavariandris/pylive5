from contextvars import ContextVar
from abc import ABC, abstractmethod

class Context:
    def __init__(self, **kwargs):
        self._data = kwargs

    def get(self, key, default=None):
        return self._data.get(key, default)
    
    _current: ContextVar["Context | None"] = ContextVar(
        "current_context", default=None
    )

    @classmethod
    def current(cls) -> "Context":
        context = cls._current.get()

        if context is None:
            raise RuntimeError("No active context")

        return context


class Node(ABC):
    def __init__(self):
        ...

    def request(self, ctx: Context)->Context:
        return ctx

    @abstractmethod
    def compute(self, ctx: Context):
        ...

from dataclasses import dataclass
import numpy as np

@dataclass
class Video:
    frames: dict[int, np.ndarray] = dict()

import numpy as np
class ReadVideo(Node):
    def compute(self, path:str)->Video:
        ctx = Context.current()
        video = Video()
        for frame in ctx.get('frames', []):
            video.frames[frame] = imread(path.format(frame))
        return video


class TemporalBlend(Node):
    def request(self, ctx: Context) -> Context:
        current_frames:dict[int] = ctx.get('frames')
        # extend the frames to include the previous 'duration' frames
        extended_frames = []
        for frame in current_frames:
            for d in range(ctx.get('duration', 1)):
                extended_frames.append(frame - d)
        ctx._data['frames'] = list(set(extended_frames))
        return ctx

    def compute(self, source: Video, duration: int):
        result_frames = Video()
        for frame in range(len(source.frames.values())):
            for d in range(duration):
                blended_frame = source.frames.get(frame - d, np.zeros((480, 640, 3)))
                if frame not in result_frames.frames:
                    result_frames.frames[frame] = blended_frame
                else:
                    result_frames.frames[frame] = (result_frames.frames[frame] + blended_frame) / 2
            result_frames.frames[frame] = source.frames.get(frame, np.zeros((480, 640, 3)))
        return result_frames

def get_video_frame(video: Video, frame: int) -> np.ndarray:
    return video.frames.get(frame, np.zeros((480, 640, 3)))

def operator(func):
    ...

@operator
def blur(source: Video, radius:int):
    ctx = Context.current()
    frame:int = ctx.get('frame')
    source_frame = get_video_frame(source, frame)
    blurred_frame = cv2.GaussianBlur(source_frame, (radius, radius), 0)
    return blurred_frame
