"""Run server: `python __main__.py` from repo root (with PYTHONPATH) or use `tspl-driver`."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.app import run

if __name__ == "__main__":
    run()
