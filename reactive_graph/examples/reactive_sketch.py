from pathlib import Path
from typing import Protocol

#reactive framework
def node(func):
    return func

import vfxops.core
import vfxops.merge
import vfxops.io
import vfxops.draw
import vfxops.file_sequence

ImageRGBA = vfxops.core.ImageRGBA
FileSequence = vfxops.file_sequence.FileSequence

class Video(Protocol):
    def __call__(self, frame:int)->ImageRGBA:
        ...


@node
def read_video(file_path:Path)->Video:
    seq = FileSequence.from_single_frame(file_path)
    @node
    def read_image(frame:int)->ImageRGBA:
        frame_path = seq.get_path(frame)
        return vfxops.io.read_image(frame_path)

    return read_image

@node
def timeoffset(video:Video, offset:int)->Video:
    @node
    def compute(frame:int)->ImageRGBA:
        return video(frame + offset)
    return compute

@node
def merge_video(A:Video, B:Video, mix:float=0.5)->Video:
    @node
    def compute(frame:int)->ImageRGBA:
        imgA = A(frame)
        imgB = B(frame)
        return vfxops.merge.merge_over(imgA, imgB, mix=mix)
    return compute

@node
def get_video_frame(video:Video, frame:int)->ImageRGBA:
    return video(frame)

class Graph:
    def __enter__(self):
        # Initialize the graph context
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # Clean up the graph context
        pass

if __name__ == "__main__":
    with Graph() as graph:
        plate = read_video(Path("assets/SMPTE_Color_Bars_animation/SMPTE_Color_Bars_animation_00000.png"))
        dream = timeoffset(plate, 5)
        comp = merge_video(plate, dream)
        print(get_video_frame(comp, 0))
