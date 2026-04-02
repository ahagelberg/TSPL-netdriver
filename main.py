"""Backward compatibility: the ASGI app and CLI entry live in ``api.app``."""

from __future__ import annotations

import sys
from pathlib import Path

# When the console script imports ``main`` without a proper editable install, or cwd
# is not the project root, ensure the repo root (directory containing this file) is on
# ``sys.path`` so ``import api`` resolves.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.app import create_app, get_app, run

__all__ = ["create_app", "get_app", "run"]
