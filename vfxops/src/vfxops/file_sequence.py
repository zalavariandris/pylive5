from os import PathLike
from pathlib import Path


class FileSequence:
    def __init__(self, pattern:str, first:int, last:int):
        self.pattern = pattern
        self._first = first
        self._last = last

    @property
    def first(self) -> int:
        return self._first

    @property
    def last(self) -> int:
        return self._last

    def get_path(self, frame:int) -> Path:
        if frame < self.first or frame > self.last:
            raise IndexError("Frame out of range")
        return Path(self.pattern % frame)

    @staticmethod
    def _detect_frame_range(pattern:str) -> tuple[int, int]:
        """Returns the first and last frame numbers in the image sequence."""
        # match all files in the sequence, to get all frame numbers
        import re
        import glob
        import os
        """filepath: path pattern with printf style format, e.g. 'image_%04d.png'"""
        
        # Extract directory and filename pattern
        path_obj = Path(pattern)
        parent_dir = path_obj.parent
        filename_pattern = path_obj.name
        
        if not parent_dir.exists():
            raise Exception(f"No such directory: '{parent_dir.absolute()}'")
        
        # Convert printf pattern (e.g., %04d) to regex pattern
        # Match patterns like %04d, %05d, %d, etc.
        regex_pattern = re.sub(r'%0?(\d*)d', r'(\\d+)', filename_pattern)
        regex_pattern = f"^{regex_pattern}$"
        
        # Find all matching files and extract frame numbers
        frames = {}
        for file_path in parent_dir.glob("*" + path_obj.suffix):
            match = re.match(regex_pattern, file_path.name)
            if match:
                frame_num = int(match.group(1))
                frames[frame_num] = file_path

        first_frame = min(frames.keys()) if frames else None
        last_frame = max(frames.keys()) if frames else None
        
        
        if not frames:
            raise ValueError(f"No image files found matching pattern: '{pattern}'")
        
        frame_numbers = sorted(frames.keys())
        first_frame = frame_numbers[0]
        last_frame = frame_numbers[-1]

        # warn for missing frames
        expected_frames = set(range(first_frame, last_frame+1))
        missing_frames = expected_frames - set(frame_numbers)
        if missing_frames:
            print(f"Warning: Missing frames in sequence: {sorted(missing_frames)}")

        return first_frame, last_frame

    @staticmethod
    def _detect_pattern_from_frame(path:PathLike) -> str:
        path_obj = Path(path)
        if not path_obj.exists():
            raise ValueError(f"File does not exist: '{path}'")
        import re
        match = re.search(r'(\d+)(?=\.\w+$)', path_obj.name)
        if not match:
            raise ValueError(f"Cannot detect frame number in file: '{path}'")
        pattern = path_obj.name.replace(match.group(1), f"%0{len(match.group(1))}d")
        return str(path_obj.parent / pattern)

    @classmethod
    def from_single_frame(cls, frame:PathLike) -> "FileSequence":
        pattern = cls._detect_pattern_from_frame(frame)
        first, last = cls._detect_frame_range(pattern)
        return cls(pattern=pattern, first=first, last=last)
        