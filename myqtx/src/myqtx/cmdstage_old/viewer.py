"""Compatibility entry point for the command-line viewer."""

import sys

from myqtx.cmdstage.viewer import ViewerServer, main

__all__ = ["ViewerServer", "main"]

if __name__ == "__main__":
    sys.exit(main())
