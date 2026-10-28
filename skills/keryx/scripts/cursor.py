#!/usr/bin/env python3
"""The pre-1.2 name of the keryx adapter, kept for one release: this runs keryx.py as __main__ with the same arguments."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("keryx.py")), run_name="__main__")
