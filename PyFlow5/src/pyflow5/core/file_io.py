"""Write complete files without truncating the previous contents on failure."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_text_atomic(path: Path, text: str) -> os.stat_result:
    """Replace a file with UTF-8 text and return the written file's stat."""
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
            written_stat = os.fstat(stream.fileno())
        temporary_path.replace(path)
        return written_stat
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
