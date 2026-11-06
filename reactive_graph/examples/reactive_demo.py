"""Run: python demo_composition.py

A tiny fake video/image implementation demonstrates a nested reactive graph.
Replace Frame/Video with your own OpenCV or image_manips functions.
"""
import asyncio
from dataclasses import dataclass
from typing import Callable
from functools import partial
from reactive_graph import edit, reactive, effect, run, trace, to_dot

from pathlib import Path
import vfxops.core
import vfxops.merge
import vfxops.io
import vfxops.draw
import vfxops.file_sequence
ImageRGBA = vfxops.core.ImageRGBA
FileSequence = vfxops.file_sequence.FileSequence



@reactive
def read_frame(video: FileSequence, frame: int) -> ImageRGBA:
    # todo: this was async!!!
    path = video.get_path(frame)
    return vfxops.io.read_image(path)

@reactive
def image_blend(A: ImageRGBA, B: ImageRGBA, strength: float) -> ImageRGBA:
    return vfxops.merge.merge_over(A, B, mix=strength)


@reactive
def read_video(path: Path)->Callable[[int], ImageRGBA]:
    seq = FileSequence.from_single_frame(path)
    # Returns a frame-producing function with its video already bound.
    # Each invocation builds (or reuses) a tracked read_frame node.
    return partial(read_frame, seq)


@reactive
def blend_frames(video, frame: int, strength: float):
    a = video(frame)
    b = video(frame - 1)
    # Returning a reactive node is fine: the engine flattens it on demand.
    return image_blend(a, b, strength)


@effect
def output(image: ImageRGBA):
    print("DISPLAY:", image)


async def main():
    path = edit("C:/Users/and/Documents/GitHub/pylive5/assets/SMPTE_Color_Bars_animation/SMPTE_Color_Bars_animation_00000.png", name="path")
    frame = edit(5, name="frame")
    strength = edit(0.5, name="strength")
    image = blend_frames(read_video(path), frame, strength)
    watcher = run(output(image))

    for label, change in [
        ("initial request", None),
        ("frame -> 6", lambda: setattr(frame, "value", 6)),
        ("strength -> 0.8", lambda: setattr(strength, "value", 0.8)),
        # ("path -> other.mp4", lambda: setattr(path, "value", "other.mp4")),
    ]:
        trace.clear()
        if change is not None:
            change()
        await watcher.idle()
        print(f"\n{label}\n{trace.format()}\n")

    with open("reactive_graph.dot", "w", encoding="utf-8") as f:
        f.write(to_dot(watcher))
    print("Graph written to reactive_graph.dot")
    watcher.dispose()


if __name__ == "__main__":
    asyncio.run(main())
