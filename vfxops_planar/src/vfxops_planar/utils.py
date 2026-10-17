from typing import Tuple
from pathlib import Path
import warnings


# utils
def get_sequence_frame_range(image_sequence_pattern: str) -> Tuple[int, int]:
    """Returns the first and last frame numbers in the image sequence."""
    # match all files in the sequence, to get all frame numbers
    import re
    import glob
    import os
    """filepath: path pattern with printf style format, e.g. 'image_%04d.png'"""
    
    # Extract directory and filename pattern
    path_obj = Path(image_sequence_pattern)
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
        raise ValueError(f"No image files found matching pattern: '{image_sequence_pattern}'")
    
    frame_numbers = sorted(frames.keys())
    first_frame = frame_numbers[0]
    last_frame = frame_numbers[-1]

    # warn for missing frames
    expected_frames = set(range(first_frame, last_frame+1))
    missing_frames = expected_frames - set(frame_numbers)
    if missing_frames:
        warnings.warn(f"Warning: Missing frames in sequence: {sorted(missing_frames)}")

    return first_frame, last_frame
